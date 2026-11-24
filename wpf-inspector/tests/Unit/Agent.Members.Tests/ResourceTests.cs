using System;
using System.Collections;
using System.Linq;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;
using Xunit;

namespace WinTestKit.Inspector.Agent.Members.Tests
{
    /// <summary>Resources are listed by key and created only when one is asked for: a dictionary loaded from compiled XAML keeps its values deferred.</summary>
    [Trait("Category", "Unit")]
    public sealed class ResourceTests
    {
        private static ResourceDictionary LoadDeferred() =>
            (ResourceDictionary)Application.LoadComponent(new Uri("/" + typeof(ResourceTests).Assembly.GetName().Name + ";component/Resources/DeferredResources.xaml", UriKind.Relative));

        private static StylingReader Reader(ResourceDictionary? application = null, params string[] redact) =>
            new StylingReader(new RedactionPolicy(redact), new ValueTestSupport.Registry(), Dispatcher.CurrentDispatcher, () => application);

        private static string RawTypeOf(ResourceDictionary dictionary, string key)
        {
            var raw = (IDictionary)typeof(ResourceDictionary).GetField("_baseDictionary", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(dictionary)!;
            return raw[key]!.GetType().Name;
        }

        [Fact]
        public void ListingNamesKeysWithoutCreatingDeferredResources()
        {
            ValueTestSupport.Sta(() =>
            {
                var dictionary = LoadDeferred();
                Assert.Equal("KeyRecord", RawTypeOf(dictionary, "Probe"));
                int before = DeferredProbe.Created;
                var panel = new StackPanel { Resources = dictionary };
                var result = Reader(LoadDeferred()).Read(panel);
                Assert.Equal(before, DeferredProbe.Created);
                var local = result.Resources!;
                Assert.Equal(3, local.Count);
                Assert.Equal(new[] { "DeferredStyle", "OtherStyle", "Probe" }, local.Entries.Select(entry => entry.Key).OrderBy(key => key, StringComparer.Ordinal));
                Assert.Equal(new[] { 0, 1, 2 }, local.Entries.Select(entry => entry.Index).OrderBy(index => index));
                Assert.All(local.Entries, entry => Assert.Equal("string", entry.KeyKind));
                // The application's dictionary is listed the same way, and nothing in it was created either.
                Assert.Equal(3, result.Application!.Entries.Count);
                Assert.Equal(before, DeferredProbe.Created);
                Assert.Equal("KeyRecord", RawTypeOf(dictionary, "Probe"));
                Assert.Equal("KeyRecord", RawTypeOf(dictionary, "OtherStyle"));
                // The listing carries no value to serialize.
                Assert.DoesNotContain("label", System.Text.Encoding.UTF8.GetString(StrictJson.Serialize(result.ToJson())), StringComparison.OrdinalIgnoreCase);
            });
        }

        [Fact]
        public void ReadingOneResourceCreatesOnlyThatResource()
        {
            ValueTestSupport.Sta(() =>
            {
                var dictionary = LoadDeferred();
                var panel = new StackPanel { Resources = dictionary };
                var reader = Reader();
                var entry = reader.Read(panel).Resources!.Entries.Single(item => item.Key == "Probe");
                int before = DeferredProbe.Created;
                var result = reader.ReadResource(panel, "local", entry.Key, entry.KeyKind, entry.Index);
                Assert.True(result.Found);
                Assert.Equal(before + 1, DeferredProbe.Created);
                Assert.Equal(typeof(DeferredProbe).FullName, result.ValueType);
                Assert.Equal("object", result.Value!.Kind);
                Assert.NotNull(result.Value.Object);
                Assert.Equal("DeferredProbe", RawTypeOf(dictionary, "Probe"));
                Assert.Equal("KeyRecord", RawTypeOf(dictionary, "OtherStyle"));
                // The same object comes back: it is the dictionary's own.
                Assert.Same(dictionary["Probe"], dictionary["Probe"]);
                Assert.Equal(before + 1, DeferredProbe.Created);
                byte[] json = StrictJson.Serialize(result.ToJson());
                Assert.Equal(json, StrictJson.Serialize(ResourceResult.FromJson(StrictJson.Parse(json, 0, json.Length)).ToJson()));
            });
        }

        [Fact]
        public void TheKeyOfAnAppliedStyleIsNamedWithoutCreatingTheOthers()
        {
            ValueTestSupport.Sta(() =>
            {
                var dictionary = LoadDeferred();
                int before = DeferredProbe.Created;
                var button = new Button { Resources = dictionary };
                button.Style = (Style)dictionary["DeferredStyle"];
                var style = Reader().Read(button).Style!;
                Assert.Equal("local", style.Source);
                Assert.Equal("DeferredStyle", style.Key);
                Assert.Equal(before, DeferredProbe.Created);
                Assert.Equal("KeyRecord", RawTypeOf(dictionary, "OtherStyle"));
                Assert.Equal("KeyRecord", RawTypeOf(dictionary, "Probe"));
            });
        }

        [Fact]
        public void ApplicationResourcesAreReadOnDemandToo()
        {
            ValueTestSupport.Sta(() =>
            {
                var application = LoadDeferred();
                var panel = new StackPanel();
                var reader = Reader(application);
                var listing = reader.Read(panel);
                var entry = listing.Application!.Entries.Single(item => item.Key == "OtherStyle");
                Assert.Equal("KeyRecord", RawTypeOf(application, "OtherStyle"));
                var style = reader.ReadResource(panel, "application", entry.Key, entry.KeyKind, entry.Index);
                Assert.True(style.Found);
                Assert.Equal("System.Windows.Style", style.ValueType);
                Assert.Equal("Style", RawTypeOf(application, "OtherStyle"));
                // The element's own dictionary is not the application's.
                Assert.False(reader.ReadResource(panel, "local", entry.Key, entry.KeyKind, entry.Index).Found);
                Assert.False(Reader(null).ReadResource(panel, "application", entry.Key, entry.KeyKind, entry.Index).Found);
            });
        }

        [Fact]
        public void TheKeyIsFoundByItsTextAndKindWhenThePositionMovedOrIsMissing()
        {
            ValueTestSupport.Sta(() =>
            {
                var resources = new ResourceDictionary { { "A", 1 }, { "B", 2 }, { typeof(Button), new Style(typeof(Button)) }, { 7, "seven" } };
                var panel = new StackPanel { Resources = resources };
                var reader = Reader();
                var entries = reader.Read(panel).Resources!.Entries;
                var b = entries.Single(item => item.Key == "B");
                Assert.Equal("2", Assert.IsType<JsonNumberNode>(reader.ReadResource(panel, "local", "B", "string", b.Index).Value!.Scalar).RawText);
                Assert.Equal("2", Assert.IsType<JsonNumberNode>(reader.ReadResource(panel, "local", "B", "string", 99).Value!.Scalar).RawText);
                Assert.True(reader.ReadResource(panel, "local", "B", "string", null).Found);
                var type = entries.Single(item => item.KeyKind == "type");
                Assert.Equal("System.Windows.Style", reader.ReadResource(panel, "local", type.Key, "type", type.Index).ValueType);
                Assert.False(reader.ReadResource(panel, "local", type.Key, "string", type.Index).Found);
                var other = entries.Single(item => item.KeyKind == "other");
                Assert.Equal("System.String", reader.ReadResource(panel, "local", other.Key, "other", other.Index).ValueType);
                var missing = reader.ReadResource(panel, "local", "Nope", "string", 0);
                Assert.False(missing.Found);
                Assert.Null(missing.Value);
                Assert.Equal("{\"found\":false}", System.Text.Encoding.UTF8.GetString(StrictJson.Serialize(missing.ToJson())));
            });
        }

        [Fact]
        public void ElementsWithoutResourcesAndPlainObjectsHaveNothingToRead()
        {
            ValueTestSupport.Sta(() =>
            {
                var panel = new StackPanel();
                Assert.False(Reader().ReadResource(panel, "local", "Any", "string", 0).Found);
                var has = typeof(FrameworkElement).GetProperty("HasResources", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public)!;
                Assert.False((bool)has.GetValue(panel)!);
                Assert.False(Reader().ReadResource("text", "local", "Any", "string", 0).Found);
            });
        }

        [Fact]
        public void PasswordFieldsAndRedactedKeysNeverGiveUpAValue()
        {
            ValueTestSupport.Sta(() =>
            {
                var box = new PasswordBox();
                box.Resources.Add("Title", "visible");
                Assert.False(Reader().ReadResource(box, "local", "Title", "string", 0).Found);
                var panel = new StackPanel { Resources = new ResourceDictionary { { "AdminSecret", new DeferredProbe { Label = "hunter2" } }, { "Title", "visible" } } };
                int before = DeferredProbe.Created;
                var secret = Reader(null, "secret").ReadResource(panel, "local", "AdminSecret", "string", 0);
                Assert.True(secret.Found);
                Assert.Equal(ValueStatus.Redacted, secret.Value!.Status);
                Assert.Equal("", secret.ValueType);
                Assert.DoesNotContain("hunter2", System.Text.Encoding.UTF8.GetString(StrictJson.Serialize(secret.ToJson())));
                Assert.Equal(before, DeferredProbe.Created);
            });
        }
    }
}
