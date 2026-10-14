"""A modal WPF dialog and a native message box."""

from screens import MainScreen, MessageBox, NoteDialog

from wintestkit import expect


def test_save_a_note(main: MainScreen) -> None:
    main.open_dialog.click()
    dialog = NoteDialog(main.app)
    dialog.note.type("remember the milk")
    dialog.save.click()
    expect(main.status).to_have_text("Note: remember the milk")
    expect(dialog.window).not_.to_exist()


def test_cancel_a_note(main: MainScreen) -> None:
    main.open_dialog.click()
    dialog = NoteDialog(main.app)
    dialog.cancel.click()
    expect(main.status).to_have_text("Note cancelled")


def test_closing_the_dialog_with_the_keyboard_cancels_it(main: MainScreen) -> None:
    main.open_dialog.click()
    dialog = NoteDialog(main.app)
    dialog.note.press("Alt+F4")
    expect(main.status).to_have_text("Note cancelled")


def test_message_box(main: MainScreen) -> None:
    main.show_message.click()
    box = MessageBox(main.app)
    expect(box.window).to_exist()
    expect(box.text).to_have_text("Hello from demo")
    box.ok.click()
    expect(main.status).to_have_text("Message closed")
