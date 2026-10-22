"""Unit tests for the Page / Element model (resolver and actions are patched out)."""

import re
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeApp, FakeElement

from wintestkit import model, runtime
from wintestkit.config import load_config
from wintestkit.engine import actions, waits
from wintestkit.engine.diagnose import Diagnostic
from wintestkit.engine.locator import ItemSelector, Locator, WindowLocator
from wintestkit.errors import (
    ActionError,
    ElementNotFoundError,
    UIAError,
    WaitTimeoutError,
)
from wintestkit.model import (
    BoundElement,
    BoundElements,
    BoundWindow,
    Element,
    Elements,
    Page,
    Window,
)

SOURCE_LINE = 0


class MainPage(Page):
    window = Window(title="WTK Demo")

    credentials = Element(control_type="Group", name="Credentials")
    username = Element(control_type="Edit", class_name="TextBox", within=credentials)
    password = Element(control_type="Edit", class_name="PasswordBox", within=credentials)
    sign_in = Element(control_type="Button", name="Sign in")
    status = Element(automation_id="StatusText", timeout=3.0)
    oks = Elements(control_type="Button", name="OK")
    panel_b_ok = Element(
        control_type="Button",
        name="OK",
        within=Element(control_type="Group", name="Panel B", window=Window(title="ignored")),
    )
    products = Element(control_type="DataGrid")
    dialog_button = Element(
        control_type="Button", name="Save", window=Window(title="WTK Demo - Dialog")
    )


class ExtendedPage(MainPage):
    extra = Element(control_type="Text", name="Extra")
    sign_in = Element(control_type="Button", name="Sign in (extended)")


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def runtime_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[runtime.StepRecord]:
    runtime.reset()
    runtime.set_config(load_config(tmp_path, {"timeout": 10.0}))
    fake = FakeTime()
    monkeypatch.setattr(waits, "_clock", fake.clock)
    monkeypatch.setattr(waits, "_sleep", fake.sleep)
    records: list[runtime.StepRecord] = []
    runtime.add_step_listener(records.append)
    yield records  # type: ignore[misc]
    runtime.reset()


@pytest.fixture
def page() -> MainPage:
    window = FakeElement("Window", "WTK Demo")
    return MainPage(FakeApp([window]))  # type: ignore[arg-type]


class Recorder:
    """Patches the resolver to return a fake element and records what was asked."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.element = FakeElement("Button", "Sign in", class_name="Button")
        self.calls: list[tuple[Any, Locator]] = []
        self.all_result: list[FakeElement] = []
        self.error: BaseException | None = None
        monkeypatch.setattr(model, "resolve", self._resolve)
        monkeypatch.setattr(model, "resolve_all", self._resolve_all)

    def _resolve(self, scope: Any, locator: Locator) -> FakeElement:
        self.calls.append((scope, locator))
        if self.error is not None:
            raise self.error
        return self.element

    def _resolve_all(self, scope: Any, locator: Locator) -> list[FakeElement]:
        self.calls.append((scope, locator))
        return self.all_result


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    return Recorder(monkeypatch)


def not_found(message: str = "No element matches") -> ElementNotFoundError:
    return ElementNotFoundError(
        Diagnostic(
            kind="not_found",
            message=message,
            locator="x",
            searched_in="Window",
            match_count=0,
        )
    )


# -- descriptors ----------------------------------------------------------------------------------


def test_class_access_returns_definitions_and_instance_access_binds(page: MainPage) -> None:
    assert isinstance(MainPage.sign_in, Element)
    assert isinstance(MainPage.oks, Elements)
    assert isinstance(MainPage.window, Window)
    assert isinstance(page.sign_in, BoundElement)
    assert isinstance(page.oks, BoundElements)
    assert isinstance(page.window, BoundWindow)
    assert page.sign_in.definition is MainPage.sign_in
    assert page.sign_in.page is page


def test_page_without_window_attribute_has_none() -> None:
    class Plain(Page):
        button = Element(control_type="Button")

    assert Plain.window is None
    assert Plain(FakeApp([])).window is None  # type: ignore[arg-type]


def test_names_owner_and_qualname() -> None:
    definition = MainPage.sign_in
    assert definition.name == "sign_in"
    assert definition.owner is MainPage
    assert definition.qualname == "MainPage.sign_in"
    assert MainPage.window.qualname == "MainPage.window"  # type: ignore[union-attr]
    assert Element(name="x").qualname == "<anonymous>"


def test_inherited_element_keeps_its_defining_owner() -> None:
    assert ExtendedPage.username.qualname == "MainPage.username"
    assert ExtendedPage.extra.qualname == "ExtendedPage.extra"


def test_source_captures_the_definition_line() -> None:
    line = 0
    for number, text in enumerate(Path(__file__).read_text(encoding="utf-8").splitlines(), 1):
        if text.strip().startswith('sign_in = Element(control_type="Button", name="Sign in")'):
            line = number
            break
    assert MainPage.sign_in.source == (__file__, line)
    assert MainPage.window.source is not None  # type: ignore[union-attr]
    assert MainPage.window.source[0] == __file__  # type: ignore[union-attr]


def test_repr_forms(page: MainPage) -> None:
    assert repr(page.sign_in) == '<BoundElement MainPage.sign_in Button[name="Sign in"]>'
    assert repr(page.oks) == '<BoundElements MainPage.oks Button[name="OK"]>'
    assert repr(MainPage.sign_in) == '<Element MainPage.sign_in Button[name="Sign in"]>'
    assert repr(page.window) == '<BoundWindow MainPage.window Window[title="WTK Demo"]>'


# -- locator building -----------------------------------------------------------------------------


def test_locator_is_built_with_within_chain() -> None:
    locator = MainPage.password.locator()
    assert locator.describe() == 'Group[name="Credentials"] > Edit[class="PasswordBox"]'
    assert [link.control_type for link in locator.chain()] == ["Group", "Edit"]


def test_within_window_is_ignored_and_own_window_overrides() -> None:
    assert MainPage.panel_b_ok.locator().window is None
    assert MainPage.panel_b_ok.locator().describe() == ('Group[name="Panel B"] > Button[name="OK"]')
    assert MainPage.dialog_button.locator().window == WindowLocator(title="WTK Demo - Dialog")


def test_elements_locator_has_no_index() -> None:
    assert MainPage.oks.locator().index is None
    with pytest.raises(TypeError):
        Elements(control_type="Button", index=1)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("kwargs", "exception", "match"),
    [
        ({"control_type": "Buton", "name": "x"}, ValueError, "valid names"),
        ({}, ValueError, "at least one property"),
        ({"name": "x", "index": -1}, ValueError, "index"),
        ({"name": "x", "depth": 0}, ValueError, "depth"),
        ({"name": "x", "timeout": -1}, ValueError, "timeout"),
        ({"name": "x", "within": object()}, TypeError, "within"),
        ({"name": "x", "within": Elements(name="y")}, TypeError, "within"),
        ({"name": "x", "window": "WTK Demo"}, TypeError, "window"),
    ],
)
def test_definition_time_validation(
    kwargs: dict[str, Any], exception: type[Exception], match: str
) -> None:
    with pytest.raises(exception, match=match):
        Element(**kwargs)


def test_index_only_element_is_allowed() -> None:
    assert Element(control_type="Button", index=0).locator().index == 0
    assert Element(index=2).locator().describe() == "*[index=2]"


def test_regex_matchers_are_accepted() -> None:
    element = Element(name=re.compile("^Item"), control_type="ListItem")
    assert element.locator().describe() == "ListItem[name=/^Item/]"


def test_window_validation() -> None:
    with pytest.raises(ValueError, match="window index"):
        Window(index=-1)
    assert Window(title="x", process="p.exe").locator == WindowLocator(title="x", process="p.exe")


# -- pages --------------------------------------------------------------------------------------


def test_page_elements_order_and_overrides() -> None:
    names = list(MainPage.elements())
    assert names[:4] == ["credentials", "username", "password", "sign_in"]
    extended = ExtendedPage.elements()
    assert list(extended)[-1] == "extra"
    assert list(extended).index("sign_in") == 3  # keeps its original position
    assert extended["sign_in"].locator().name == "Sign in (extended)"
    assert "window" not in extended


def test_scope_uses_the_page_window(page: MainPage, recorder: Recorder) -> None:
    page.sign_in.resolve()
    scope, locator = recorder.calls[-1]
    assert scope.app is page.app
    assert scope.window == WindowLocator(title="WTK Demo")
    assert locator.describe() == 'Button[name="Sign in"]'


def test_scope_without_window_is_none(recorder: Recorder) -> None:
    class Plain(Page):
        button = Element(control_type="Button")

    Plain(FakeApp([])).button.resolve()  # type: ignore[arg-type]
    assert recorder.calls[-1][0].window is None


def test_page_check_reports_each_element(page: MainPage, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_resolve(scope: Any, locator: Locator) -> FakeElement:
        if locator.name == "Sign in":
            raise not_found('No element matches Button[name="Sign in"]')
        return FakeElement("Button", "x")

    monkeypatch.setattr(model, "resolve", fake_resolve)
    monkeypatch.setattr(model, "resolve_all", lambda scope, locator: [])
    results = page.check()
    assert set(results) == set(MainPage.elements())
    assert isinstance(results["sign_in"], ElementNotFoundError)
    assert results["username"] is None
    assert results["oks"] is None


# -- actions: steps, waits, timeouts --------------------------------------------------------------


def test_click_emits_a_step(
    page: MainPage,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
    runtime_setup: list[runtime.StepRecord],
) -> None:
    seen: dict[str, Any] = {}

    def fake_click(element: Any, *, mode: str, button: str = "left") -> str:
        seen["mode"] = mode
        return "invoke"

    monkeypatch.setattr(actions, "click", fake_click)
    page.sign_in.click()
    assert seen["mode"] == "pattern"
    (record,) = runtime_setup
    assert record.action == "click"
    assert record.target == "MainPage.sign_in"
    assert record.locator == 'Button[name="Sign in"]'
    assert record.args == {"mode": "pattern", "strategy": "invoke"}
    assert record.status == "passed"


def test_click_mode_comes_from_the_call_or_config(
    page: MainPage, recorder: Recorder, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    modes: list[str] = []
    monkeypatch.setattr(
        actions, "click", lambda el, *, mode, button="left": modes.append(mode) or "x"
    )
    page.sign_in.click(mode="mouse")
    runtime.set_config(load_config(tmp_path, {"input_mode": "mouse"}))
    page.sign_in.click()
    assert modes == ["mouse", "mouse"]


def test_type_redacts_password_input(
    page: MainPage,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
    runtime_setup: list[runtime.StepRecord],
) -> None:
    monkeypatch.setattr(actions, "type_text", lambda el, text, *, clear, keys: "value")
    page.username.type("admin")
    page.password.type("hunter2", clear=False)
    username, password = runtime_setup
    assert username.args == {"text": "admin", "clear": True, "keys": False, "strategy": "value"}
    assert password.args == {"text": "***", "clear": "***", "keys": "***", "strategy": "value"}
    assert "hunter2" not in str([r.to_dict() for r in runtime_setup])


def test_failed_action_records_the_error(
    page: MainPage,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
    runtime_setup: list[runtime.StepRecord],
) -> None:
    def boom(element: Any) -> None:
        raise ActionError("cannot hover")

    monkeypatch.setattr(actions, "hover", boom)
    with pytest.raises(ActionError):
        page.sign_in.hover()
    assert runtime_setup[0].status == "failed"
    assert runtime_setup[0].error == {"type": "ActionError", "message": "cannot hover"}


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("method", ["type", "press"])
def test_id_only_password_and_explicit_secret_hide_input_and_provider_errors(
    page: MainPage,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
    runtime_setup: list[runtime.StepRecord],
    explicit: bool,
    method: str,
) -> None:
    recorder.element.properties["IsPassword"] = not explicit
    sentinel = "PRIVATE_INPUT_SENTINEL"

    def fail(*args: Any, **kwargs: Any) -> None:
        raise ActionError(f"provider rejected {sentinel}")

    monkeypatch.setattr(actions, "type_text" if method == "type" else "press", fail)
    with pytest.raises(ActionError) as failure:
        getattr(page.status, method)(sentinel, secret=explicit)
    assert sentinel not in str(failure.value)
    assert sentinel not in str([record.to_dict() for record in runtime_setup])
    assert runtime_setup[-1].status == "failed"


def test_id_only_password_success_is_redacted(
    page: MainPage,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
    runtime_setup: list[runtime.StepRecord],
) -> None:
    recorder.element.properties["IsPassword"] = True
    monkeypatch.setattr(actions, "type_text", lambda *args, **kwargs: "value")
    page.status.type("PRIVATE_INPUT_SENTINEL")
    assert runtime_setup[-1].args["text"] == runtime.REDACTED
    assert "PRIVATE_INPUT_SENTINEL" not in str(runtime_setup[-1].to_dict())


@pytest.mark.parametrize(
    ("method", "args", "action"),
    [
        ("double_click", (), "double_click"),
        ("right_click", (), "right_click"),
        ("clear", (), "clear"),
        ("expand", (), "expand"),
        ("collapse", (), "collapse"),
        ("focus", (), "focus"),
        ("press", ("Ctrl+S",), "press"),
        ("select", ("Blue",), "select"),
        ("check", (), "check"),
        ("uncheck", (), "uncheck"),
    ],
)
def test_every_action_emits_a_step_and_calls_the_engine(
    page: MainPage,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
    runtime_setup: list[runtime.StepRecord],
    method: str,
    args: tuple[Any, ...],
    action: str,
) -> None:
    called: list[str] = []
    for name in (
        "double_click",
        "right_click",
        "clear",
        "expand",
        "collapse",
        "focus",
        "press",
        "select",
        "set_checked",
    ):
        monkeypatch.setattr(actions, name, lambda *a, _n=name, **k: called.append(_n))
    getattr(page.sign_in, method)(*args)
    assert called  # the engine function ran
    assert runtime_setup[0].action == action


def test_actions_wait_for_enabled(
    page: MainPage, recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder.element.is_enabled = False
    polls = [0]
    original = recorder._resolve

    def resolve(scope: Any, locator: Locator) -> FakeElement:
        polls[0] += 1
        if polls[0] == 4:
            recorder.element.is_enabled = True
        return original(scope, locator)

    monkeypatch.setattr(model, "resolve", resolve)
    monkeypatch.setattr(actions, "click", lambda el, *, mode, button="left": "invoke")
    page.sign_in.click()
    assert polls[0] == 4


def test_actions_time_out_naming_the_unmet_state(
    page: MainPage, recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder.element.is_enabled = False
    monkeypatch.setattr(actions, "click", lambda el, *, mode, button="left": "invoke")
    with pytest.raises(WaitTimeoutError) as exc_info:
        page.sign_in.click(timeout=2)
    assert str(exc_info.value) == (
        'Timed out after 2.0s waiting for MainPage.sign_in Button[name="Sign in"] to be enabled'
    )


def test_offpage_elements_wait_for_visibility_unless_scrollable(
    page: MainPage, recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder.element.is_offscreen = True
    monkeypatch.setattr(model.patterns, "has_pattern", lambda el, name: False)
    monkeypatch.setattr(actions, "click", lambda el, *, mode, button="left": "invoke")
    with pytest.raises(WaitTimeoutError, match="to be visible"):
        page.sign_in.click(timeout=1)
    monkeypatch.setattr(model.patterns, "has_pattern", lambda el, name: name == "ScrollItem")
    page.sign_in.click(timeout=1)  # scrollable: ensure_visible handles it


def test_timeout_precedence(page: MainPage, recorder: Recorder) -> None:
    recorder.error = not_found()
    with pytest.raises(ElementNotFoundError, match=r"waited 5\.0s"):
        page.sign_in.resolve(timeout=5)  # per call wins
    with pytest.raises(ElementNotFoundError, match=r"waited 3\.0s"):
        page.status.resolve()  # Element(timeout=3.0) beats config
    with pytest.raises(ElementNotFoundError, match=r"waited 10\.0s"):
        page.sign_in.resolve()  # falls back to config


def test_resolve_error_message_carries_the_diagnostic(page: MainPage, recorder: Recorder) -> None:
    recorder.error = not_found('No element matches Button[name="Sign in"] in Window "WTK Demo"')
    with pytest.raises(ElementNotFoundError) as exc_info:
        page.sign_in.resolve(timeout=0)
    assert str(exc_info.value) == (
        'No element matches Button[name="Sign in"] in Window "WTK Demo" (waited 0.0s)'
    )


def test_element_gone_mid_action_is_retried_once(
    page: MainPage, recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = [0]

    def flaky(element: Any) -> None:
        attempts[0] += 1
        if attempts[0] == 1:
            raise UIAError("gone", element_gone=True)

    monkeypatch.setattr(actions, "double_click", flaky)
    page.sign_in.double_click()
    assert attempts[0] == 2
    assert len(recorder.calls) == 2  # resolved again before the retry


def test_element_gone_twice_raises(
    page: MainPage, recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    def always(element: Any) -> None:
        raise UIAError("gone", element_gone=True)

    monkeypatch.setattr(actions, "double_click", always)
    with pytest.raises(UIAError):
        page.sign_in.double_click()


def test_other_uia_errors_are_not_retried(
    page: MainPage, recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = [0]

    def failing(element: Any) -> None:
        attempts[0] += 1
        raise UIAError("com failure")

    monkeypatch.setattr(actions, "double_click", failing)
    with pytest.raises(UIAError):
        page.sign_in.double_click()
    assert attempts[0] == 1


# -- reads and queries ----------------------------------------------------------------------------


def test_reads_resolve_and_read(
    page: MainPage, recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(actions, "get_text", lambda el: "text!")
    monkeypatch.setattr(actions, "get_value", lambda el: "value!")
    monkeypatch.setattr(actions, "is_checked", lambda el: True)
    monkeypatch.setattr(actions, "selected_items", lambda el: ["a"])
    assert page.status.text == "text!"
    assert page.status.value == "value!"
    assert page.status.is_checked() is True
    assert page.status.selected_items() == ["a"]
    assert page.status.is_enabled() is True
    assert page.status.info().name == "Sign in"


def test_exists_and_is_visible_do_not_raise(page: MainPage, recorder: Recorder) -> None:
    assert page.sign_in.exists() is True
    assert page.sign_in.is_visible() is True
    recorder.element.is_offscreen = True
    assert page.sign_in.is_visible() is False
    recorder.error = not_found()
    assert page.sign_in.exists() is False
    assert page.sign_in.is_visible() is False
    assert page.sign_in.exists(timeout=1) is False


def test_exists_waits_for_the_element(
    page: MainPage, recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    polls = [0]
    original = recorder._resolve

    def appears_later(scope: Any, locator: Locator) -> FakeElement:
        polls[0] += 1
        if polls[0] < 3:
            raise not_found()
        return original(scope, locator)

    monkeypatch.setattr(model, "resolve", appears_later)
    assert page.sign_in.exists(timeout=5) is True
    assert polls[0] == 3


def test_wait_for_returns_self(page: MainPage, recorder: Recorder) -> None:
    bound = page.sign_in
    assert bound.wait_for("enabled") is bound
    assert bound.wait_for("visible", timeout=1) is bound


# -- derivation -----------------------------------------------------------------------------------


def test_nth_row_and_cell_derive_locators(page: MainPage) -> None:
    assert page.sign_in.nth(2).locator.index == 2
    assert page.sign_in.locator.index is None  # the original is untouched
    assert page.products.row(3).locator.item == ItemSelector("row", 3)
    assert page.products.cell(5, "Name").locator.item == ItemSelector("cell", 5, "Name")
    assert page.products.row(3).locator.describe() == "DataGrid > row(3)"
    assert page.products.cell(5, "Name").qualname == "MainPage.products"


def test_derived_elements_resolve_with_their_own_locator(
    page: MainPage, recorder: Recorder
) -> None:
    page.products.cell(1, 2).resolve()
    assert recorder.calls[-1][1].item == ItemSelector("cell", 1, 2)


# -- collections ----------------------------------------------------------------------------------


def test_collections(page: MainPage, recorder: Recorder, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder.all_result = [FakeElement("Button", "OK"), FakeElement("Button", "OK")]
    monkeypatch.setattr(actions, "get_text", lambda el: f"text-{el.runtime_id}")
    oks = page.oks
    assert oks.count() == 2
    assert len(oks) == 2
    assert oks.first().locator.index == 0
    assert oks.last().locator.index == 1
    assert [b.locator.index for b in oks.all()] == [0, 1]
    assert [b.locator.index for b in oks] == [0, 1]
    assert oks.texts() == [f"text-{e.runtime_id}" for e in recorder.all_result]


def test_empty_collection(page: MainPage, recorder: Recorder) -> None:
    assert page.oks.count() == 0
    assert page.oks.count(timeout=2) == 0
    assert page.oks.all() == []
    with pytest.raises(ActionError, match="no last"):
        page.oks.last()


def test_collection_count_waits_for_first_match(
    page: MainPage, monkeypatch: pytest.MonkeyPatch
) -> None:
    polls = [0]

    def later(scope: Any, locator: Locator) -> list[FakeElement]:
        polls[0] += 1
        return [FakeElement("Button", "OK")] if polls[0] >= 3 else []

    monkeypatch.setattr(model, "resolve_all", later)
    assert page.oks.count(timeout=5) == 1
    assert polls[0] == 3


def test_filter_narrows_the_locator(page: MainPage, recorder: Recorder) -> None:
    narrowed = page.oks.filter(class_name="Button", automation_id=re.compile("^ok"))
    assert narrowed.locator.describe() == 'Button[id=/^ok/, name="OK", class="Button"]'
    assert page.oks.locator.class_name is None  # original untouched
    narrowed.count()
    assert recorder.calls[-1][1] == narrowed.locator


# -- windows --------------------------------------------------------------------------------------


def test_bound_window_operations(
    page: MainPage, monkeypatch: pytest.MonkeyPatch, runtime_setup: list[runtime.StepRecord]
) -> None:
    dialog = FakeElement("Window", "WTK Demo")
    monkeypatch.setattr(model, "resolve_window", lambda app, wl: dialog)
    states: list[str] = []
    monkeypatch.setattr(model.patterns, "window_set_state", lambda el, state: states.append(state))
    closed: list[Any] = []
    monkeypatch.setattr(model.patterns, "window_close", closed.append)
    window = page.window
    assert window.title == "WTK Demo"
    assert window.exists() is True
    assert window.is_visible() is True
    window.maximize()
    window.minimize()
    window.restore()
    window.close()
    assert states == ["maximized", "minimized", "normal"]
    assert closed == [dialog]
    assert [r.action for r in runtime_setup] == [
        "window.maximize",
        "window.minimize",
        "window.restore",
        "window.close",
    ]
    assert window.locator == WindowLocator(title="WTK Demo")
    assert window.wait_for("visible") is window


def test_missing_window_does_not_exist(page: MainPage, monkeypatch: pytest.MonkeyPatch) -> None:
    from wintestkit.errors import WindowNotFoundError

    def missing(app: Any, wl: Any) -> None:
        raise WindowNotFoundError(
            Diagnostic(
                kind="window_not_found",
                message="No window matches",
                locator="Window",
                searched_in="Application",
                match_count=0,
            )
        )

    monkeypatch.setattr(model, "resolve_window", missing)
    assert page.window.exists() is False
    assert page.window.is_visible() is False
