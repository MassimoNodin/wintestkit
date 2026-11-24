using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using WinTestKit.Inspector.Agent.Inspection.Members;
using Xunit;

namespace WinTestKit.Inspector.Agent.Members.Tests
{
    public static class CustomAttached
    {
        public static readonly DependencyProperty FlagProperty = DependencyProperty.RegisterAttached("Flag", typeof(string), typeof(CustomAttached), new PropertyMetadata("default"));
        public static string GetFlag(DependencyObject target) => (string)target.GetValue(FlagProperty);
        public static void SetFlag(DependencyObject target, string value) => target.SetValue(FlagProperty, value);
    }

    [Trait("Category", "Unit")]
    public sealed class AttachedCatalogTests
    {
        private sealed class BrokenAssembly : Assembly
        {
            public override Type[] GetTypes() => throw new ReflectionTypeLoadException(new[] { typeof(CustomAttached), null! }, new Exception[] { new TypeLoadException() });
        }

        [Fact]
        public void StyledAndLocalAttachedPropertiesAreDiscoveredOnce()
        {
            Exception? failure = null;
            var thread = new Thread(() =>
            {
                try
                {
                    var target = new Button();
                    var style = new Style(typeof(Button));
                    style.Setters.Add(new Setter(Grid.RowProperty, 3));
                    style.Setters.Add(new Setter(AutomationProperties.NameProperty, "styled"));
                    style.Setters.Add(new Setter(CustomAttached.FlagProperty, "styled"));
                    target.Style = style;
                    var inspector = new ObjectInspector();
                    var diagnostics = new List<WinTestKit.Inspector.Protocol.Diagnostic>();
                    var rows = inspector.GetMembers(target, diagnostics);
                    foreach (var property in new[] { Grid.RowProperty, AutomationProperties.NameProperty, CustomAttached.FlagProperty })
                        Assert.True(rows.Count(row => row.Category == "attachedProperty" && row.Name == property.Name && row.DeclaringType == property.OwnerType.FullName) == 1, property.OwnerType.FullName + "." + property.Name + " rows: " + string.Join(",", rows.Where(r => r.Name == property.Name).Select(r => r.Category + ":" + r.DeclaringType)));
                    Assert.DoesNotContain(rows, row => row.Category == "attachedProperty" && row.Name == "Column" && row.DeclaringType == typeof(Grid).FullName);
                    target.SetValue(Grid.RowProperty, 4);
                    Assert.Single(inspector.GetMembers(target, diagnostics), row => row.Category == "attachedProperty" && row.Name == "Row" && row.DeclaringType == typeof(Grid).FullName);
                }
                catch (Exception ex) { failure = ex; }
            });
            thread.SetApartmentState(ApartmentState.STA);
            thread.Start(); thread.Join();
            if (failure != null) throw failure;
        }

        [Fact]
        public void TypeLoadFailureAndScanLimitAreReported()
        {
            var failures = new List<Exception>();
            DependencyCatalog.ScanAssembly(new BrokenAssembly(), failures.Add, 10, 2000);
            Assert.Contains(failures, error => error is ReflectionTypeLoadException);
            failures.Clear();
            DependencyCatalog.ScanAssembly(typeof(CustomAttached).Assembly, failures.Add, 0, 2000);
            Assert.Contains(failures, error => error is TimeoutException);
        }
    }
}
