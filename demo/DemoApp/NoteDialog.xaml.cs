using System.Windows;
using System.Windows.Controls;

namespace DemoApp;

public partial class NoteDialog : Window
{
    public string Note { get; private set; } = string.Empty;

    public NoteDialog()
    {
        InitializeComponent();
    }

    private void Save_Click(object sender, RoutedEventArgs args)
    {
        var panel = (StackPanel)Content;
        foreach (object child in panel.Children)
        {
            if (child is TextBox noteBox)
            {
                Note = noteBox.Text;
                break;
            }
        }
        DialogResult = true;
    }
}
