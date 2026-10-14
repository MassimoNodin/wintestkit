"""Integration tests for Elements collections and grid helpers."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from screens import MainScreen
from support import DemoProcess

from wintestkit import expect, runtime
from wintestkit.app import App
from wintestkit.config import load_config
from wintestkit.errors import ActionError

pytestmark = pytest.mark.integration


@pytest.fixture
def main(demo_process: DemoProcess, tmp_path: Path) -> Iterator[MainScreen]:
    runtime.reset()
    runtime.set_config(load_config(tmp_path, {"timeout": 8.0}))
    yield MainScreen(App.attach(pid=demo_process.pid))
    runtime.reset()


def test_buttons_named_ok(main: MainScreen) -> None:
    assert main.all_oks.count() == 2
    assert len(main.all_oks) == 2
    assert [b.locator.index for b in main.all_oks] == [0, 1]
    expect(main.all_oks).to_have_count(2)
    main.all_oks.last().click()
    expect(main.status).to_have_text("B OK")
    main.all_oks.first().click()
    expect(main.status).to_have_text("A OK")
    assert main.all_oks.texts() == ["OK", "OK"]


def test_combo_item_texts_after_expand(main: MainScreen) -> None:
    main.color.expand()
    assert main.color_items.count(timeout=3) == 3
    assert main.color_items.texts() == ["Red", "Green", "Blue"]
    narrowed = main.color_items.filter(name="Green")
    assert narrowed.count() == 1
    narrowed.first().click()
    expect(main.status).to_have_text("Color: Green")


def test_missing_collection_is_empty(main: MainScreen) -> None:
    assert main.color_items.count() == 0  # collapsed combos expose no items
    expect(main.color_items).to_have_count(0)


def test_grid_row_and_cell_helpers(main: MainScreen) -> None:
    assert main.products.row_count() == 200
    assert main.products.column_count() == 3
    assert main.products.cell(9, "Qty").text == "1"  # Product 10: (10 * 7) mod 23
    assert main.products.cell(5, "Name").text == "Product 6"
    assert main.products.cell(0, 0).text == "1"
    main.products.row(3).click()
    expect(main.status).to_have_text("Row: Product 4")


def test_find_row_by_column_value(main: MainScreen) -> None:
    row = main.products.find_row("Name", "Product 180")
    assert row.locator.describe() == "DataGrid > row(179)"
    row.click()
    expect(main.status).to_have_text("Row: Product 180")


def test_find_row_errors(main: MainScreen) -> None:
    with pytest.raises(ActionError, match="no column 'Nope'"):
        main.products.find_row("Nope", "x")
    with pytest.raises(ActionError, match="out of range"):
        main.products.find_row(9, "x")
    from wintestkit.errors import ElementNotFoundError

    with pytest.raises(ElementNotFoundError, match="No row with 'Name' = 'Product 999'"):
        main.products.find_row("Name", "Product 999")
