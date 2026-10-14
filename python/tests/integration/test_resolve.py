"""Integration tests for the resolver and diagnostics against the demo app."""

import time
from collections.abc import Callable

import pytest
from support import DemoProcess, window_props

from wintestkit.app import App
from wintestkit.engine.locator import ItemSelector, Locator, WindowLocator
from wintestkit.engine.resolve import Scope, resolve, resolve_all
from wintestkit.errors import AmbiguousElementError, ElementNotFoundError, WindowNotFoundError
from wintestkit.uia import patterns, win32

pytestmark = pytest.mark.integration


@pytest.fixture
def scope(demo_process: DemoProcess) -> Scope:
    return Scope(App.attach(pid=demo_process.pid))


def wait_for(predicate: Callable[[], object], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert predicate()


def test_unique_button_and_timing(scope: Scope) -> None:
    locator = Locator(control_type="Button", name="Sign in")
    resolve(scope, locator)  # warm up COM and the cache request
    started = time.perf_counter()
    element = resolve(scope, locator)
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"resolve(Button[name='Sign in']) took {elapsed_ms:.0f} ms")
    assert element.name == "Sign in"
    assert element.control_type == "Button"


def test_ambiguous_ok_buttons(scope: Scope) -> None:
    with pytest.raises(AmbiguousElementError) as exc_info:
        resolve(scope, Locator(control_type="Button", name="OK"))
    diagnostic = exc_info.value.diagnostic
    assert diagnostic.match_count == 2
    assert str(exc_info.value) == (
        '2 elements match Button[name="OK"] in Window "WTK Demo"; add within= or index= to pick one'
    )
    print(diagnostic.format())


def test_within_disambiguates(scope: Scope) -> None:
    panel_b = Locator(control_type="Group", name="Panel B")
    button = resolve(scope, Locator(control_type="Button", name="OK", within=panel_b))
    parent = button.parent()
    assert parent is not None
    assert parent.name == "Panel B"


def test_index_picks_the_second_ok(scope: Scope) -> None:
    first = resolve(scope, Locator(control_type="Button", name="OK", index=0))
    second = resolve(scope, Locator(control_type="Button", name="OK", index=1))
    assert not first.same_as(second)
    parent = second.parent()
    assert parent is not None
    assert parent.name == "Panel B"


def test_password_box_and_status(scope: Scope) -> None:
    assert resolve(scope, Locator(control_type="Edit", class_name="PasswordBox")).class_name == (
        "PasswordBox"
    )
    status = resolve(scope, Locator(automation_id="StatusText"))
    assert status.name == "Ready"


def test_regex_and_virtualized_list_item(scope: Scope) -> None:
    assert resolve(scope, Locator(control_type="ListItem", name="Item 1")).name == "Item 1"
    import re

    matches = resolve_all(scope, Locator(control_type="ListItem", name=re.compile(r"^Item [12]$")))
    assert [m.name for m in matches][:2] == ["Item 1", "Item 2"]


def test_resolved_elements_read_live_values(scope: Scope, demo_process: DemoProcess) -> None:
    status = resolve(scope, Locator(automation_id="StatusText"))
    patterns.invoke(resolve(scope, Locator(control_type="Button", name="Sign in")))
    wait_for(lambda: status.name == "Invalid credentials")


def test_datagrid_row_and_cell(scope: Scope) -> None:
    grid = Locator(control_type="DataGrid")
    row = resolve(scope, grid.with_item(ItemSelector("row", 0)))
    print(f"row(0) -> {row.info().short()}")
    assert row.control_type == "DataItem"
    cell = resolve(scope, grid.with_item(ItemSelector("cell", 5, "Name")))
    assert cell.name == "Product 6"
    by_index = resolve(scope, grid.with_item(ItemSelector("cell", 5, 1)))
    assert by_index.same_as(cell)


def test_datagrid_item_errors(scope: Scope) -> None:
    grid = Locator(control_type="DataGrid")
    with pytest.raises(ElementNotFoundError, match=r"row=500 is out of range: .* has 200 rows"):
        resolve(scope, grid.with_item(ItemSelector("row", 500)))
    with pytest.raises(ElementNotFoundError, match=r'No column "Nope" .*columns: Id, Name, Qty'):
        resolve(scope, grid.with_item(ItemSelector("cell", 0, "Nope")))
    with pytest.raises(ElementNotFoundError, match="column=9 is out of range"):
        resolve(scope, grid.with_item(ItemSelector("cell", 0, 9)))


def test_note_dialog_by_window_locator(scope: Scope) -> None:
    patterns.invoke(resolve(scope, Locator(control_type="Button", name="Open dialog")))
    dialog = WindowLocator(title="WTK Demo - Dialog")
    wait_for(lambda: "WTK Demo - Dialog" in window_props(scope.app, "name"))
    save = resolve(scope, Locator(control_type="Button", name="Save", window=dialog))
    assert save.name == "Save"
    with pytest.raises(WindowNotFoundError) as exc_info:
        resolve(
            scope, Locator(control_type="Button", name="Save", window=WindowLocator(title="Foo"))
        )
    assert 'No window matches Window[title="Foo"] for DemoApp.exe (open windows: ' in str(
        exc_info.value
    )
    assert '"WTK Demo - Dialog"' in str(exc_info.value)
    cancel = resolve(scope, Locator(control_type="Button", name="Cancel", window=dialog))
    patterns.invoke(cancel)
    wait_for(lambda: "WTK Demo - Dialog" not in window_props(scope.app, "name"))


def test_message_box_ok_by_class(scope: Scope) -> None:
    patterns.invoke(resolve(scope, Locator(control_type="Button", name="Show message")))
    box = WindowLocator(class_name="#32770")
    wait_for(lambda: "#32770" in window_props(scope.app, "class_name"))
    ok = resolve(scope, Locator(control_type="Button", name="OK", window=box))
    assert ok.automation_id == "2"
    patterns.invoke(ok)
    wait_for(lambda: "#32770" not in window_props(scope.app, "class_name"))


def test_combo_item_after_expand(scope: Scope) -> None:
    combo_locator = Locator(automation_id="ColorCombo")
    combo = resolve(scope, combo_locator)
    patterns.expand(combo)
    wait_for(lambda: patterns.expand_state(combo).name == "Expanded")
    # Finding: WPF exposes each drop-down item twice inside the main window subtree - once as a
    # child of the ComboBox and once under a "Popup" window that UIA nests below the owner window.
    # So the popup fallback is not needed here and an unscoped locator is ambiguous.
    with pytest.raises(AmbiguousElementError) as exc_info:
        resolve(scope, Locator(control_type="ListItem", name="Blue"))
    assert exc_info.value.diagnostic.match_count == 2
    item = resolve(scope, Locator(control_type="ListItem", name="Blue", within=combo_locator))
    parent = item.parent()
    assert parent is not None
    assert parent.automation_id == "ColorCombo"
    patterns.collapse(combo)


def test_not_found_misspelled_name_lists_the_real_button(scope: Scope) -> None:
    with pytest.raises(ElementNotFoundError) as exc_info:
        resolve(scope, Locator(control_type="Button", name="Sign In"))
    diagnostic = exc_info.value.diagnostic
    assert diagnostic.candidates[0].info.name == "Sign in"
    assert str(exc_info.value) == (
        'No element matches Button[name="Sign In"] in Window "WTK Demo" '
        '(closest: Button "Sign in" — name differs)'
    )
    text = diagnostic.format()
    print(text)
    assert 'name: expected "Sign In", got "Sign in"' in text
    assert win32.window_text(0) == ""  # sanity: helper tolerates a null handle
