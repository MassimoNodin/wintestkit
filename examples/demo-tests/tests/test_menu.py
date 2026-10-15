"""The menu bar."""

from pages import MainPage, MessageBox

from wintestkit import expect


def test_reset_clears_the_form(main: MainPage) -> None:
    main.username.type("someone")
    main.remember_me.check()
    main.menu_file.click()
    main.menu_reset.click()
    expect(main.status).to_have_text("Ready")
    expect(main.username).to_have_value("")
    expect(main.remember_me).not_.to_be_checked()


def test_about_box(main: MainPage) -> None:
    main.menu_help.click()
    main.menu_about.click()
    box = MessageBox(main.app)
    expect(box.text).to_have_text("WTK Demo 1.0")
    box.ok.click()
    expect(box.window).not_.to_exist()
