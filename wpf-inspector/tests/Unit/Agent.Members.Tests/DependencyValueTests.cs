using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Automation.Peers;
using System.Windows.Controls;
using System.Windows.Media.Animation;
using WinTestKit.Inspector.Protocol;
using Xunit;
using static WinTestKit.Inspector.Agent.Members.Tests.ValueTestSupport;

namespace WinTestKit.Inspector.Agent.Members.Tests
{
    [Trait("Category", "Unit")]
    public sealed class DependencyValueTests
    {
        public sealed class Probe : Decorator
        {
            protected override AutomationPeer OnCreateAutomationPeer() => new FrameworkElementAutomationPeer(this);
            public static readonly DependencyProperty AmountProperty = DependencyProperty.Register(nameof(Amount), typeof(double), typeof(Probe), new FrameworkPropertyMetadata(7.0, FrameworkPropertyMetadataOptions.Inherits, null, CoerceAmount));
            public static readonly DependencyProperty PayloadProperty = DependencyProperty.Register(nameof(Payload), typeof(object), typeof(Probe));
            public int GetterCalls;
            public bool CoercionEnabled;
            public double Amount { get { GetterCalls++; return (double)GetValue(AmountProperty); } set { SetValue(AmountProperty, value); } }
            public object? Payload { get { GetterCalls++; return GetValue(PayloadProperty); } set { SetValue(PayloadProperty, value); } }
            private static object CoerceAmount(DependencyObject target, object value) => ((Probe)target).CoercionEnabled ? Math.Min(10.0, (double)value) : value;
        }

        [Fact]
        public void DefaultAndLocalSourcesUseGetValueNotTheClrWrapper()
        {
            Sta(() =>
            {
                var target = new Probe();
                var reader = new Reader(target);
                ValueDto defaultValue = ReadSource(reader, target, Probe.AmountProperty, "Default");
                Assert.Equal("7", ValueTests.Number(defaultValue));
                Assert.False(defaultValue.DependencySource!.IsExpression);
                Assert.False(defaultValue.DependencySource.IsAnimated);
                Assert.False(defaultValue.DependencySource.IsCoerced);
                Assert.False(defaultValue.DependencySource.IsCurrent);
                target.SetValue(Probe.AmountProperty, 12.0);
                Assert.Equal("12", ValueTests.Number(ReadSource(reader, target, Probe.AmountProperty, "Local")));
                Assert.Equal(0, target.GetterCalls);
            });
        }

        [Fact]
        public void InheritedSourceComesFromTheCurrentLogicalParent()
        {
            Sta(() =>
            {
                var target = new Probe();
                var parent = new Probe { Child = target };
                parent.SetValue(Probe.AmountProperty, 23.0);
                ValueDto value = ReadSource(new Reader(target), target, Probe.AmountProperty, "Inherited");
                Assert.Equal("23", ValueTests.Number(value));
                Assert.Equal(0, target.GetterCalls);
            });
        }

        [Fact]
        public void StyleSourceIsReportedWithoutAClrGetter()
        {
            Sta(() =>
            {
                var style = new Style(typeof(Probe));
                style.Setters.Add(new Setter(Probe.AmountProperty, 15.0));
                var target = new Probe { Style = style };
                Assert.Equal("15", ValueTests.Number(ReadSource(new Reader(target), target, Probe.AmountProperty, "Style")));
                Assert.Equal(0, target.GetterCalls);
            });
        }

        [Fact]
        public void AnimatedSourceIncludesTheAnimationFlag()
        {
            Sta(() =>
            {
                var target = new Probe();
                target.SetValue(Probe.AmountProperty, 4.0);
                var clock = (AnimationClock)new DoubleAnimation(19.0, 19.0, new Duration(TimeSpan.FromHours(1))).CreateClock(true);
                target.ApplyAnimationClock(Probe.AmountProperty, clock);
                clock.Controller!.Begin();
                clock.Controller.SeekAlignedToLastTick(TimeSpan.Zero, TimeSeekOrigin.BeginTime);
                try
                {
                    ValueDto value = ReadSource(new Reader(target), target, Probe.AmountProperty, "Local");
                    Assert.True(value.DependencySource!.IsAnimated);
                    Assert.Equal(ValueKind.Number, value.Kind);
                    Assert.Equal(0, target.GetterCalls);
                }
                finally { target.BeginAnimation(Probe.AmountProperty, null); }
            });
        }

        [Fact]
        public void CoercedSourceIncludesTheCoercionFlagAndEffectiveValue()
        {
            Sta(() =>
            {
                var target = new Probe { CoercionEnabled = true };
                target.SetValue(Probe.AmountProperty, 50.0);
                ValueDto value = ReadSource(new Reader(target), target, Probe.AmountProperty, "Local");
                Assert.Equal("10", ValueTests.Number(value));
                Assert.True(value.DependencySource!.IsCoerced);
                Assert.Equal(0, target.GetterCalls);
            });
        }

        [Fact]
        public void CurrentValueSourceIncludesTheCurrentFlag()
        {
            Sta(() =>
            {
                var target = new Probe();
                target.SetCurrentValue(Probe.AmountProperty, 9.0);
                ValueDto value = ReadSource(new Reader(target), target, Probe.AmountProperty, "Default");
                Assert.True(value.DependencySource!.IsCurrent);
                Assert.Equal("9", ValueTests.Number(value));
                Assert.Equal(0, target.GetterCalls);
            });
        }

        [Fact]
        public void DependencySourcesRespectNullTruncatedCycleAndUnsupportedVariants()
        {
            Sta(() =>
            {
                var target = new Probe();
                var reader = new Reader(target);
                ValueDto empty = ReadSource(reader, target, Probe.PayloadProperty, "Default");
                Assert.Equal(ValueKind.Null, empty.Kind);
                target.Payload = new string('x', 4097);
                Assert.Equal(ValueStatus.Truncated, ReadSource(reader, target, Probe.PayloadProperty, "Local").Status);
                target.Payload = target;
                Assert.Equal(ValueStatus.Cycle, ReadSource(reader, target, Probe.PayloadProperty, "Local").Status);
                target.Payload = IntPtr.Zero;
                ValueDto unsupported = reader.Read(Dependency(Probe.PayloadProperty));
                Assert.Equal(ValueStatus.Unsupported, unsupported.Status);
                Assert.Null(unsupported.DependencySource);
                target.Payload = null;
                ValueDto missing = reader.Read(Dependency(Probe.PayloadProperty), Property("Name"));
                Assert.Equal(ValueStatus.NullIntermediate, missing.Status);
                Assert.Equal(0, missing.FailedSegment);
                Assert.Null(missing.DependencySource);
                Assert.Equal(0, target.GetterCalls);
            });
        }

        private sealed class Model
        {
            public string Name { get; set; } = "";
        }

        private sealed class SafeBorder : Border
        {
            protected override AutomationPeer OnCreateAutomationPeer() => new FrameworkElementAutomationPeer(this);
        }

        [Fact]
        public void DataContextChangesAreVisibleOnEveryReadAndSourcesDoNotLeak()
        {
            Sta(() =>
            {
                var target = new SafeBorder { DataContext = new Model { Name = "first" } };
                var reader = new Reader(target);
                Assert.Equal("first", ValueTests.Text(reader.Read(Property("DataContext"), Property("Name"))));
                target.DataContext = new Model { Name = "second" };
                Assert.Equal("second", ValueTests.Text(reader.Read(Property("DataContext"), Property("Name"))));
                ValueDto nested = reader.Read(Dependency(FrameworkElement.DataContextProperty), Property("Name"));
                Assert.Equal("second", ValueTests.Text(nested));
                Assert.Null(nested.DependencySource);
                ValueDto direct = reader.Read(Dependency(FrameworkElement.DataContextProperty));
                Assert.Equal("Local", direct.DependencySource!.BaseValueSource);
                Assert.Null(reader.Read(Property("DataContext")).DependencySource);
            });
        }

        [Fact]
        public void DependencySegmentsCannotAddressForeignOwnersOrAssemblies()
        {
            Sta(() =>
            {
                var reader = new Reader(new Probe());
                var wrongOwner = Dependency(Probe.AmountProperty);
                wrongOwner.OwnerType = typeof(Border).FullName;
                var wrongAssembly = Dependency(Probe.AmountProperty);
                wrongAssembly.OwnerAssembly = "Missing.Assembly.Must.Not.Be.Loaded";
                var absent = Dependency(Border.BackgroundProperty);
                foreach (PathSegment path in new[] { wrongOwner, wrongAssembly, absent })
                    Assert.Equal(ErrorCodes.MemberNotFound, Assert.Throws<ProtocolException>(() => reader.Read(path)).Code);
            });
        }

        private static ValueDto ReadSource(Reader reader, DependencyObject target, DependencyProperty property, string baseSource)
        {
            ValueDto value = reader.Read(Dependency(property));
            DependencySourceDto source = Assert.IsType<DependencySourceDto>(value.DependencySource);
            ValueSource expected = DependencyPropertyHelper.GetValueSource(target, property);
            Assert.Equal(baseSource, source.BaseValueSource);
            Assert.Equal(expected.IsExpression, source.IsExpression);
            Assert.Equal(expected.IsAnimated, source.IsAnimated);
            Assert.Equal(expected.IsCoerced, source.IsCoerced);
            Assert.Equal(expected.IsCurrent, source.IsCurrent);
            return value;
        }
    }
}
