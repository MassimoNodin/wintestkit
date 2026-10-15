"""Two groups with identical "OK" buttons: disambiguate with within=, index or Elements."""

import pytest
from pages import MainPage

from wintestkit import Element, expect
from wintestkit.errors import AmbiguousElementError


def test_panel_a_ok(main: MainPage) -> None:
    main.ok_a.click()
    expect(main.status).to_have_text("A OK")


def test_panel_b_ok(main: MainPage) -> None:
    main.ok_b.click()
    expect(main.status).to_have_text("B OK")


def test_both_ok_buttons_are_found_as_a_collection(main: MainPage) -> None:
    expect(main.all_ok_buttons).to_have_count(2)
    main.all_ok_buttons.last().click()
    expect(main.status).to_have_text("B OK")
    main.all_ok_buttons.first().click()
    expect(main.status).to_have_text("A OK")


def test_an_ambiguous_locator_fails_fast_with_a_clear_message(main: MainPage) -> None:
    class Ambiguous(MainPage):
        either_ok = Element(control_type="Button", name="OK")

    with pytest.raises(AmbiguousElementError) as error:
        Ambiguous(main.app).either_ok.click()
    assert str(error.value) == (
        '2 elements match Button[name="OK"] in Window "WTK Demo"; '
        "add within= or index= to pick one"
    )
