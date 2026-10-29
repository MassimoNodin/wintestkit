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
    public sealed class RedactionIdentityTests
    {
        private sealed class ProtectedControl : Button
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
                var error = Assert.Throws<ProtocolException>(() => reader.Inspector.GetBindings(target, new[] { key }));
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

        [Fact] public void MissingPeerFailsClosed()
        {
            Sta(() =>
            {
                var target = new NoPeer();
                Assert.Equal("identity", new Reader(target).Read(Property("VisibleValue")).RedactionRule);
                Assert.Equal(0, target.Calls);
            });
        }
    }
}
