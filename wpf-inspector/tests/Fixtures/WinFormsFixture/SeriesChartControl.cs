using System.Drawing;
using System.Windows.Forms;

namespace WinTestKit.WinFormsFixture;

/// <summary>A nested object of a custom control: a string member below the control's own members.</summary>
public sealed class SeriesChartFooter
{
    public string Text { get; set; } = "Page 1 of 2";
    public int Pages { get; set; } = 2;
}

/// <summary>
/// A custom control that exposes native members the way a third-party chart does: an int property, a nested object with a
/// string property, and a list that is read by position. It paints nothing; it exists to be read and matched by managed keys.
/// </summary>
public sealed class SeriesChartControl : UserControl
{
    public SeriesChartControl()
    {
        Name = "seriesChart1";
        Size = new Size(330, 44);
        BorderStyle = BorderStyle.FixedSingle;
        Controls.Add(new Label { Name = "seriesChartCaption", Text = "Series chart", AutoSize = true, Location = new Point(6, 6) });
    }

    public int SeriesCount { get; set; } = 3;
    public SeriesChartFooter Footer { get; } = new SeriesChartFooter();
    public string[] SeriesTitles { get; } = { "Alpha", "Beta", "Gamma" };
}
