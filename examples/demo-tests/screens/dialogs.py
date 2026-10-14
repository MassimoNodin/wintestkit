"""Secondary windows of the demo app."""

from wintestkit import Element, Screen, Window


class NoteDialog(Screen):
    """The modal dialog opened by "Open dialog" (an owned WPF window)."""

    window = Window(title="WTK Demo - Dialog")

    note = Element(control_type="Edit")
    save = Element(control_type="Button", name="Save")
    cancel = Element(control_type="Button", name="Cancel")


class MessageBox(Screen):
    """A native Win32 message box (window class ``#32770``)."""

    window = Window(class_name="#32770")

    ok = Element(control_type="Button", name="OK")
    text = Element(control_type="Text", index=0)
