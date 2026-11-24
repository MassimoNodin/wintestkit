using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Markup;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Members.Tests
{
    [Trait("Category", "Unit")]
    public sealed class StylingTests
    {
        private const string Header = "xmlns=\"http://schemas.microsoft.com/winfx/2006/xaml/presentation\" xmlns:x=\"http://schemas.microsoft.com/winfx/2006/xaml\" xmlns:s=\"clr-namespace:System;assembly=mscorlib\"";

        private static T Parse<T>(string xaml) => (T)XamlReader.Load(new MemoryStream(Encoding.UTF8.GetBytes(xaml)));

        private static StylingResult Read(object target, params string[] redact) => Read(target, null, redact);

        private static StylingResult Read(object target, ResourceDictionary? application, params string[] redact)
        {
            var registry = new ValueTestSupport.Registry();
            var result = new StylingReader(new RedactionPolicy(redact), registry, Dispatcher.CurrentDispatcher, () => application).Read(target);
            byte[] json = StrictJson.Serialize(result.ToJson());
            var copy = StylingResult.FromJson(StrictJson.Parse(json, 0, json.Length));
            Assert.Equal(json, StrictJson.Serialize(copy.ToJson()));
            return copy;
        }

        private const string StyleDictionary = "<ResourceDictionary " + Header + ">" +
            "<SolidColorBrush x:Key=\"Accent\" Color=\"Red\"/>" +
            "<Style x:Key=\"Base\" TargetType=\"Button\"><Setter Property=\"Padding\" Value=\"4\"/><Setter Property=\"Foreground\" Value=\"{DynamicResource Accent}\"/></Style>" +
            "<Style x:Key=\"Fancy\" TargetType=\"Button\" BasedOn=\"{StaticResource Base}\">" +
            "<Setter Property=\"Background\" Value=\"{Binding Path=Name, RelativeSource={RelativeSource Self}}\"/>" +
            "<Setter Property=\"Tag\" Value=\"{Binding Path=Missing, ElementName=other}\"/>" +
            "<Setter Property=\"Opacity\" Value=\"0.75\"/>" +
            "<Style.Triggers>" +
            "<Trigger Property=\"IsEnabled\" Value=\"False\"><Setter Property=\"Opacity\" Value=\"0.5\"/><Setter Property=\"Cursor\" Value=\"No\"/></Trigger>" +
            "<Trigger Property=\"IsDefault\" Value=\"True\"><Setter Property=\"FontWeight\" Value=\"Bold\"/></Trigger>" +
            "<DataTrigger Binding=\"{Binding Path=Ready}\" Value=\"True\"><Setter Property=\"Content\" Value=\"Ready\"/></DataTrigger>" +
            "<MultiTrigger><MultiTrigger.Conditions><Condition Property=\"IsEnabled\" Value=\"True\"/><Condition Property=\"IsDefault\" Value=\"False\"/></MultiTrigger.Conditions><Setter Property=\"FontSize\" Value=\"20\"/></MultiTrigger>" +
            "<EventTrigger RoutedEvent=\"Button.Click\"><BeginStoryboard><Storyboard/></BeginStoryboard></EventTrigger>" +
            "</Style.Triggers></Style></ResourceDictionary>";

        [Fact]
        public void StyleDescribesSettersBasedOnAndTriggers()
        {
            ValueTestSupport.Sta(() =>
            {
                var resources = Parse<ResourceDictionary>(StyleDictionary);
                var button = new Button { Resources = resources, Style = (Style)resources["Fancy"], IsEnabled = false };
                var result = Read(button);
                Assert.True(result.Applicable);
                var style = result.Style!;
                Assert.Equal("local", style.Source);
                Assert.Equal("Fancy", style.Key);
                Assert.Equal("System.Windows.Controls.Button", style.TargetType);
                Assert.Equal(new[] { "Background", "Tag", "Opacity" }, style.Setters.Select(item => item.Property));
                var background = style.Setters[0];
                Assert.Equal("binding", background.Kind);
                Assert.Contains("RelativeSource=Self", background.Expression);
                Assert.Null(background.Value);
                Assert.Equal("Path=Missing, ElementName=other", style.Setters[1].Expression);
                Assert.Equal("value", style.Setters[2].Kind);
                Assert.Equal("0.75", Assert.IsType<JsonNumberNode>(style.Setters[2].Value!.Scalar).RawText);
                Assert.Single(style.BasedOn);
                Assert.Equal("Base", style.BasedOn[0].Key);
                Assert.Equal("System.Windows.Controls.Button", style.BasedOn[0].TargetType);
                var foreground = style.BasedOn[0].Setters.Single(item => item.Property == "Foreground");
                Assert.Equal("dynamicResource", foreground.Kind);
                Assert.Equal("Accent", foreground.Expression);
                Assert.Null(foreground.Value);
                Assert.Equal("value", style.BasedOn[0].Setters.Single(item => item.Property == "Padding").Kind);
                Assert.Equal(5, style.TriggerCount);
                Assert.Equal(new[] { "trigger", "trigger", "dataTrigger", "multiTrigger", "eventTrigger" }, style.Triggers.Select(item => item.Kind));
                Assert.Equal("active", style.Triggers[0].Active);
                Assert.Equal("System.Windows.UIElement.IsEnabled", style.Triggers[0].Conditions.Single().Property);
                Assert.Equal(2, style.Triggers[0].SetterCount);
                Assert.Equal("inactive", style.Triggers[1].Active);
                Assert.Equal("unknown", style.Triggers[2].Active);
                Assert.Equal("Path=Ready", style.Triggers[2].Conditions.Single().Binding);
                Assert.Equal("inactive", style.Triggers[3].Active);
                Assert.Equal(new[] { "inactive", "active" }, style.Triggers[3].Conditions.Select(item => item.Active));
                Assert.Equal("System.Windows.Controls.Primitives.ButtonBase.Click", style.Triggers[4].RoutedEvent);
                Assert.Equal("unknown", style.Triggers[4].Active);
            });
        }

        [Fact]
        public void PropertyTriggerActivityFollowsTheCurrentValue()
        {
            ValueTestSupport.Sta(() =>
            {
                var resources = Parse<ResourceDictionary>(StyleDictionary);
                var button = new Button { Resources = resources, Style = (Style)resources["Fancy"], IsEnabled = true };
                Assert.Equal("inactive", Read(button).Style!.Triggers[0].Active);
                Assert.Equal("active", Read(button).Style!.Triggers[3].Active);
                button.IsEnabled = false;
                Assert.Equal("active", Read(button).Style!.Triggers[0].Active);
                Assert.Equal("inactive", Read(button).Style!.Triggers[3].Active);
            });
        }

        [Fact]
        public void ThemeDefaultStyleIsFoundByTypeAndAnImplicitStyleIsNamedByItsType()
        {
            ValueTestSupport.Sta(() =>
            {
                var plain = Read(new Button()).Style!;
                Assert.Equal("typeLookup", plain.Source);
                Assert.Equal("System.Windows.Controls.Button", plain.Key);
                Assert.Equal("System.Windows.Controls.Button", plain.TargetType);

                var implicitStyle = new Style(typeof(TextBlock));
                implicitStyle.Setters.Add(new Setter(TextBlock.FontSizeProperty, 30.0));
                var panel = new StackPanel();
                panel.Resources.Add(typeof(TextBlock), implicitStyle);
                var block = new TextBlock();
                panel.Children.Add(block);
                block.BeginInit();
                block.EndInit();
                var style = Read(block).Style!;
                Assert.Equal("implicit", style.Source);
                Assert.Equal("System.Windows.Controls.TextBlock", style.Key);
                Assert.Equal("FontSize", Assert.Single(style.Setters).Property);
                Assert.Equal("none", Read(new Border()).Style!.Source);
            });
        }

        [Fact]
        public void ElementsThatAreNotFrameworkElementsAreEmpty()
        {
            ValueTestSupport.Sta(() =>
            {
                foreach (object target in new object[] { "text", 5, new object(), new System.Windows.Media.DrawingVisual(), new Dictionary<string, int>() })
                {
                    var result = Read(target);
                    Assert.False(result.Applicable);
                    Assert.Null(result.Style);
                    Assert.Null(result.Templates);
                    Assert.Null(result.Resources);
                    Assert.Null(result.Application);
                }
                Assert.True(Read(new System.Windows.Documents.Run("x")).Applicable);
            });
        }

        [Fact]
        public void SetterValuesOfRedactedPropertiesAreRedacted()
        {
            ValueTestSupport.Sta(() =>
            {
                var style = new Style(typeof(TextBox));
                style.Setters.Add(new Setter(TextBox.TagProperty, "hunter2"));
                style.Setters.Add(new Setter(TextBox.TextProperty, "visible"));
                var trigger = new Trigger { Property = TextBox.TagProperty, Value = "hunter2" };
                trigger.Setters.Add(new Setter(TextBox.TextProperty, "x"));
                style.Triggers.Add(trigger);
                var result = Read(new TextBox { Style = style }, "tag").Style!;
                Assert.Equal(ValueStatus.Redacted, result.Setters[0].Value!.Status);
                Assert.Null(result.Setters[0].Expression);
                Assert.Equal("ok", result.Setters[1].Value!.Status);
                Assert.Equal(ValueStatus.Redacted, result.Triggers[0].Conditions[0].Value.Status);
                Assert.DoesNotContain("hunter2", Encoding.UTF8.GetString(StrictJson.Serialize(Read(new TextBox { Style = style }, "tag").ToJson())));
            });
        }

        private const string ButtonTemplate = "<ControlTemplate " + Header + " TargetType=\"Button\">" +
            "<Border x:Name=\"PART_Border\" Background=\"White\"><ContentPresenter x:Name=\"PART_Content\"/></Border>" +
            "<ControlTemplate.Triggers>" +
            "<Trigger Property=\"IsEnabled\" Value=\"False\"><Setter TargetName=\"PART_Border\" Property=\"Opacity\" Value=\"0.5\"/></Trigger>" +
            "<Trigger SourceName=\"PART_Border\" Property=\"Opacity\" Value=\"1\"><Setter Property=\"FontSize\" Value=\"20\"/></Trigger>" +
            "</ControlTemplate.Triggers></ControlTemplate>";

        private static ControlTemplate ParseButtonTemplate()
        {
            var template = Parse<ControlTemplate>(ButtonTemplate);
            // The parser rejects a SourceName that names nothing, so the dangling one is added in code.
            template.Triggers.Add(new Trigger { SourceName = "Missing", Property = UIElement.OpacityProperty, Value = 1.0 });
            return template;
        }

        [Fact]
        public void ControlTemplateListsTriggersAndTheNamedPartsItBuilt()
        {
            ValueTestSupport.Sta(() =>
            {
                var button = new Button { Template = ParseButtonTemplate(), Content = "ok" };
                button.ApplyTemplate();
                var templates = Read(button).Templates!;
                var template = templates.ControlTemplate!;
                Assert.Equal("controlTemplate", template.Kind);
                Assert.Equal("System.Windows.Controls.Button", template.TargetType);
                Assert.Equal("System.Windows.Controls.Border", template.RootType);
                Assert.Equal(new[] { "PART_Border", "PART_Content" }, template.Parts.Select(item => item.Name).OrderBy(name => name));
                Assert.Equal("System.Windows.Controls.Border", template.Parts.Single(item => item.Name == "PART_Border").Type);
                Assert.Equal("object", template.Parts[0].Element.Kind);
                Assert.Equal(3, template.TriggerCount);
                Assert.Equal(new[] { "inactive", "active", "unknown" }, template.Triggers.Select(item => item.Active));
                Assert.Equal("PART_Border", template.Triggers[1].Conditions[0].SourceName);
                Assert.Null(templates.ContentTemplate);
                Assert.Null(templates.ItemTemplate);
                Assert.Null(templates.TemplatedParent);
                button.IsEnabled = false;
                Assert.Equal("active", Read(button).Templates!.ControlTemplate!.Triggers[0].Active);
            });
        }

        [Fact]
        public void PartsOfACodeBuiltTemplateAreNamedByTheirFactories()
        {
            ValueTestSupport.Sta(() =>
            {
                var frame = new FrameworkElementFactory(typeof(Grid), "PART_Frame");
                frame.AppendChild(new FrameworkElementFactory(typeof(ContentPresenter), "PART_Content"));
                frame.AppendChild(new FrameworkElementFactory(typeof(TextBlock)));
                var button = new Button { Template = new ControlTemplate(typeof(Button)) { VisualTree = frame } };
                button.ApplyTemplate();
                var template = Read(button).Templates!.ControlTemplate!;
                Assert.Equal(new[] { "PART_Content", "PART_Frame" }, template.Parts.Select(item => item.Name).OrderBy(name => name));
                Assert.Equal("System.Windows.Controls.Grid", template.RootType);
                Assert.False(template.PartsTruncated);
            });
        }

        [Fact]
        public void TemplatedParentIsTheControlWhoseTemplateBuiltTheElement()
        {
            ValueTestSupport.Sta(() =>
            {
                var button = new Button { Template = ParseButtonTemplate() };
                button.ApplyTemplate();
                var border = (Border)button.Template.FindName("PART_Border", button);
                var registry = new ValueTestSupport.Registry();
                var result = new StylingReader(new RedactionPolicy(new string[0]), registry, Dispatcher.CurrentDispatcher, () => null).Read(border);
                var parent = result.Templates!.TemplatedParent!;
                Assert.Equal("object", parent.Kind);
                Assert.Same(button, registry.Resolve(parent.Object!));
                Assert.Null(result.Templates.ControlTemplate);
            });
        }

        [Fact]
        public void ContentAndItemTemplatesAndTheItemContainerStyleAreListed()
        {
            ValueTestSupport.Sta(() =>
            {
                var dataTemplate = Parse<DataTemplate>("<DataTemplate " + Header + " DataType=\"{x:Type s:String}\"><TextBlock Text=\"{Binding}\"/></DataTemplate>");
                var content = Read(new ContentControl { ContentTemplate = dataTemplate }).Templates!.ContentTemplate!;
                Assert.Equal("dataTemplate", content.Kind);
                Assert.Equal("System.String", content.DataType);

                var factory = new FrameworkElementFactory(typeof(WrapPanel));
                var container = new Style(typeof(ListBoxItem));
                container.Setters.Add(new Setter(Control.PaddingProperty, new Thickness(3)));
                var list = new ListBox { ItemTemplate = dataTemplate, ItemContainerStyle = container, ItemsPanel = new ItemsPanelTemplate(factory) };
                var templates = Read(list).Templates!;
                Assert.Equal("dataTemplate", templates.ItemTemplate!.Kind);
                Assert.Equal("itemsPanelTemplate", templates.ItemsPanel!.Kind);
                Assert.Equal("System.Windows.Controls.WrapPanel", templates.ItemsPanel.RootType);
                Assert.Equal("System.Windows.Controls.ListBoxItem", templates.ItemContainerStyle!.TargetType);
                Assert.Equal("Padding", Assert.Single(templates.ItemContainerStyle.Setters).Property);
                Assert.Equal("local", templates.ItemContainerStyle.Source);

                var applied = new ListBox { ItemsPanel = Parse<ItemsPanelTemplate>("<ItemsPanelTemplate " + Header + "><StackPanel/></ItemsPanelTemplate>") };
                applied.ApplyTemplate();
                var presenter = FindDescendant<ItemsPresenter>(applied);
                presenter?.ApplyTemplate();
                if (presenter != null && FindDescendant<Panel>(applied)?.IsItemsHost == true)
                    Assert.Equal("System.Windows.Controls.StackPanel", Read(applied).Templates!.ItemsPanel!.RootType);
            });
        }

        private static T? FindDescendant<T>(DependencyObject root) where T : DependencyObject
        {
            int count = System.Windows.Media.VisualTreeHelper.GetChildrenCount(root);
            for (int index = 0; index < count; index++)
            {
                var child = System.Windows.Media.VisualTreeHelper.GetChild(root, index);
                if (child is T match) return match;
                var nested = FindDescendant<T>(child);
                if (nested != null) return nested;
            }
            return null;
        }

        [Fact]
        public void LocalResourcesDescribeEveryKeyKindAndTheirMergedDictionaries()
        {
            ValueTestSupport.Sta(() =>
            {
                string path = Path.Combine(Path.GetTempPath(), "wtk-styling-" + Guid.NewGuid().ToString("N") + ".xaml");
                File.WriteAllText(path, "<ResourceDictionary " + Header + "><s:String x:Key=\"FromFile\">file</s:String></ResourceDictionary>");
                try
                {
                    var resources = Parse<ResourceDictionary>("<ResourceDictionary " + Header + "><s:String x:Key=\"Title\">Hello</s:String><SolidColorBrush x:Key=\"Accent\" Color=\"Red\"/><Style TargetType=\"Button\"/><DataTemplate DataType=\"{x:Type s:Int32}\"><TextBlock/></DataTemplate></ResourceDictionary>");
                    resources.Add(new ComponentResourceKey(typeof(StylingTests), "Shared"), 5);
                    resources.Add(42, "number key");
                    resources.MergedDictionaries.Add(new ResourceDictionary { Source = new Uri(path, UriKind.Absolute) });
                    resources.MergedDictionaries.Add(new ResourceDictionary());
                    var panel = new StackPanel { Resources = resources };
                    var result = Read(panel);
                    var local = result.Resources!;
                    Assert.Equal(resources.Count, local.Count);
                    Assert.False(local.Truncated);
                    var byKey = local.Entries.ToDictionary(entry => entry.Key);
                    Assert.Equal("string", byKey["Title"].KeyKind);
                    Assert.Equal(resources.Keys.Cast<object>().ToList().IndexOf("Title"), byKey["Title"].Index);
                    Assert.Equal("type", byKey["System.Windows.Controls.Button"].KeyKind);
                    Assert.Equal("componentResourceKey", byKey["ComponentResourceKey(" + typeof(StylingTests).FullName + ", Shared)"].KeyKind);
                    Assert.Equal("other", byKey["DataTemplateKey(System.Int32)"].KeyKind);
                    Assert.Equal("other", byKey["System.Int32: 42"].KeyKind);
                    Assert.Equal(2, local.MergedDictionaries.Count);
                    Assert.Equal(new Uri(path, UriKind.Absolute).OriginalString, local.MergedDictionaries[0].Source);
                    Assert.Equal(1, local.MergedDictionaries[0].Count);
                    Assert.Null(local.MergedDictionaries[1].Source);
                    Assert.Null(result.Application);
                }
                finally { File.Delete(path); }
            });
        }

        [Fact]
        public void ElementsWithoutResourcesGetNoDictionaryCreatedByReading()
        {
            ValueTestSupport.Sta(() =>
            {
                var block = new TextBlock();
                var result = Read(block);
                Assert.Equal(0, result.Resources!.Count);
                Assert.Empty(result.Resources.Entries);
                var has = typeof(FrameworkElement).GetProperty("HasResources", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Public);
                if (has != null) Assert.False((bool)has.GetValue(block)!);
            });
        }

        [Fact]
        public void ResourceListsAreCappedAndApplicationResourcesAreSummarized()
        {
            ValueTestSupport.Sta(() =>
            {
                var many = new ResourceDictionary();
                for (int index = 0; index < StylingLimits.MaxResources + 50; index++) many.Add("key" + index, index);
                for (int index = 0; index < StylingLimits.MaxResources + 1; index++) many.MergedDictionaries.Add(new ResourceDictionary());
                var result = Read(new StackPanel { Resources = many });
                Assert.Equal(StylingLimits.MaxResources + 50, result.Resources!.Count);
                Assert.Equal(StylingLimits.MaxResources, result.Resources.Entries.Count);
                Assert.True(result.Resources.Truncated);
                Assert.Equal(StylingLimits.MaxResources, result.Resources.MergedDictionaries.Count);
                Assert.True(result.Resources.MergedTruncated);

                var application = new ResourceDictionary();
                for (int index = 0; index < StylingLimits.MaxApplicationResources + 7; index++) application.Add("app" + index, "v" + index);
                var summary = Read(new StackPanel(), application).Application!;
                Assert.Equal(StylingLimits.MaxApplicationResources + 7, summary.Count);
                Assert.Equal(StylingLimits.MaxApplicationResources, summary.Entries.Count);
                Assert.True(summary.Truncated);
            });
        }

        [Fact]
        public void ResourceValuesUnderRedactedKeysAreRedactedWhenRead()
        {
            ValueTestSupport.Sta(() =>
            {
                var resources = new ResourceDictionary { { "ApiToken", "hunter2" }, { "Title", "visible" } };
                var panel = new StackPanel { Resources = resources };
                var json = Encoding.UTF8.GetString(StrictJson.Serialize(Read(panel).ToJson()));
                Assert.DoesNotContain("hunter2", json);
                Assert.DoesNotContain("visible", json);
                var reader = new StylingReader(new RedactionPolicy(new string[0]), new ValueTestSupport.Registry(), Dispatcher.CurrentDispatcher);
                var secret = reader.ReadResource(panel, "local", "ApiToken", "string", null);
                Assert.True(secret.Found);
                Assert.Equal(ValueStatus.Redacted, secret.Value!.Status);
                Assert.DoesNotContain("hunter2", Encoding.UTF8.GetString(StrictJson.Serialize(secret.ToJson())));
                Assert.Equal("visible", Assert.IsType<JsonStringNode>(reader.ReadResource(panel, "local", "Title", "string", null).Value!.Scalar).Value);
            });
        }

        [Fact]
        public void SettersTriggersAndBasedOnAreCapped()
        {
            ValueTestSupport.Sta(() =>
            {
                Style? current = null;
                for (int level = 0; level < StylingLimits.MaxBasedOn + 3; level++)
                {
                    var style = new Style(typeof(Button), current);
                    for (int index = 0; index < StylingLimits.MaxEntries + 5; index++) style.Setters.Add(new Setter(Button.TagProperty, index));
                    for (int index = 0; index < StylingLimits.MaxEntries + 2; index++) style.Triggers.Add(new Trigger { Property = Button.IsDefaultProperty, Value = true });
                    current = style;
                }
                var result = Read(new Button { Style = current }).Style!;
                Assert.Equal(StylingLimits.MaxBasedOn, result.BasedOn.Count);
                Assert.True(result.BasedOnTruncated);
                Assert.Equal(StylingLimits.MaxEntries, result.Setters.Count);
                Assert.Equal(StylingLimits.MaxEntries + 5, result.SetterCount);
                Assert.True(result.SettersTruncated);
                Assert.Equal(StylingLimits.MaxEntries, result.Triggers.Count);
                Assert.Equal(StylingLimits.MaxEntries + 2, result.TriggerCount);
                Assert.True(result.TriggersTruncated);
                Assert.All(result.BasedOn, level => Assert.True(level.SettersTruncated));
                var chain = Read(new Button { Style = new Style(typeof(Button), new Style(typeof(Button))) }).Style!;
                Assert.Single(chain.BasedOn);
                Assert.False(chain.BasedOnTruncated);
            });
        }
    }
}
