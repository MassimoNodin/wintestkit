"""The demo app's main window.

The demo is a black box: it sets an AutomationId on only two controls (``StatusText`` and
``ColorCombo``), so everything else is located by control type, class name, visible name and
its position in the tree (``within=``).
"""

from wintestkit import Element, Elements, Page, Window


class MainPage(Page):
    window = Window(title="WTK Demo")

    # menu
    menu_file = Element(control_type="MenuItem", name="File")
    menu_reset = Element(control_type="MenuItem", name="Reset")
    menu_help = Element(control_type="MenuItem", name="Help")
    menu_about = Element(control_type="MenuItem", name="About")

    # credentials
    credentials = Element(control_type="Group", name="Credentials")
    username = Element(control_type="Edit", class_name="TextBox", within=credentials)
    password = Element(control_type="Edit", class_name="PasswordBox", within=credentials)
    remember_me = Element(control_type="CheckBox", name="Remember me", within=credentials)
    sign_in = Element(control_type="Button", name="Sign in", within=credentials)

    # two groups that each contain an "OK" button
    panel_a = Element(control_type="Group", name="Panel A")
    panel_b = Element(control_type="Group", name="Panel B")
    ok_a = Element(control_type="Button", name="OK", within=panel_a)
    ok_b = Element(control_type="Button", name="OK", within=panel_b)
    all_ok_buttons = Elements(control_type="Button", name="OK")

    # asynchronous loading
    load = Element(control_type="Button", name="Load")
    continue_button = Element(control_type="Button", name="Continue")
    data_loaded = Element(control_type="Text", name="Data loaded")

    # choices
    color = Element(automation_id="ColorCombo")
    color_items = Elements(control_type="ListItem", within=color)

    # virtualized list and grid
    items = Element(control_type="List", class_name="ListBox")
    products = Element(control_type="DataGrid")

    # dialogs
    open_dialog = Element(control_type="Button", name="Open dialog")
    show_message = Element(control_type="Button", name="Show message")

    status = Element(automation_id="StatusText")
