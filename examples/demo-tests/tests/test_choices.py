"""The color combo box."""

import re

from pages import MainPage

from wintestkit import expect


def test_select_a_color_by_name(main: MainPage) -> None:
    main.color.select("Blue")
    expect(main.status).to_have_text("Color: Blue")
    assert main.color.selected_items() == ["Blue"]


def test_select_a_color_by_index_and_by_pattern(main: MainPage) -> None:
    main.color.select(0)
    expect(main.status).to_have_text("Color: Red")
    main.color.select(re.compile("^Gr"))
    expect(main.status).to_have_text("Color: Green")


def test_the_dropdown_items(main: MainPage) -> None:
    main.color.expand()
    assert main.color_items.texts() == ["Red", "Green", "Blue"]
    main.color_items.filter(name="Green").first().click()
    expect(main.status).to_have_text("Color: Green")
