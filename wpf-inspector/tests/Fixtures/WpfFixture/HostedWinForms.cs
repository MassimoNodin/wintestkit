using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Forms.Integration;
using WinForms = System.Windows.Forms;

namespace WinTestKit.Fixture;

/// <summary>A nested object of a hosted control: a string member below the control's own members.</summary>
public sealed class HostedChartFooter
{
    public string Text { get; set; } = "Page 1 of 2";
}

/// <summary>A WinForms custom control with an int property and a nested object, as a third-party chart exposes them.</summary>
public sealed class HostedSeriesChart : WinForms.UserControl
{
    public HostedSeriesChart()
    {
        Name = "hostedSeriesChart";
        Controls.Add(new WinForms.Label { Name = "hostedCaption", Text = "Hosted chart", AutoSize = true, Location = new System.Drawing.Point(4, 4) });
    }

    public int SeriesCount { get; set; } = 7;
    public HostedChartFooter Footer { get; } = new HostedChartFooter();
}

/// <summary>
/// The "openHostedWinForms" scenario: a WPF window holding a WinForms control through a WindowsFormsHost. The WinForms
/// assembly is only loaded when the scenario runs, so the other scenarios still start a WPF-only process.
/// </summary>
internal static class HostedWinForms
{
    internal static Window Open()
    {
        var host = new WindowsFormsHost { Child = new HostedSeriesChart(), Width = 320, Height = 80 };
        AutomationProperties.SetAutomationId(host, "ChartHost");
        var panel = new StackPanel();
        panel.Children.Add(new Button { Content = "Beside the host", Name = "besideTheHost" });
        panel.Children.Add(host);
        var window = new Window { Title = "Hosted WinForms", Width = 400, Height = 200, Content = panel };
        AutomationProperties.SetAutomationId(window, "HostedWinFormsWindow");
        window.Show();
        return window;
    }
}
