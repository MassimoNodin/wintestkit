using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Automation.Peers;
using System.Windows.Controls;
using System.Windows.Data;
using WinTestKit.Inspector.Agent.Inspection.Members;
using WinTestKit.Inspector.Protocol;
using Xunit;
using static WinTestKit.Inspector.Agent.Members.Tests.ValueTestSupport;

namespace WinTestKit.Inspector.Agent.Members.Tests
{
    [Trait("Category", "Unit")]
    public sealed class RedactionIdentityTests
    {
        private class ProtectedControl : Button
        {
            public bool Protected = true;
            public bool ThrowOnPassword;
            public int Calls;
            public string VisibleValue { get { Calls++; return "sensitive-value"; } }
            protected override AutomationPeer OnCreateAutomationPeer() => new ProtectedPeer(this);
        }
        private sealed class ProtectedPeer : ButtonAutomationPeer
        {
            private readonly ProtectedControl owner;
            public ProtectedPeer(ProtectedControl owner) : base(owner) { this.owner = owner; }
            protected override bool IsPasswordCore() => owner.ThrowOnPassword ? throw new InvalidOperationException() : owner.Protected;
        }
        private sealed class Outer
        {
            public ProtectedControl Child { get; } = new ProtectedControl();
        }
        private sealed class NoPeer : FrameworkElement
        {
            public int Calls;
            public string VisibleValue { get { Calls++; return "value"; } }
        }

        [Fact] public void PasswordPeerBlocksDirectNestedAndBindingReadsBeforeValueGetters()
        {
            Sta(() =>
            {
                var outer = new Outer();
                var target = outer.Child;
                BindingOperations.SetBinding(target, ContentControl.ContentProperty, new Binding("VisibleValue") { Source = target });
                int before = target.Calls;
                var reader = new Reader(target);
                Assert.Equal("identity", reader.Read(Property("VisibleValue")).RedactionRule);
                Assert.Equal("identity", new Reader(outer).Read(Property("Child"), Property("VisibleValue")).RedactionRule);
                string key = reader.Inspector.GetMembers(target, new List<Diagnostic>()).Single(row => row.PathSegment?.Kind == "dependency" && row.PathSegment.Name == "Content" && row.PathSegment.OwnerType == typeof(ContentControl).FullName).MemberKey;
                var error = Assert.Throws<ProtocolException>(() => reader.Inspector.GetBindings(target, new[] { key }, reader.Registry, System.Windows.Threading.Dispatcher.CurrentDispatcher));
                Assert.Equal(ErrorCodes.AccessDenied, error.Code);
                Assert.DoesNotContain("VisibleValue", error.Message);
                Assert.Equal(before, target.Calls);
                target.Protected = false;
                Assert.Equal(ValueStatus.Ok, reader.Read(Property("VisibleValue")).Status);
                Assert.Equal(before + 1, target.Calls);
                target.ThrowOnPassword = true;
                Assert.Equal(ValueStatus.Redacted, reader.Read(Property("VisibleValue")).Status);
                Assert.Equal(before + 1, target.Calls);
            });
        }

        private sealed class ShadowName : ProtectedControl
        {
            public new string Name => "hidden";
        }

        private sealed class ShadowVisible : ProtectedControl
        {
            public new bool IsVisible => true;
        }

        [Trait("Category", "Unit")]
        [Fact] public void ProtectedAllowlistRequiresExactDeclarationAndSingleSegment()
        {
            Sta(() =>
            {
                foreach (var target in new FrameworkElement[] { new PasswordBox(), new ProtectedControl() })
                {
                    var reader = new Reader(target);
                    foreach (string name in new[] { "Name", "IsVisible", "IsEnabled", "IsFocused", "IsKeyboardFocused", "IsKeyboardFocusWithin", "IsMouseOver", "IsHitTestVisible", "Visibility", "Opacity", "Width", "Height", "ActualWidth", "ActualHeight" })
                    {
                        Declaration declaration = ReflectionCatalog.Get(target.GetType()).Single(item => item.Name == name && item.Property != null);
                        Assert.True(RedactionPolicy.IsAllowedOnProtected(new[] { Property(name) }, declaration));
                        Assert.Equal(ValueStatus.Ok, reader.Read(Property(name)).Status);
                    }
                    foreach (string name in new[] { "Name", "FullName", "AssemblyName", "AssemblyQualifiedName" })
                        Assert.Equal(ValueStatus.Ok, reader.Read(new PathSegment { Kind = "type", Name = name }).Status);
                    Assert.Equal(ValueStatus.Redacted, reader.Read(new PathSegment { Kind = "type", Name = "BaseTypes" }).Status);
                    Assert.Equal(ValueStatus.Redacted, reader.Read(Property("Tag")).Status);
                    Assert.Equal(ValueStatus.Redacted, reader.Read(Property("Name"), Property("Length")).Status);
                    Assert.Equal(ValueStatus.Redacted, new Reader(target, "Name").Read(Property("Name")).Status);
                    Assert.Equal(ValueStatus.Ok, reader.Read(Dependency(UIElement.IsEnabledProperty)).Status);
                }
                var password = new Reader(new PasswordBox());
                Assert.Equal(ValueStatus.Redacted, password.Read(Property("Password")).Status);
                Assert.Equal(ValueStatus.Redacted, password.Read(Property("SecurePassword")).Status);
                Declaration shadow = ReflectionCatalog.Get(typeof(ShadowName)).Single(item => item.Name == "Name" && item.DeclaringType == typeof(ShadowName));
                Assert.False(RedactionPolicy.IsAllowedOnProtected(new[] { Property("Name") }, shadow));
                Declaration shadowVisible = ReflectionCatalog.Get(typeof(ShadowVisible)).Single(item => item.Name == "IsVisible" && item.DeclaringType == typeof(ShadowVisible));
                Assert.False(RedactionPolicy.IsAllowedOnProtected(new[] { Property("IsVisible") }, shadowVisible));
                Assert.Equal(ValueStatus.Redacted, new Reader(new ShadowVisible()).Read(new PathSegment { Kind = "property", Name = "IsVisible", DeclaringType = typeof(ShadowVisible).FullName }).Status);
                Assert.Equal(ValueStatus.Redacted, new Reader(new ShadowName()).Read(new PathSegment { Kind = "property", Name = "Name", DeclaringType = typeof(ShadowName).FullName }).Status);
            });
        }

        [Fact] public void PeerlessElementsAreNotProtected()
        {
            Sta(() =>
            {
                var target = new NoPeer();
                Assert.False(RedactionPolicy.IsProtectedIdentity(target));
                Assert.Equal(ValueStatus.Ok, new Reader(target).Read(Property("VisibleValue")).Status);
                Assert.Equal(1, target.Calls);
                foreach (DependencyObject panel in new DependencyObject[] { new Grid(), new DockPanel(), new StackPanel(), new Border(), new System.Windows.Documents.Run("x") })
                    Assert.False(RedactionPolicy.IsProtectedIdentity(panel));
                Assert.False(RedactionPolicy.IsProtectedIdentity(new object()));
            });
        }

        [Fact] public void OwnedPeerNotReportingPasswordIsNotProtectedAndFailureIsClosed()
        {
            Sta(() =>
            {
                var target = new ProtectedControl { Protected = false };
                Assert.False(RedactionPolicy.IsProtectedIdentity(target));
                Assert.False(RedactionPolicy.IsProtectedIdentity(new TextBox()));
                target.Protected = true;
                Assert.True(RedactionPolicy.IsProtectedIdentity(target));
                target.ThrowOnPassword = true;
                Assert.True(RedactionPolicy.IsProtectedIdentity(target));
            });
        }

        [Fact] public void PasswordBoxAndItsTemplatePartsAreProtected()
        {
            Sta(() =>
            {
                var box = new PasswordBox();
                Assert.True(RedactionPolicy.IsProtectedIdentity(box));
                var border = new FrameworkElementFactory(typeof(Border));
                var host = new FrameworkElementFactory(typeof(ScrollViewer));
                host.Name = "PART_ContentHost";
                border.AppendChild(host);
                box.Template = new ControlTemplate(typeof(PasswordBox)) { VisualTree = border };
                Assert.True(box.ApplyTemplate());
                var part = (DependencyObject)box.Template.FindName("PART_ContentHost", box);
                Assert.NotNull(part);
                Assert.True(RedactionPolicy.IsProtectedIdentity(part));
                Assert.True(RedactionPolicy.IsProtectedIdentity(System.Windows.Media.VisualTreeHelper.GetParent(part)));
                Assert.False(RedactionPolicy.IsProtectedIdentity(new Grid()));
                var unrelated = new Grid();
                unrelated.Children.Add(new Border());
                Assert.False(RedactionPolicy.IsProtectedIdentity(unrelated));
                Assert.False(RedactionPolicy.IsProtectedIdentity(unrelated.Children[0]));
            });
        }

        [Fact] public void TextBoxAndItsTemplatePartAreNotProtected()
        {
            Sta(() =>
            {
                var box = new TextBox();
                var part = new FrameworkElementFactory(typeof(Border));
                part.Name = "Part";
                box.Template = new ControlTemplate(typeof(TextBox)) { VisualTree = part };
                Assert.True(box.ApplyTemplate());
                Assert.False(RedactionPolicy.IsProtectedIdentity(box));
                var templatePart = (DependencyObject)box.Template.FindName("Part", box);
                Assert.NotNull(templatePart);
                Assert.False(RedactionPolicy.IsProtectedIdentity(templatePart));
            });
        }

        [Fact] public void DeepNestedTemplatesAreCheckedQuicklyAndCorrectly()
        {
            Sta(() =>
            {
                foreach (Control root in new Control[] { new ContentControl(), new PasswordBox() })
                {
                    Control current = root;
                    for (int i = 0; i < 10; i++)
                    {
                        var factory = new FrameworkElementFactory(typeof(ContentControl));
                        factory.Name = "Nested";
                        current.Template = new ControlTemplate(current.GetType()) { VisualTree = factory };
                        Assert.True(current.ApplyTemplate());
                        current = (Control)current.Template.FindName("Nested", current);
                    }
                    bool expected = root is PasswordBox;
                    Assert.Equal(expected, RedactionPolicy.IsProtectedIdentity(current));
                    var samples = new long[9];
                    for (int i = 0; i < samples.Length; i++)
                    {
                        long start = System.Diagnostics.Stopwatch.GetTimestamp();
                        Assert.Equal(expected, RedactionPolicy.IsProtectedIdentity(current));
                        samples[i] = System.Diagnostics.Stopwatch.GetTimestamp() - start;
                    }
                    Array.Sort(samples);
                    Assert.True(samples[samples.Length / 2] * 1000.0 / System.Diagnostics.Stopwatch.Frequency < 5);
                }
            });
        }

        [Fact] public void VisualAncestorPasswordBoxProtectsDescendants()
        {
            Sta(() =>
            {
                var box = new PasswordBox();
                var template = new FrameworkElementFactory(typeof(Grid));
                template.AppendChild(new FrameworkElementFactory(typeof(Border)));
                box.Template = new ControlTemplate(typeof(PasswordBox)) { VisualTree = template };
                box.ApplyTemplate();
                var grid = (DependencyObject)System.Windows.Media.VisualTreeHelper.GetChild(box, 0);
                var child = System.Windows.Media.VisualTreeHelper.GetChild(grid, 0);
                Assert.True(RedactionPolicy.IsProtectedIdentity(grid));
                Assert.True(RedactionPolicy.IsProtectedIdentity(child));
                var outside = new Grid();
                outside.Children.Add(new Border());
                Assert.False(RedactionPolicy.IsProtectedIdentity(outside.Children[0]));
            });
        }    }
}
