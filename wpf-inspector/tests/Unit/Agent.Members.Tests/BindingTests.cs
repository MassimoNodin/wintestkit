using System;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;
using Xunit;
using static WinTestKit.Inspector.Agent.Members.Tests.ValueTestSupport;
namespace WinTestKit.Inspector.Agent.Members.Tests
{
 public sealed class BindingTests
 {
  private sealed class Counter : IValueConverter, IMultiValueConverter
  {
   public int Forward, Back;
   public object Convert(object value, Type type, object parameter, CultureInfo culture) { Forward++; return value; }
   public object ConvertBack(object value, Type type, object parameter, CultureInfo culture) { Back++; return value; }
   public object Convert(object[] values, Type type, object parameter, CultureInfo culture) { Forward++; return values[0]; }
   public object[] ConvertBack(object value, Type[] types, object parameter, CultureInfo culture) { Back++; return new[] { value }; }
  }
  private sealed class Source { public string Name { get; set; } = "hello"; public string Password { get; set; } = "secret"; }
  private sealed class AccountConverter : IValueConverter
  {
   public object Convert(object value, Type type, object parameter, CultureInfo culture) => value;
   public object ConvertBack(object value, Type type, object parameter, CultureInfo culture) => value;
  }
  private static BindingInfoDto Read(DependencyObject target, DependencyProperty property)
  {
   var inspector = new ObjectInspector();
   string key = inspector.GetMembers(target, new System.Collections.Generic.List<Diagnostic>()).Single(x => x.PathSegment?.Kind == "dependency" && x.PathSegment.Name == property.Name && x.PathSegment.OwnerType == property.OwnerType.FullName).MemberKey;
   var value = Assert.Single(inspector.GetBindings(target, new[] { key }));
   byte[] bytes = StrictJson.Serialize(value.ToJson()); var copy = BindingInfoDto.FromJson(StrictJson.Parse(bytes, 0, bytes.Length));
   Assert.Equal(bytes, StrictJson.Serialize(copy.ToJson())); return copy;
  }
  [Fact] public void SingleBindingReadsMetadataWithoutInvokingConverter()
  {
   Sta(() => { var target = new TextBox(); var source = new Source(); var converter = new Counter();
    BindingOperations.SetBinding(target, TextBox.TextProperty, new Binding("Name") { Source = source, Converter = converter, Mode = BindingMode.TwoWay, UpdateSourceTrigger = UpdateSourceTrigger.Explicit });
    int forward = converter.Forward, back = converter.Back; var info = Read(target, TextBox.TextProperty);
    Assert.Equal("binding", info.Kind); Assert.Equal("Name", info.Path); Assert.Equal("TwoWay", info.Mode); Assert.Equal("Explicit", info.UpdateSourceTrigger);
    Assert.Equal(typeof(Source).FullName, info.SourceType); Assert.Equal(typeof(Counter).FullName, info.ConverterType);
    Assert.Equal(forward, converter.Forward); Assert.Equal(back, converter.Back); Assert.Equal("hello", source.Name);
    BindingOperations.ClearBinding(target, TextBox.TextProperty); Assert.Equal("none", Read(target, TextBox.TextProperty).Kind);
   });
  }
  [Fact] public void AdditionalRulesSuppressBindingStringsAndSensitiveTargets()
  {
   Sta(() => {
    var target = new TextBox();
    BindingOperations.SetBinding(target, TextBox.TextProperty, new Binding("AccountNumber") { ElementName = "AccountSource", Converter = new AccountConverter() });
    var inspector = new ObjectInspector(new[] { "account" });
    string key = inspector.GetMembers(target, new System.Collections.Generic.List<Diagnostic>()).Single(x => x.PathSegment?.Kind == "dependency" && x.PathSegment.Name == "Text" && x.PathSegment.OwnerType == typeof(TextBox).FullName).MemberKey;
    var value = Assert.Single(inspector.GetBindings(target, new[] { key }));
    Assert.Null(value.Path); Assert.Null(value.ElementName); Assert.Null(value.SourceType); Assert.Null(value.ConverterType);
    var targetPolicy = new ObjectInspector(new[] { "text" });
    var error = Assert.Throws<ProtocolException>(() => targetPolicy.GetBindings(target, new[] { key }));
    Assert.Equal(ErrorCodes.AccessDenied, error.Code); Assert.DoesNotContain("text", error.Message, StringComparison.OrdinalIgnoreCase);
   });
  }
  private sealed class ErrorContent { public override string ToString() => throw new InvalidOperationException(); }
  [Fact] public void ValidationAndRelativeSourceAreReadWithoutFormattingErrorContent()
  {
   Sta(() => {
    var target = new TextBox();
    var expression = BindingOperations.SetBinding(target, TextBox.TextProperty, new Binding("Name") { RelativeSource = new RelativeSource(RelativeSourceMode.Self) });
    Validation.MarkInvalid(expression, new ValidationError(new ExceptionValidationRule(), expression, new ErrorContent(), null));
    var info = Read(target, TextBox.TextProperty);
    Assert.Equal(typeof(ErrorContent).FullName, Assert.Single(info.ValidationErrors!));
    Assert.NotNull(info.RelativeSource);
    Validation.ClearInvalid(expression);
   });
  }
  [Fact] public void CompositeBindingsAndSensitivePathAreMetadataOnly()
  {
   Sta(() => { var target = new TextBox(); var source = new Source(); var converter = new Counter();
    var multi = new MultiBinding { Converter = converter }; multi.Bindings.Add(new Binding("Name") { Source = source }); multi.Bindings.Add(new Binding("Password") { Source = source });
    BindingOperations.SetBinding(target, TextBox.TextProperty, multi); int forward = converter.Forward, back = converter.Back; var info = Read(target, TextBox.TextProperty);
    Assert.Equal("multiBinding", info.Kind); Assert.Equal(2, info.Children!.Count); Assert.Equal("Name", info.Children[0].Path); Assert.Null(info.Children[1].Path); Assert.Null(info.Children[1].SourceType);
    Assert.Equal(forward, converter.Forward); Assert.Equal(back, converter.Back);
    var priority = new PriorityBinding(); priority.Bindings.Add(new Binding("Name") { Source = source, Converter = converter }); BindingOperations.SetBinding(target, TextBox.TextProperty, priority);
    forward = converter.Forward; back = converter.Back; info = Read(target, TextBox.TextProperty); Assert.Equal("priorityBinding", info.Kind); Assert.Single(info.Children!); Assert.Equal(forward, converter.Forward); Assert.Equal(back, converter.Back);
   });
  }
 }
}
