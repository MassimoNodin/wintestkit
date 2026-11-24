using System;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Threading;
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
  private static BindingInfoDto Read(DependencyObject target, DependencyProperty property) => Read(target, property, new ObjectInspector(), new Registry());
  private static BindingInfoDto Read(DependencyObject target, DependencyProperty property, ObjectInspector inspector, Registry registry)
  {
   string key = inspector.GetMembers(target, new System.Collections.Generic.List<Diagnostic>()).Single(x => x.PathSegment?.Kind == "dependency" && x.PathSegment.Name == property.Name && x.PathSegment.OwnerType == property.OwnerType.FullName).MemberKey;
   var value = Assert.Single(inspector.GetBindings(target, new[] { key }, registry, Dispatcher.CurrentDispatcher));
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
    var value = Assert.Single(inspector.GetBindings(target, new[] { key }, new Registry(), Dispatcher.CurrentDispatcher));
    Assert.Null(value.Path); Assert.Null(value.ElementName); Assert.Null(value.SourceType); Assert.Null(value.ConverterType);
    var targetPolicy = new ObjectInspector(new[] { "text" });
    var error = Assert.Throws<ProtocolException>(() => targetPolicy.GetBindings(target, new[] { key }, new Registry(), Dispatcher.CurrentDispatcher));
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
  [Fact] public void ValidationExceptionMessageRespectsSensitivePaths()
  {
   Sta(() => {
    var target = new TextBox();
    var expression = BindingOperations.SetBinding(target, TextBox.TextProperty, new Binding("Name") { Source = new Source() });
    Validation.MarkInvalid(expression, new ValidationError(new ExceptionValidationRule(), expression, null, new InvalidOperationException("binding failure")));
    Assert.Equal(typeof(InvalidOperationException).FullName + ": binding failure", Assert.Single(Read(target, TextBox.TextProperty).ValidationErrors!));
    expression = BindingOperations.SetBinding(target, TextBox.TextProperty, new Binding("Password") { Source = new Source() });
    Validation.MarkInvalid(expression, new ValidationError(new ExceptionValidationRule(), expression, null, new InvalidOperationException("hidden")));
    Assert.Equal(typeof(InvalidOperationException).FullName, Assert.Single(Read(target, TextBox.TextProperty).ValidationErrors!));
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

  private sealed class Inner { public string Name { get; set; } = "inner-name"; }
  private sealed class Outer { public Inner Child { get; set; } = new Inner(); public string Name { get; set; } = "outer-name"; public string Password { get; set; } = "secret"; }
  private sealed class AccountToken { public string Value = "x"; }
  private sealed class NonEmptyRule : ValidationRule
  {
   public override ValidationResult Validate(object value, CultureInfo culture) => ValidationResult.ValidResult;
  }
  private static string Scalar(ValueDto? value) => ((JsonStringNode)value!.Scalar!).Value;
  private static TextBox Bound(BindingBase binding) { var target = new TextBox(); BindingOperations.SetBinding(target, TextBox.TextProperty, binding); return target; }

  [Fact] public void BindingOptionsAreReadWithoutInvokingConverterOrSource()
  {
   Sta(() => {
    var target = new TextBox(); var source = new Source(); var converter = new Counter(); var parameter = new Inner();
    var binding = new Binding("Name") { Source = source, Converter = converter, ConverterParameter = parameter, ConverterCulture = new CultureInfo("fr-FR"), StringFormat = "{0:N2}", FallbackValue = "fb", TargetNullValue = 7,
     Delay = 250, BindingGroupName = "group", IsAsync = true, NotifyOnSourceUpdated = true, NotifyOnTargetUpdated = true, NotifyOnValidationError = true, ValidatesOnDataErrors = true, ValidatesOnExceptions = true, ValidatesOnNotifyDataErrors = false,
     UpdateSourceExceptionFilter = (expression, exception) => null };
    binding.ValidationRules.Add(new NonEmptyRule());
    BindingOperations.SetBinding(target, TextBox.TextProperty, binding);
    int forward = converter.Forward, back = converter.Back;
    var registry = new Registry(); var info = Read(target, TextBox.TextProperty, new ObjectInspector(), registry);
    Assert.Equal("{0:N2}", info.StringFormat); Assert.Equal("fb", Scalar(info.FallbackValue)); Assert.Equal(ValueKind.Integer, info.TargetNullValue!.Kind); Assert.True(((JsonNumberNode)info.TargetNullValue.Scalar!).TryGetInt64(out long seven)); Assert.Equal(7, seven);
    Assert.Equal(ValueKind.Object, info.ConverterParameter!.Kind); Assert.Same(parameter, registry.Resolve(info.ConverterParameter.Object!));
    Assert.Equal("fr-FR", info.ConverterCulture); Assert.Equal(250, info.Delay); Assert.Equal("group", info.BindingGroupName);
    Assert.True(info.IsAsync); Assert.True(info.NotifyOnSourceUpdated); Assert.True(info.NotifyOnTargetUpdated); Assert.True(info.NotifyOnValidationError);
    Assert.True(info.ValidatesOnDataErrors); Assert.True(info.ValidatesOnExceptions); Assert.False(info.ValidatesOnNotifyDataErrors);
    Assert.Contains(typeof(NonEmptyRule).FullName, info.ValidationRules!); Assert.True(info.HasUpdateSourceExceptionFilter);
    Assert.Equal(forward, converter.Forward); Assert.Equal(back, converter.Back);
   });
  }
  [Fact] public void DefaultBindingOmitsEmptyOptionsAndReportsFlags()
  {
   Sta(() => {
    var info = Read(Bound(new Binding("Name") { Source = new Source() }), TextBox.TextProperty);
    Assert.Null(info.StringFormat); Assert.Null(info.FallbackValue); Assert.Null(info.TargetNullValue); Assert.Null(info.ConverterParameter); Assert.Null(info.Delay); Assert.Null(info.BindingGroupName); Assert.Null(info.XPath); Assert.Null(info.ActiveChildIndex); Assert.Null(info.ConverterCulture);
    Assert.False(info.IsAsync); Assert.False(info.HasUpdateSourceExceptionFilter); Assert.False(info.HasError); Assert.False(info.HasValidationError); Assert.True(info.ValidatesOnNotifyDataErrors);
    Assert.Equal(string.Empty, Read(Bound(new Binding("Name") { Source = new Source(), ConverterCulture = CultureInfo.InvariantCulture }), TextBox.TextProperty).ConverterCulture);
   });
  }
  [Fact] public void XPathIsRead()
  {
   Sta(() => {
    var document = new System.Xml.XmlDocument(); document.LoadXml("<root><item>a</item></root>");
    var info = Read(Bound(new Binding { XPath = "item", Source = document }), TextBox.TextProperty);
    Assert.Equal("item", info.XPath);
   });
  }
  [Fact] public void DataItemAndResolvedSourceAreHandlesUsableInFollowUpReads()
  {
   Sta(() => {
    var outer = new Outer(); var target = Bound(new Binding("Child.Name") { Source = outer });
    var registry = new Registry(); var info = Read(target, TextBox.TextProperty, new ObjectInspector(), registry);
    Assert.Equal(ValueKind.Object, info.DataItem!.Kind); Assert.Equal(ValueKind.Object, info.ResolvedSource!.Kind);
    object dataItem = registry.Resolve(info.DataItem.Object!), resolved = registry.Resolve(info.ResolvedSource.Object!);
    Assert.Same(outer, dataItem); Assert.Same(outer.Child, resolved); Assert.Equal("Name", info.ResolvedSourcePropertyName);
    Assert.Equal("inner-name", Scalar(new Reader(resolved).Read(Property("Name")))); Assert.Equal("outer-name", Scalar(new Reader(dataItem).Read(Property("Name"))));
    Assert.False(info.HasError); Assert.Equal("Active", info.Status);
   });
  }
  [Fact] public void HasErrorFlagsFollowTheExpression()
  {
   Sta(() => {
    var target = new TextBox(); var expression = BindingOperations.SetBinding(target, TextBox.TextProperty, new Binding("Name") { Source = new Source() });
    Validation.MarkInvalid(expression, new ValidationError(new ExceptionValidationRule(), expression, "bad", null));
    var info = Read(target, TextBox.TextProperty); Assert.True(info.HasError); Assert.True(info.HasValidationError);
    Validation.ClearInvalid(expression);
   });
  }
  [Fact] public void MultiBindingReadsConverterParameterAndNestedChildren()
  {
   Sta(() => {
    var outer = new Outer(); var converter = new Counter(); var parameter = new Inner();
    var multi = new MultiBinding { Converter = converter, ConverterParameter = parameter, StringFormat = "{0}-{1}", NotifyOnSourceUpdated = true, ValidatesOnDataErrors = true };
    multi.Bindings.Add(new Binding("Name") { Source = outer, FallbackValue = "child-fb" }); multi.Bindings.Add(new Binding("Child.Name") { Source = outer });
    var target = Bound(multi); int forward = converter.Forward; var registry = new Registry(); var info = Read(target, TextBox.TextProperty, new ObjectInspector(), registry);
    Assert.Equal("multiBinding", info.Kind); Assert.Equal(typeof(Counter).FullName, info.ConverterType); Assert.Same(parameter, registry.Resolve(info.ConverterParameter!.Object!)); Assert.Equal("{0}-{1}", info.StringFormat);
    Assert.True(info.NotifyOnSourceUpdated); Assert.True(info.ValidatesOnDataErrors); Assert.Null(info.IsAsync);
    Assert.Equal(2, info.Children!.Count); Assert.Equal("child-fb", Scalar(info.Children[0].FallbackValue)); Assert.Same(outer, registry.Resolve(info.Children[0].DataItem!.Object!));
    Assert.Same(outer.Child, registry.Resolve(info.Children[1].ResolvedSource!.Object!)); Assert.Equal("Name", info.Children[1].ResolvedSourcePropertyName); Assert.NotEqual("", info.Children[0].Status);
    Assert.Equal(forward, converter.Forward);
   });
  }
  [Fact] public void PriorityBindingReportsActiveChildAndOptions()
  {
   Sta(() => {
    var outer = new Outer(); var priority = new PriorityBinding { FallbackValue = "pfb", StringFormat = "{0}" };
    priority.Bindings.Add(new Binding("Missing") { Source = outer }); priority.Bindings.Add(new Binding("Name") { Source = outer });
    var registry = new Registry(); var info = Read(Bound(priority), TextBox.TextProperty, new ObjectInspector(), registry);
    Assert.Equal("priorityBinding", info.Kind); Assert.Equal(1, info.ActiveChildIndex); Assert.Equal("pfb", Scalar(info.FallbackValue)); Assert.Equal("{0}", info.StringFormat); Assert.Equal(2, info.Children!.Count);
    Assert.Same(outer, registry.Resolve(info.Children[1].DataItem!.Object!));
   });
  }
  [Fact] public void ValueBearingFieldsAreOmittedForSensitiveBindingsAndValues()
  {
   Sta(() => {
    var outer = new Outer();
    var info = Read(Bound(new Binding("Password") { Source = outer, FallbackValue = "fb", TargetNullValue = "tnv", ConverterParameter = new Inner(), StringFormat = "{0}", ConverterCulture = new CultureInfo("fr-FR"), Delay = 5 }), TextBox.TextProperty);
    Assert.Null(info.FallbackValue); Assert.Null(info.TargetNullValue); Assert.Null(info.ConverterParameter); Assert.Null(info.StringFormat); Assert.Null(info.DataItem); Assert.Null(info.ResolvedSource); Assert.Null(info.ResolvedSourcePropertyName); Assert.Null(info.XPath);
    Assert.Equal("fr-FR", info.ConverterCulture); Assert.Equal(5, info.Delay);
    var multi = new MultiBinding { Converter = new Counter(), ConverterParameter = new Inner(), FallbackValue = "multi-fb" }; multi.Bindings.Add(new Binding("Name") { Source = outer }); multi.Bindings.Add(new Binding("Password") { Source = outer });
    info = Read(Bound(multi), TextBox.TextProperty);
    Assert.Null(info.ConverterParameter); Assert.Null(info.FallbackValue); Assert.NotNull(info.Children![0].DataItem); Assert.Null(info.Children[1].DataItem);
    info = Read(Bound(new Binding("Name") { Source = outer, ConverterParameter = new AccountToken(), FallbackValue = new AccountToken(), TargetNullValue = "visible" }), TextBox.TextProperty);
    Assert.Null(info.ConverterParameter); Assert.Null(info.FallbackValue); Assert.Equal("visible", Scalar(info.TargetNullValue)); Assert.NotNull(info.DataItem);
    var additional = new ObjectInspector(new[] { "inner" });
    info = Read(Bound(new Binding("Child.Name") { Source = outer, ConverterParameter = new Inner() }), TextBox.TextProperty, additional, new Registry());
    Assert.Null(info.ConverterParameter); Assert.Null(info.ResolvedSource); Assert.NotNull(info.DataItem);
   });
  }
  [Fact] public void ProtectedObjectsAreNotExposedAsDataItem()
  {
   Sta(() => {
    var password = new PasswordBox();
    var info = Read(Bound(new Binding("Tag") { Source = password, ConverterParameter = password }), TextBox.TextProperty);
    Assert.Null(info.DataItem); Assert.Null(info.ResolvedSource); Assert.Null(info.ConverterParameter);
    Assert.Equal("binding", info.Kind);
   });
  }
 }
}
