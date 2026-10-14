"""Screens for the WPF demo app, written in the black-box style users will write them."""

from wintestkit import Element, Elements, Screen, Window


class MainScreen(Screen):
    window = Window(title="WTK Demo")

    menu_file = Element(control_type="MenuItem", name="File")
    menu_reset = Element(control_type="MenuItem", name="Reset")

    credentials = Element(control_type="Group", name="Credentials")
    username = Element(control_type="Edit", class_name="TextBox", within=credentials)
    password = Element(control_type="Edit", class_name="PasswordBox", within=credentials)
    remember = Element(control_type="CheckBox", name="Remember me", within=credentials)
    sign_in = Element(control_type="Button", name="Sign in", within=credentials)

    panel_a = Element(control_type="Group", name="Panel A")
    panel_b = Element(control_type="Group", name="Panel B")
    ok_a = Element(control_type="Button", name="OK", within=panel_a)
    ok_b = Element(control_type="Button", name="OK", within=panel_b)
    all_oks = Elements(control_type="Button", name="OK")

    load = Element(control_type="Button", name="Load")
    continue_button = Element(control_type="Button", name="Continue")
    data_loaded = Element(control_type="Text", name="Data loaded")

    color = Element(automation_id="ColorCombo")
    color_items = Elements(control_type="ListItem", within=color)
    items = Element(control_type="List", class_name="ListBox")
    products = Element(control_type="DataGrid")

    open_dialog = Element(control_type="Button", name="Open dialog")
    show_message = Element(control_type="Button", name="Show message")
    status = Element(automation_id="StatusText")


class NoteDialogScreen(Screen):
    window = Window(title="WTK Demo - Dialog")

    note = Element(control_type="Edit")
    save = Element(control_type="Button", name="Save")
    cancel = Element(control_type="Button", name="Cancel")


class MessageBoxScreen(Screen):
    window = Window(class_name="#32770")

    ok = Element(control_type="Button", name="OK")
