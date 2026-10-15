"""Asynchronous behaviour: actions and assertions wait automatically."""

from pages import MainPage

from wintestkit import expect


def test_continue_waits_until_it_is_enabled(main: MainPage) -> None:
    expect(main.continue_button).to_be_disabled()
    main.load.click()
    expect(main.status).to_have_text("Loading...")
    main.continue_button.click()  # disabled for about two seconds: click() waits
    expect(main.status).to_have_text("Continued")


def test_data_loaded_appears_after_loading(main: MainPage) -> None:
    expect(main.data_loaded).not_.to_exist()
    main.load.click()
    expect(main.status).to_have_text("Loaded")
    expect(main.data_loaded).to_be_visible()
    expect(main.load).to_be_disabled()


def test_reset_cancels_a_pending_load(main: MainPage) -> None:
    main.load.click()
    main.menu_file.click()
    main.menu_reset.click()
    expect(main.status).to_have_text("Ready")
    expect(main.load).to_be_enabled()
    expect(main.continue_button).to_be_disabled()
