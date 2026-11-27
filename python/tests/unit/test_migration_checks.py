"""Property checks of a migrated suite: conditions, name mapping, checks, waits and soft errors."""

import re
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import finders, model, runtime, soft
from wintestkit.config import load_config
from wintestkit.engine import actions, conditions, pseudo, waits
from wintestkit.engine.diagnose import Diagnostic
from wintestkit.engine.locator import Locator
from wintestkit.engine.properties import AsText
from wintestkit.errors import AmbiguousElementError, ElementNotFoundError
from wintestkit.expect import expect
from wintestkit.model import Element, Page, Window


class OrdersPage(Page):
    window = Window(title="Orders")
    pending = Element(automation_id="PendingOrders")
    title = Element(automation_id="Title")


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        # A tick of at least a microsecond: floats near the end of a wait round a shorter sleep away.
        self.now += max(seconds, 1e-6)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeTime:
    fake = FakeTime()
    monkeypatch.setattr(waits, "_clock", fake.clock)
    monkeypatch.setattr(waits, "_sleep", fake.sleep)
    return fake


@pytest.fixture(autouse=True)
def steps(tmp_path: Path, clock: FakeTime) -> Generator[list[runtime.StepRecord]]:
    runtime.reset()
    soft.clear()
    runtime.set_config(load_config(tmp_path, {"timeout": 2.0}))
    records: list[runtime.StepRecord] = []
    runtime.add_step_listener(records.append)
    yield records
    soft.clear()
    runtime.reset()


class World:
    """The element the patched resolver finds (``None`` means none), and the values it reads."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.element: FakeElement | None = FakeElement(
            "List", "Pending orders", automation_id="PendingOrders"
        )
        self.managed: dict[str, Any] = {}
        self.text = "Order 1"
        self.items = ["Order 1", "Order 2", "Order 3"]
        self.children = 4
        self.resolves = 0
        self.script: list[Any] = []  # what each resolve does: an element, None or an exception
        monkeypatch.setattr(model, "resolve", self._resolve)
        monkeypatch.setattr(actions, "get_text", lambda el: self.text)
        monkeypatch.setattr(actions, "listed_item_names", lambda el: list(self.items))
        monkeypatch.setattr(actions, "combo_item_names", lambda el: list(self.items))
        monkeypatch.setattr(finders, "child_count_of", lambda bound: self.children)
        monkeypatch.setattr(pseudo, "read_property", self._read_property)

    def _resolve(self, scope: Any, locator: Locator) -> FakeElement:
        self.resolves += 1
        step = self.script.pop(0) if self.script else self.element
        if isinstance(step, BaseException):
            raise step
        if step is None:
            raise not_found()
        return step

    def _read_property(self, element: Any, name: str) -> Any:
        if name in self.managed:
            return self.managed[name]
        return element.get_property(name)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    return World(monkeypatch)


@pytest.fixture
def page() -> OrdersPage:
    return OrdersPage(FakeApp([FakeElement("Window", "Orders")]))  # type: ignore[arg-type]


def not_found() -> ElementNotFoundError:
    return ElementNotFoundError(
        Diagnostic(
            kind="not_found",
            message="No element matches",
            locator="x",
            searched_in="Window",
            match_count=0,
        )
    )


# -- conditions -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "condition"),
    [
        ("equal", "=="),
        ("Equal", "=="),
        ("==", "=="),
        ("notEqual", "!="),
        ("NOT_EQUAL", "!="),
        ("!=", "!="),
        ("contains", "contains"),
        ("notContains", "not contains"),
        ("not contains", "not contains"),
        ("lessOrEqual", "<="),
        ("less or equal", "<="),
        ("<=", "<="),
        ("greaterOrEqual", ">="),
        (">=", ">="),
        ("less", "<"),
        ("greater", ">"),
    ],
)
def test_condition_names_and_symbols(name: str, condition: str) -> None:
    assert conditions.parse_condition(name) == condition


def test_unknown_condition_lists_the_valid_ones() -> None:
    with pytest.raises(ValueError, match=r"unknown condition 'near'.*lessOrEqual"):
        conditions.parse_condition("near")


@pytest.mark.parametrize(
    ("actual", "expected", "condition", "result"),
    [
        (5, 5, "==", True),
        (5, 6, "==", False),
        (5, 6, "!=", True),
        ("a", "a", "==", True),
        (5, 6, "<", True),
        (6, 6, "<=", True),
        (7, 6, "<=", False),
        (6, 6, ">=", True),
        (5, 6, ">=", False),
        (7, 6, ">", True),
        ("10", 9, ">", True),  # numeric text is a number: 10 > 9
        (10, "9", ">", True),
        ("10", "9", ">=", True),
        ("2.50", 2.5, "<=", True),
        ("apple", "banana", "<", True),  # other text is ordered alphabetically
        ("Order 1", "Order", "contains", True),
        ("Order 1", "Item", "contains", False),
        ("Order 1", "Item", "not contains", True),
        (["Order 1", "Order 2"], "Order 2", "contains", True),
        (["Order 1", "Order 2"], "Order", "contains", False),
        ("Order 15", 15, "contains", True),
        (None, "x", "contains", False),
    ],
)
def test_compare(actual: Any, expected: Any, condition: Any, result: bool) -> None:
    assert conditions.compare(actual, expected, condition) is result


@pytest.mark.parametrize(
    ("actual", "expected", "result"),
    [(True, "True", True), (True, "true", True), (False, "True", False), (15, "15", True),
     (15.0, "15", True), ("15", "15", True), ("x", "y", False), (None, "x", False)],
)  # fmt: skip
def test_lenient_equality_compares_invariant_text(actual: Any, expected: Any, result: bool) -> None:
    assert conditions.compare(actual, expected, "==", lenient=True) is result
    assert conditions.compare(actual, expected, "!=", lenient=True) is not result


def test_strict_equality_keeps_the_types() -> None:
    assert not conditions.compare(True, "True", "==")
    assert conditions.compare(True, AsText("True"), "==")
    assert conditions.compare("Order 12", re.compile(r"Order \d+"), "==")


@pytest.mark.parametrize(
    ("actual", "expected"),
    [(None, 1), ("abc", 1), ([1], 1), (True, 1), (object(), "x")],
)
def test_values_that_cannot_be_ordered(actual: Any, expected: Any) -> None:
    with pytest.raises(conditions.ComparisonError):
        conditions.compare(actual, expected, "<=")


def test_contains_needs_something_to_look_in() -> None:
    with pytest.raises(conditions.ComparisonError):
        conditions.compare(5, 5, "contains")


# -- old property names ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "wpf", "other"),
    [
        ("WPFControlText", "wpf:Text", "name"),
        ("IsEnabled", "clr:IsEnabled", "enabled"),
        ("Enabled", "clr:IsEnabled", "enabled"),
        ("IsVisible", "clr:IsVisible", "visible_on_screen"),
        ("Visible", "clr:IsVisible", "visible_on_screen"),
        ("IsChecked", "clr:IsChecked", "checked"),
        ("Value", "clr:Value", "value"),
        ("Value.OleValue", "clr:Value", "value"),
    ],
)
def test_names_that_depend_on_the_kind_of_element(name: str, wpf: str, other: str) -> None:
    assert finders.map_property(name) == wpf
    assert finders.map_property(name, wpf=True) == wpf
    assert finders.map_property(name, wpf=False) == other


@pytest.mark.parametrize(
    ("name", "mapped"),
    [
        ("Exists", "exists"),
        ("exists", "exists"),
        ("VisibleOnScreen", "visible_on_screen"),
        ("wText", "text"),
        ("wItemList", "item_list"),
        ("wItemCount", "item_count"),
        ("ChildCount", "child_count"),
        ("WndCaption", "name"),
        ("WPFControlName", "AutomationId"),
        ("ControlId", "AutomationId"),
        ("WndClass", "ClassName"),
        ("ClrClassName", "type:Name"),
        ("ClrFullClassName", "type:FullName"),
        ("WPFControlOrdinalNo", "wpf:Ordinal"),
        ("Label", "clr:Label"),
        ("Count", "clr:Count"),
        ("SeriesCount", "clr:SeriesCount"),
        ("DataContext.Orders.Count", "clr:DataContext.Orders.Count"),
        ("DataContext.Total.OleValue", "clr:DataContext.Total"),
        ("Items.Item[0].Name", "clr:Items.Item[0].Name"),
        ("clr:Header", "clr:Header"),
        ("wpf:Text", "wpf:Text"),
        ("items", "items"),
    ],
)
def test_names_that_do_not_depend_on_the_element(name: str, mapped: str) -> None:
    assert finders.map_property(name) == mapped
    assert finders.map_property(name, wpf=False) == mapped


@pytest.mark.parametrize("bad", ["", "  ", "OleValue"])
def test_invalid_property_names(bad: str) -> None:
    with pytest.raises(ValueError):
        finders.map_property(bad)


# -- expect(...).to_have_property with conditions -------------------------------------------------


def test_property_condition_on_a_uia_property(page: OrdersPage, world: World) -> None:
    assert world.element is not None
    world.element.properties["HelpText"] = "12"
    expect(page.pending).to_have_property("HelpText", 12, op="<=")
    expect(page.pending).to_have_property("HelpText", "10", op=">=")
    expect(page.pending).to_have_property("HelpText", 13, op="!=")
    with pytest.raises(AssertionError, match="Expected: HelpText < 12"):
        expect(page.pending, timeout=0).to_have_property("HelpText", 12, op="<")


def test_property_condition_on_a_managed_property(page: OrdersPage, world: World) -> None:
    world.managed["clr:DataContext.Orders.Count"] = 3
    expect(page.pending).to_have_property("clr:DataContext.Orders.Count", 3)
    expect(page.pending).to_have_property("clr:DataContext.Orders.Count", 2, op="greaterOrEqual")
    expect(page.pending).to_have_property("clr:DataContext.Orders.Count", 5, op="lessOrEqual")
    with pytest.raises(AssertionError, match="Actual: 3"):
        expect(page.pending, timeout=0).to_have_property("clr:DataContext.Orders.Count", 4, op=">=")


def test_property_condition_on_the_wpf_text(page: OrdersPage, world: World) -> None:
    world.managed["wpf:Text"] = "Pending orders (3)"
    expect(page.pending).to_have_property("wpf:Text", "Pending", op="contains")
    expect(page.pending).to_have_property("wpf:Text", "Shipped", op="not contains")
    with pytest.raises(AssertionError, match='Expected: wpf:Text contains "Shipped"'):
        expect(page.pending, timeout=0).to_have_property("wpf:Text", "Shipped", op="contains")


def test_pseudo_properties_work_with_conditions(page: OrdersPage, world: World) -> None:
    expect(page.pending).to_have_property("exists", True)
    expect(page.pending).to_have_property("visible_on_screen", True)
    expect(page.pending).to_have_property("item_count", 3)
    expect(page.pending).to_have_property("item_count", 4, op="<=")
    expect(page.pending).to_have_property("items", ["Order 1", "Order 2", "Order 3"])
    expect(page.pending).to_have_property("items", "Order 2", op="contains")
    expect(page.pending).to_have_property("item_list", "Order 3", op="contains")
    expect(page.pending).to_have_property("child_count", 4)
    expect(page.pending).to_have_property("text", "Order 1")
    expect(page.pending).to_have_property("name", "Pending orders")
    expect(page.pending).to_have_property("enabled", True)


def test_a_missing_element_fails_every_property_but_exists(page: OrdersPage, world: World) -> None:
    world.element = None
    expect(page.pending).to_have_property("exists", False)
    expect(page.pending).to_have_property("visible_on_screen", False)
    with pytest.raises(AssertionError, match="element not found"):
        expect(page.pending, timeout=0).to_have_property("item_count", 0)


def test_negated_property_conditions(page: OrdersPage, world: World) -> None:
    world.managed["clr:Total"] = 10
    expect(page.pending).not_.to_have_property("clr:Total", 10, op="<")
    expect(page.pending).not_.to_have_property("clr:Total", 11, op="==")


def test_property_failure_is_recorded_with_expected_actual_and_condition(
    page: OrdersPage, world: World, steps: list[runtime.StepRecord]
) -> None:
    world.managed["clr:Total"] = 10
    with pytest.raises(AssertionError) as failure:
        expect(page.pending, timeout=0).to_have_property("clr:Total", 5, op="<=")
    assert "Expected: clr:Total <= 5" in str(failure.value)
    assert "Actual: 10" in str(failure.value)
    record = steps[-1]
    assert record.status == "failed"
    assert record.args == {"name": "clr:Total", "condition": "<=", "expected": 5}


def test_unorderable_values_fail_with_a_reason(page: OrdersPage, world: World) -> None:
    world.managed["clr:Title"] = "abc"
    with pytest.raises(AssertionError, match="cannot be ordered"):
        expect(page.pending, timeout=0).to_have_property("clr:Title", 5, op="<=")


def test_unknown_condition_is_a_programming_error(page: OrdersPage, world: World) -> None:
    with pytest.raises(ValueError, match="unknown condition"):
        expect(page.pending).to_have_property("exists", True, op="near")


# -- check_property -------------------------------------------------------------------------------


def test_check_property_passes_and_returns_true(page: OrdersPage, world: World) -> None:
    world.managed["wpf:Text"] = "Pending orders"
    world.managed["clr:IsEnabled"] = True
    world.managed["clr:IsVisible"] = True
    world.managed["clr:IsChecked"] = False
    world.managed["clr:Value"] = "7"
    world.managed["clr:Count"] = 3
    world.managed["clr:Label"] = "Orders"
    world.managed["clr:SeriesCount"] = 2
    world.managed["clr:DataContext.Orders.Count"] = 3
    check = finders.check_property
    bound = page.pending
    assert check(bound, "WPFControlText", "equal", "Pending orders")
    assert check(bound, "WPFControlText", "contains", "Pending")
    assert check(bound, "IsEnabled", "equal", "True")
    assert check(bound, "Enabled", "equal", True)
    assert check(bound, "Value.OleValue", "equal", 7)
    assert check(bound, "IsVisible", "equal", True)
    assert check(bound, "Visible", "notEqual", False)
    assert check(bound, "VisibleOnScreen", "equal", True)
    assert check(bound, "IsChecked", "equal", "False")
    assert check(bound, "Exists", "equal", True)
    assert check(bound, "Value", "greaterOrEqual", "7")
    assert check(bound, "Label", "equal", "Orders")
    assert check(bound, "Count", "lessOrEqual", 3)
    assert check(bound, "SeriesCount", "equal", "2")
    assert check(bound, "wText", "equal", "Order 1")
    assert check(bound, "wItemList", "contains", "Order 2")
    assert check(bound, "wItemCount", "equal", 3)
    assert check(bound, "ChildCount", "equal", 4)
    assert check(bound, "WndCaption", "equal", "Pending orders")
    assert check(bound, "DataContext.Orders.Count", "greaterOrEqual", 1)


@pytest.mark.parametrize(
    ("prop", "condition", "value", "passes"),
    [
        ("wItemCount", "equal", 3, True),
        ("wItemCount", "equal", "3", True),
        ("wItemCount", "notEqual", 3, False),
        ("wItemCount", "notEqual", 4, True),
        ("wItemCount", "lessOrEqual", 3, True),
        ("wItemCount", "lessOrEqual", 2, False),
        ("wItemCount", "greaterOrEqual", 3, True),
        ("wItemCount", "greaterOrEqual", 4, False),
        ("wItemList", "contains", "Order 3", True),
        ("wItemList", "contains", "Order 4", False),
        ("wText", "contains", "Order", True),
        ("wText", "equal", "Order 2", False),
    ],
)
def test_check_property_conditions(
    page: OrdersPage, world: World, prop: str, condition: str, value: Any, passes: bool
) -> None:
    assert (
        finders.check_property(page.pending, prop, condition, value, timeout=0, soft=True) is passes
    )


def test_a_failed_check_is_a_failed_step_like_a_failed_expect(
    page: OrdersPage, world: World, steps: list[runtime.StepRecord]
) -> None:
    with pytest.raises(AssertionError) as failure:
        finders.check_property(page.pending, "wItemCount", "greaterOrEqual", 5, timeout=0)
    message = str(failure.value)
    assert "Expected: wItemCount >= 5" in message
    assert "Actual: 3" in message
    record = steps[-1]
    assert record.action == "expect.to_have_property"
    assert record.status == "failed"
    assert record.args == {"name": "wItemCount", "condition": ">=", "expected": 5}
    assert record.error is not None and "Actual: 3" in record.error["message"]


def test_a_soft_check_records_the_error_and_the_test_goes_on(
    page: OrdersPage, world: World, steps: list[runtime.StepRecord]
) -> None:
    assert (
        finders.check_property(page.pending, "wItemCount", "equal", 9, timeout=0, soft=True)
        is False
    )
    assert finders.check_property(page.pending, "wItemCount", "equal", 3, timeout=0, soft=True)
    (error,) = soft.errors()
    assert error.source == "expect"
    assert "Expected: wItemCount = 9" in error.message and "Actual: 3" in error.message
    assert [step.status for step in steps] == ["failed", "passed"]  # both are in the report


def test_a_whole_block_of_checks_can_be_soft(page: OrdersPage, world: World) -> None:
    with soft.continue_on_error():
        assert finders.check_property(page.pending, "wItemCount", "equal", 1, timeout=0) is False
        assert finders.check_property(page.pending, "ChildCount", "equal", 9, timeout=0) is False
        expect(page.pending, timeout=0).to_have_property("item_count", 2)
    assert len(soft.errors()) == 3
    with pytest.raises(AssertionError):  # outside the block they raise again
        finders.check_property(page.pending, "wItemCount", "equal", 1, timeout=0)


def test_exists_and_visibility_checks_of_a_missing_element(page: OrdersPage, world: World) -> None:
    world.element = None
    assert finders.check_property(page.pending, "Exists", "equal", False, timeout=0)
    assert finders.check_property(page.pending, "Exists", "equal", "False", timeout=0)
    assert finders.check_property(page.pending, "VisibleOnScreen", "equal", False, timeout=0)
    assert not finders.check_property(page.pending, "Exists", "equal", True, timeout=0, soft=True)
    with pytest.raises(AssertionError, match="element not found"):
        finders.check_property(page.pending, "wItemCount", "equal", 0, timeout=0)


def test_a_check_waits_for_the_property(
    page: OrdersPage, world: World, clock: FakeTime, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = iter([1, 2, 3])
    monkeypatch.setattr(pseudo, "read_property", lambda element, name: next(values))
    assert finders.check_property(page.pending, "Count", "equal", 3)
    assert clock.now == pytest.approx(0.2)


def test_check_property_on_an_element_that_is_not_wpf(page: OrdersPage, world: World) -> None:
    assert world.element is not None
    world.element.framework_id = "Win32"
    world.element.name = "Pending orders"
    world.element.is_enabled = True
    world.element.properties["HelpText"] = "tip"
    assert finders.check_property(page.pending, "WPFControlText", "equal", "Pending orders")
    assert finders.check_property(page.pending, "Enabled", "equal", True)
    assert finders.check_property(page.pending, "VisibleOnScreen", "equal", True)
    assert finders.check_property(page.pending, "HelpText", "equal", "tip")


def test_a_window_can_be_checked(world: World, page: OrdersPage) -> None:
    assert finders.check_property(page.window, "Exists", "equal", True, timeout=0)
    assert finders.check_property(page.window, "WndCaption", "equal", "Orders", timeout=0)


# -- wait_property --------------------------------------------------------------------------------


def test_wait_property_returns_true_at_once(
    page: OrdersPage, world: World, clock: FakeTime, steps: list[runtime.StepRecord]
) -> None:
    assert finders.wait_property(page.pending, "wItemCount", 3, 5000) is True
    assert clock.now == 0
    record = steps[-1]
    assert record.action == "wait_property" and record.status == "passed"
    assert record.args["matched"] is True


def test_wait_property_returns_false_on_timeout_and_never_raises(
    page: OrdersPage, world: World, clock: FakeTime, steps: list[runtime.StepRecord]
) -> None:
    assert finders.wait_property(page.pending, "wItemCount", 99, 1500) is False
    assert clock.now == pytest.approx(1.5, abs=0.2)
    record = steps[-1]
    assert record.status == "passed"  # the suite decides what False means
    assert record.args["matched"] is False and record.args["last"] == 3
    assert record.args["timeout_ms"] == 1500


def test_wait_property_sees_a_value_that_changes(
    page: OrdersPage, world: World, clock: FakeTime, monkeypatch: pytest.MonkeyPatch
) -> None:
    counts = [1, 1, 2, 3]

    def read(element: Any, name: str) -> Any:
        return counts.pop(0) if len(counts) > 1 else counts[0]

    monkeypatch.setattr(pseudo, "read_property", read)
    assert finders.wait_property(page.pending, "Count", 3, 10_000) is True
    assert 0 < clock.now < 1


def test_wait_for_an_element_to_appear(page: OrdersPage, world: World, clock: FakeTime) -> None:
    world.script = [None, None, None]
    assert finders.wait_property(page.pending, "Exists", True, 5000) is True
    assert world.resolves == 4
    assert clock.now == pytest.approx(0.3)


def test_wait_for_an_element_to_disappear(page: OrdersPage, world: World, clock: FakeTime) -> None:
    world.script = [world.element, world.element, None]
    world.element = None  # what the lookups after the script find
    assert finders.wait_property(page.pending, "Exists", False, 5000) is True
    assert clock.now == pytest.approx(0.2)


def test_wait_for_disappearance_times_out_while_it_is_there(
    page: OrdersPage, world: World, clock: FakeTime
) -> None:
    assert finders.wait_property(page.pending, "Exists", False, 1000) is False
    assert clock.now == pytest.approx(1.0, abs=0.2)


def test_exists_counts_several_matches_as_existing(page: OrdersPage, world: World) -> None:
    from wintestkit.engine.diagnose import Diagnostic

    world.script = [
        AmbiguousElementError(
            Diagnostic(
                kind="ambiguous",
                message="2 elements match",
                locator="x",
                searched_in="Window",
                match_count=2,
            )
        )
    ]
    assert finders.wait_property(page.pending, "Exists", True, 0) is True


def test_other_properties_wait_for_the_element_to_exist(
    page: OrdersPage, world: World, clock: FakeTime
) -> None:
    world.script = [None, None]
    assert finders.wait_property(page.pending, "wItemCount", 3, 5000) is True
    assert clock.now == pytest.approx(0.2)
    world.element = None
    assert finders.wait_property(page.pending, "wItemCount", 3, 500) is False


@pytest.mark.parametrize(
    ("prop", "value"),
    [("Enabled", True), ("VisibleOnScreen", True), ("Visible", "True")],
)
def test_waits_for_state_properties(page: OrdersPage, world: World, prop: str, value: Any) -> None:
    world.managed["clr:IsEnabled"] = True
    world.managed["clr:IsVisible"] = True
    assert finders.wait_property(page.pending, prop, value, 1000) is True


def test_wait_property_accepts_a_condition_and_very_long_timeouts(
    page: OrdersPage, world: World, clock: FakeTime
) -> None:
    assert finders.wait_property(page.pending, "wItemCount", 99, 600_000, condition="less") is True
    assert finders.wait_property(page.pending, "wItemCount", 1, 600_000, condition="less") is False
    assert clock.now == pytest.approx(600.0, abs=1.0)  # the whole budget, never more


def test_wait_property_without_a_timeout_uses_the_default(
    page: OrdersPage, world: World, clock: FakeTime
) -> None:
    assert finders.wait_property(page.pending, "wItemCount", 99) is False
    assert clock.now == pytest.approx(2.0, abs=0.2)


def test_wait_property_rejects_unknown_conditions_and_names(page: OrdersPage, world: World) -> None:
    with pytest.raises(ValueError, match="unknown condition"):
        finders.wait_property(page.pending, "Exists", True, 10, condition="near")
    with pytest.raises(ValueError, match="invalid property name"):
        finders.wait_property(page.pending, "", True, 10)


def test_wait_property_redacts_a_password(
    page: OrdersPage, world: World, steps: list[runtime.StepRecord]
) -> None:
    assert world.element is not None
    world.element.properties["IsPassword"] = True
    world.element.class_name = "PasswordBox"
    assert not finders.wait_property(page.pending, "wText", "hunter2", 0)
    assert "hunter2" not in str(steps[-1].to_dict())
