"""Signing in: valid and invalid credentials."""

import pytest
from pages import MainPage

from wintestkit import expect


def test_valid_login(main: MainPage) -> None:
    main.username.type("admin")
    main.password.type("secret")
    main.sign_in.click()
    expect(main.status).to_have_text("Welcome, admin")


def test_invalid_login(main: MainPage) -> None:
    main.username.type("admin")
    main.password.type("wrong")
    main.sign_in.click()
    expect(main.status).to_have_text("Invalid credentials")


@pytest.mark.parametrize(
    ("username", "password", "message"),
    [
        ("admin", "secret", "Welcome, admin"),
        ("admin", "nope", "Invalid credentials"),
        ("guest", "secret", "Invalid credentials"),
        ("", "", "Invalid credentials"),
    ],
)
def test_login_matrix(main: MainPage, username: str, password: str, message: str) -> None:
    if username:
        main.username.type(username)
    if password:
        main.password.type(password)
    main.sign_in.click()
    expect(main.status).to_have_text(message)


def test_remember_me_can_be_checked_and_unchecked(main: MainPage) -> None:
    main.remember_me.check()
    expect(main.remember_me).to_be_checked()
    expect(main.status).to_have_text("Remember: True")
    main.remember_me.uncheck()
    expect(main.remember_me).not_.to_be_checked()
    expect(main.status).to_have_text("Remember: False")


def test_the_password_is_never_readable(main: MainPage) -> None:
    main.password.type("secret")
    assert "secret" not in main.password.text
