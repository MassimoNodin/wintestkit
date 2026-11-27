using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

namespace WinTestKit.WinFormsFixture;

/// <summary>The WinForms counterpart of the WPF fixture: a test target that does not reference the inspector.</summary>
public sealed class MainForm : Form
{
    internal readonly FixtureUserControl Custom = new FixtureUserControl { Location = new Point(12, 520) };
    internal readonly SeriesChartControl Chart = new SeriesChartControl { Location = new Point(12, 594) };
    private readonly List<Form> opened = new List<Form>();

    public MainForm()
    {
        Name = "mainForm";
        Text = "WinForms Fixture";
        ClientSize = new Size(900, 640);
        StartPosition = FormStartPosition.Manual;
        Location = new Point(80, 60);

        var menu = new MenuStrip { Name = "menuStrip1" };
        var file = new ToolStripMenuItem("&File") { Name = "fileToolStripMenuItem" };
        file.DropDownItems.Add(new ToolStripMenuItem("&Open") { Name = "openToolStripMenuItem" });
        file.DropDownItems.Add(new ToolStripMenuItem("E&xit") { Name = "exitToolStripMenuItem" });
        menu.Items.Add(file);
        menu.Items.Add(new ToolStripMenuItem("&Help") { Name = "helpToolStripMenuItem" });
        MainMenuStrip = menu;

        var button1 = new Button { Name = "button1", Text = "OK", Location = new Point(12, 40), Size = new Size(90, 28) };
        var button2 = new Button { Name = "button2", Text = "Cancel", Location = new Point(112, 40), Size = new Size(90, 28) };
        var textBox1 = new TextBox { Name = "textBox1", Text = "hello", Location = new Point(12, 80), Size = new Size(190, 23) };
        var password = new TextBox { Name = "passwordBox", Text = "hunter2", UseSystemPasswordChar = true, Location = new Point(212, 80), Size = new Size(150, 23) };
        var label1 = new Label { Name = "label1", Text = "Label", Location = new Point(12, 116), AutoSize = true };
        var checkBox1 = new CheckBox { Name = "checkBox1", Text = "Check me", Location = new Point(112, 114), AutoSize = true };
        var comboBox1 = new ComboBox { Name = "comboBox1", Location = new Point(212, 112), Size = new Size(150, 23), DropDownStyle = ComboBoxStyle.DropDownList };
        comboBox1.Items.AddRange(new object[] { "alpha", "beta", "gamma" });
        comboBox1.SelectedIndex = 0;
        var listBox1 = new ListBox { Name = "listBox1", Location = new Point(12, 150), Size = new Size(190, 70) };
        listBox1.Items.AddRange(new object[] { "one", "two", "three" });

        var group = new GroupBox { Name = "groupBox1", Text = "Group", Location = new Point(212, 150), Size = new Size(250, 70) };
        group.Controls.Add(new Button { Name = "nestedButton1", Text = "Nested 1", Location = new Point(10, 24), Size = new Size(100, 28) });
        group.Controls.Add(new Button { Name = "nestedButton2", Text = "Nested 2", Location = new Point(130, 24), Size = new Size(100, 28) });

        var tabs = new TabControl { Name = "tabControl1", Location = new Point(12, 232), Size = new Size(440, 130) };
        var page1 = new TabPage("First") { Name = "tabPage1" };
        page1.Controls.Add(new Label { Name = "firstPageLabel", Text = "First page", Location = new Point(8, 8), AutoSize = true });
        var page2 = new TabPage("Second") { Name = "tabPage2" };
        page2.Controls.Add(new Button { Name = "secondPageButton", Text = "On page two", Location = new Point(8, 8), Size = new Size(110, 28) });
        tabs.TabPages.Add(page1);
        tabs.TabPages.Add(page2);

        var grid = new DataGridView { Name = "dataGridView1", Location = new Point(12, 374), Size = new Size(440, 130), AllowUserToAddRows = false };
        grid.Columns.Add("name", "Name");
        grid.Columns.Add("value", "Value");
        grid.Rows.Add("row 1", "10");
        grid.Rows.Add("row 2", "20");

        Controls.AddRange(new Control[] { menu, button1, button2, textBox1, password, label1, checkBox1, comboBox1, listBox1, group, tabs, grid, Custom, Chart });
    }

    /// <summary>Test-setup scenarios that open and close windows; they change no inspected value.</summary>
    internal void Scenario(string name)
    {
        if (name == "openSecondForm")
        {
            var form = new Form { Name = "secondForm", Text = "Second Form", ClientSize = new Size(320, 120), StartPosition = FormStartPosition.Manual, Location = new Point(Left + 40, Top + 80) };
            form.Controls.Add(new Button { Name = "secondButton", Text = "Second", Location = new Point(12, 12), Size = new Size(90, 28) });
            Track(form).Show(this);
        }
        else if (name == "openDuplicateButtons")
        {
            // Unnamed siblings with the same type and text: only their place tells them apart.
            var form = new Form { Name = "duplicateForm", Text = "Duplicate Buttons", ClientSize = new Size(320, 120), StartPosition = FormStartPosition.Manual, Location = new Point(Left + 80, Top + 120) };
            form.Controls.Add(new Button { Text = "Same", Location = new Point(12, 12), Size = new Size(90, 28) });
            form.Controls.Add(new Button { Text = "Same", Location = new Point(112, 12), Size = new Size(90, 28) });
            form.Controls.Add(new Button { Text = "Other", Location = new Point(212, 12), Size = new Size(90, 28) });
            Track(form).Show(this);
        }
        else if (name == "closeForm")
        {
            for (int index = opened.Count - 1; index >= 0; index--)
            {
                Form form = opened[index];
                opened.RemoveAt(index);
                if (!form.IsDisposed) { form.Close(); break; }
            }
        }
    }

    private Form Track(Form form) { opened.Add(form); return form; }
}

public static class Program
{
    private static string Json(string body) => "{" + body + "}";

    private static NamedPipeServerStream CreatePipe()
    {
        string name = "WinTestKit.WinFormsFixture." + Process.GetCurrentProcess().Id;
#if NETFRAMEWORK
        var security = new PipeSecurity();
        var sid = System.Security.Principal.WindowsIdentity.GetCurrent().User!;
        security.SetAccessRuleProtection(true, false);
        security.AddAccessRule(new PipeAccessRule(sid, PipeAccessRights.FullControl, System.Security.AccessControl.AccessControlType.Allow));
        return new NamedPipeServerStream(name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.None, 4096, 4096, security);
#else
        return new NamedPipeServerStream(name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.CurrentUserOnly);
#endif
    }

    private static string? Field(string line, string name)
    {
        Match match = Regex.Match(line, "\"" + name + "\"\\s*:\\s*\"([^\"]*)\"");
        return match.Success ? match.Groups[1].Value : null;
    }

    /// <summary>Newline-delimited JSON on \\.\pipe\WinTestKit.WinFormsFixture.&lt;pid&gt;: counters, exit and scenario commands.</summary>
    private static void Serve(MainForm form)
    {
        while (true)
        {
            try
            {
                using NamedPipeServerStream pipe = CreatePipe();
                pipe.WaitForConnection();
                using var reader = new StreamReader(pipe, Encoding.UTF8, false, 1024, true);
                using var writer = new StreamWriter(pipe, new UTF8Encoding(false), 1024, true) { AutoFlush = true };
                string? line;
                while ((line = reader.ReadLine()) != null)
                {
                    string response = Json("\"ok\":true");
                    string? command = Field(line, "cmd");
                    if (command == "counters") response = Json("\"writeCount\":" + form.Custom.WriteCount);
                    else if (command == "exit") form.BeginInvoke(new Action(Application.Exit));
                    else if (command == "scenario")
                    {
                        string name = Field(line, "name") ?? "";
                        if (name == "openSecondForm" || name == "closeForm" || name == "openDuplicateButtons") form.BeginInvoke(new Action(() => form.Scenario(name)));
                        else response = Json("\"error\":\"unknown scenario\"");
                    }
                    else response = Json("\"error\":\"unknown command\"");
                    writer.WriteLine(response);
                }
            }
            catch (Exception) { Thread.Sleep(100); }
        }
    }

    [STAThread]
    public static void Main(string[] args)
    {
#if NET5_0_OR_GREATER
        Application.SetHighDpiMode(HighDpiMode.SystemAware);
#endif
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        var form = new MainForm();
        new Thread(() => Serve(form)) { IsBackground = true, Name = "WinForms fixture pipe" }.Start();
        int scenario = Array.IndexOf(args, "--scenario");
        if (scenario >= 0 && scenario + 1 < args.Length) form.Shown += (_, _) => form.Scenario(args[scenario + 1]);
        Application.Run(form);
    }
}
