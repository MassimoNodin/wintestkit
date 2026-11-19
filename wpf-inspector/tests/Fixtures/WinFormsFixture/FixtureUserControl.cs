using System;
using System.ComponentModel;
using System.Drawing;
using System.Windows.Forms;

namespace WinTestKit.WinFormsFixture;

/// <summary>
/// A custom control with one member of every kind the Spy lists: public, private and internal properties and
/// fields, a property that has a default value, a getter that throws, and methods to invoke.
/// </summary>
public sealed class FixtureUserControl : UserControl
{
    private readonly Label output = new Label { Name = "writeOutput", Text = "(no write yet)", AutoSize = true, Location = new Point(6, 6) };

    public FixtureUserControl()
    {
        Name = "fixtureUserControl1";
        Size = new Size(330, 70);
        BorderStyle = BorderStyle.FixedSingle;
        Controls.Add(output);
    }

    public string PublicProperty { get; set; } = "public value";
    private string PrivateProperty { get; set; } = "private value";
    internal string InternalProperty { get; set; } = "internal value";
    [DefaultValue("default value")] public string DefaultedProperty { get; set; } = "default value";
    public string ThrowingProperty => throw new InvalidOperationException("The fixture getter always fails.");

    public int PublicField = 3;
    private string privateField = "private field";
    internal int internalField = 5;
    public string LastValue = "";
    public int LastNumber;
    public int WriteCount;

    /// <summary>Stores its arguments and shows them in a label, so a live invoke is visible.</summary>
    public void RecordWrite(string value, int number)
    {
        LastValue = value;
        LastNumber = number;
        WriteCount++;
        output.Text = "RecordWrite(" + value + ", " + number + ") #" + WriteCount;
    }

    public int Add(int first, int second) => first + second;
    public string Echo(string text) => text;
    public bool Toggle(bool value) => !value;
    public void Reset() { LastValue = ""; LastNumber = 0; WriteCount = 0; output.Text = "(no write yet)"; }
    private string PrivateMethod() => privateField;
    internal int InternalMethod() => internalField;
    public static string StaticHelper() => "static";
}
