using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;

namespace DemoApp;

public partial class MainWindow : Window
{
    private readonly TextBox username;
    private readonly PasswordBox password;
    private readonly CheckBox rememberMe;
    private readonly Button load;
    private readonly Button continueButton;
    private readonly TextBlock loadedText;
    private readonly ListBox items;
    private readonly DataGrid products;
    private readonly DispatcherTimer loadTimer;
    private bool resetting;

    public MainWindow(int loadDelay)
    {
        InitializeComponent();
        List<DependencyObject> controls = Descendants(this).ToList();
        username = controls.OfType<TextBox>().Single();
        password = controls.OfType<PasswordBox>().Single();
        rememberMe = controls.OfType<CheckBox>().Single();
        load = controls.OfType<Button>().Single(button => Equals(button.Content, "Load"));
        continueButton = controls.OfType<Button>().Single(button => Equals(button.Content, "Continue"));
        loadedText = controls.OfType<TextBlock>().Single(text => text.Text == "Data loaded");
        items = controls.OfType<ListBox>().Single();
        products = controls.OfType<DataGrid>().Single();
        loadTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(loadDelay) };
        loadTimer.Tick += LoadTimer_Tick;
        Closed += (_, _) => loadTimer.Stop();

        resetting = true;
        ColorCombo.ItemsSource = new[] { "Red", "Green", "Blue" };
        items.ItemsSource = Enumerable.Range(1, 500).Select(number => $"Item {number}").ToList();
        products.ItemsSource = Enumerable.Range(1, 200).Select(number => new Product
        {
            Id = number,
            Name = $"Product {number}",
            Qty = (number * 7) % 23
        }).ToList();
        resetting = false;
    }

    private static IEnumerable<DependencyObject> Descendants(DependencyObject parent)
    {
        foreach (object child in LogicalTreeHelper.GetChildren(parent))
        {
            if (child is DependencyObject element)
            {
                yield return element;
                foreach (DependencyObject descendant in Descendants(element))
                {
                    yield return descendant;
                }
            }
        }
    }

    private void SignIn_Click(object sender, RoutedEventArgs args)
    {
        StatusText.Text = username.Text == "admin" && password.Password == "secret"
            ? "Welcome, admin" : "Invalid credentials";
    }

    private void PanelA_Click(object sender, RoutedEventArgs args) => StatusText.Text = "A OK";

    private void RememberMe_Changed(object sender, RoutedEventArgs args)
    {
        if (!resetting)
        {
            StatusText.Text = $"Remember: {((CheckBox)sender).IsChecked == true}";
        }
    }

    private void PanelB_Click(object sender, RoutedEventArgs args) => StatusText.Text = "B OK";
    private void Continue_Click(object sender, RoutedEventArgs args) => StatusText.Text = "Continued";

    private void Load_Click(object sender, RoutedEventArgs args)
    {
        load.IsEnabled = false;
        StatusText.Text = "Loading...";
        loadTimer.Start();
    }

    private void LoadTimer_Tick(object? sender, EventArgs args)
    {
        loadTimer.Stop();
        loadedText.Visibility = Visibility.Visible;
        continueButton.IsEnabled = true;
        StatusText.Text = "Loaded";
    }

    private void Color_SelectionChanged(object sender, SelectionChangedEventArgs args)
    {
        if (!resetting && ColorCombo.SelectedItem is string color)
        {
            StatusText.Text = $"Color: {color}";
        }
    }

    private void Items_SelectionChanged(object sender, SelectionChangedEventArgs args)
    {
        if (!resetting && ((ListBox)sender).SelectedItem is string item)
        {
            StatusText.Text = $"Selected: {item}";
        }
    }

    private void Products_SelectionChanged(object sender, SelectionChangedEventArgs args)
    {
        if (!resetting && ((DataGrid)sender).SelectedItem is Product product)
        {
            StatusText.Text = $"Row: {product.Name}";
        }
    }

    private void OpenDialog_Click(object sender, RoutedEventArgs args)
    {
        var dialog = new NoteDialog { Owner = this };
        StatusText.Text = dialog.ShowDialog() == true ? $"Note: {dialog.Note}" : "Note cancelled";
    }

    private void ShowMessage_Click(object sender, RoutedEventArgs args)
    {
        MessageBox.Show(this, "Hello from demo", "WTK Demo Message");
        StatusText.Text = "Message closed";
    }

    private void Reset_Click(object sender, RoutedEventArgs args)
    {
        resetting = true;
        loadTimer.Stop();
        username.Clear();
        password.Clear();
        rememberMe.IsChecked = false;
        load.IsEnabled = true;
        loadedText.Visibility = Visibility.Collapsed;
        continueButton.IsEnabled = false;
        ColorCombo.SelectedIndex = -1;
        items.SelectedIndex = -1;
        products.SelectedIndex = -1;
        resetting = false;
        StatusText.Text = "Ready";
    }

    private void Exit_Click(object sender, RoutedEventArgs args) => Close();
    private void About_Click(object sender, RoutedEventArgs args) => MessageBox.Show(this, "WTK Demo 1.0", "About");
}
