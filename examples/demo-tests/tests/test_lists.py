"""The virtualized list box and data grid."""

from pages import MainPage

from wintestkit import expect


def test_select_a_far_away_list_item(main: MainPage) -> None:
    main.items.select("Item 450")  # not realized yet: WinTestKit asks the container for it
    expect(main.status).to_have_text("Selected: Item 450")


def test_select_a_list_item_by_index(main: MainPage) -> None:
    main.items.select(2)
    expect(main.status).to_have_text("Selected: Item 3")


def test_grid_dimensions(main: MainPage) -> None:
    assert main.products.row_count() == 200
    assert main.products.column_count() == 3


def test_select_a_grid_row_by_index(main: MainPage) -> None:
    main.products.select(120)
    expect(main.status).to_have_text("Row: Product 121")


def test_read_grid_cells(main: MainPage) -> None:
    assert main.products.cell(5, "Name").text == "Product 6"
    assert main.products.cell(9, "Qty").text == "1"  # Product 10: (10 * 7) mod 23


def test_find_a_row_by_value(main: MainPage) -> None:
    main.products.find_row("Name", "Product 180").click()
    expect(main.status).to_have_text("Row: Product 180")
