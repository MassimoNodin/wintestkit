using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;

namespace WinTestKit.Inspector.Agent.Members.Tests
{
    /// <summary>A panel whose button has handlers wired in compiled XAML. The handlers throw, so a test notices if one is ever called.</summary>
    public partial class HandlerHost : StackPanel
    {
        public static int Invocations;
        public HandlerHost() { InitializeComponent(); }
        private void OnClick(object sender, RoutedEventArgs e) { Invocations++; throw new InvalidOperationException("handler invoked"); }
        private void OnPreview(object sender, MouseButtonEventArgs e) { Invocations++; throw new InvalidOperationException("handler invoked"); }
    }
}
