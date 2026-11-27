"""WebView2 content (``app.web_page``) on a fake Playwright/CDP layer."""

from __future__ import annotations

import re
import sys
from collections.abc import Generator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from web_fakes import FakeError, Node, Page, World

from wintestkit import runtime, web
from wintestkit.app import App, Apps
from wintestkit.config import WtkConfig, load_config
from wintestkit.errors import (
    ActionError,
    AmbiguousElementError,
    ElementNotFoundError,
    InvalidLocatorError,
    WaitTimeoutError,
    WebConnectionError,
    WebError,
    WebExtraMissingError,
    WebPageNotFoundError,
)

PORT = 9223
ORDERS = "https://app.example/index.html"


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Generator[World]:
    runtime.reset()
    world = World()
    world.install(monkeypatch)
    yield world
    web.close_all()
    runtime.reset()


@pytest.fixture
def config(tmp_path: Path) -> WtkConfig:
    cfg = load_config(tmp_path, {"timeout": 2, "app.webview_debug_port": 9300})
    runtime.set_config(cfg)
    return cfg


@pytest.fixture
def app() -> App:
    app = App("Demo.exe")
    app.webview_debug_port = PORT
    return app


@pytest.fixture
def steps() -> Generator[list[runtime.StepRecord]]:
    records: list[runtime.StepRecord] = []
    remove = runtime.add_step_listener(records.append)
    yield records
    remove()


def form_tree() -> Node:
    """A login form, a custom element with a shadow root and a nested one."""
    return Node(
        "html",
        children=[
            Node("input", id="userName", type="text"),
            Node("input", id="password", type="password"),
            Node("button", id="submit", text="Sign in"),
            Node("button", id="hidden", text="Hidden", visible=False),
            Node(
                "x-card",
                id="orderForm",
                shadow=[
                    Node("div", id="inner", **{"class": "wrap"}),
                    Node(
                        "x-button",
                        type="primary",
                        shadow=[Node("button", id="deep", text="Deep"), Node("span", text="x")],
                    ),
                ],
            ),
            Node("x-card", id="other", shadow=[Node("x-button", type="primary")]),
            Node("x-card", id="closed", shadow=[Node("b")], shadow_mode="closed"),
            Node("x-plain", id="plain"),
            Node("li", text="one", **{"class": "row"}),
            Node("li", text="two", **{"class": "row"}),
            Node("li", text="three", **{"class": "row"}),
        ],
    )


@pytest.fixture
def page(world: World) -> Page:
    return world.page(PORT, ORDERS, "Orders", form_tree())


# -- the missing extra ----------------------------------------------------------------------------


def test_web_apis_work_without_the_extra_until_they_are_used(
    monkeypatch: pytest.MonkeyPatch, app: App, steps: list[runtime.StepRecord]
) -> None:
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    monkeypatch.setattr(web, "_api_loader", web.load_playwright)
    with pytest.raises(WebExtraMissingError) as error:
        app.web_page()
    assert 'pip install "wintestkit[web]"' in str(error.value)
    assert "uv add" in str(error.value)
    with pytest.raises(WebExtraMissingError, match=r"wintestkit\[web\]"):
        app.web_pages()
    assert [(s.action, s.status) for s in steps] == [
        ("web.page", "failed"),
        ("web.pages", "failed"),
    ]


def test_the_missing_extra_is_reported_before_a_missing_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime.reset()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    monkeypatch.setattr(web, "_api_loader", web.load_playwright)
    with pytest.raises(WebExtraMissingError):
        App("Demo.exe").web_page()


def test_the_package_imports_without_playwright() -> None:
    import subprocess

    code = (
        "import sys; sys.modules['playwright']=None; sys.modules['playwright.sync_api']=None;"
        "import wintestkit.web, wintestkit.app; print('ok')"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert result.stdout.strip() == "ok", result.stderr


# -- the port -------------------------------------------------------------------------------------


def test_the_port_comes_from_the_call_then_the_launch_then_the_configuration(
    world: World, config: WtkConfig
) -> None:
    for port in (7001, PORT, 9300):
        world.page(port, f"https://app.example/{port}")
    launched = App("A.exe")
    launched.webview_debug_port = PORT
    plain = App("B.exe")
    assert launched.web_page(port=7001).url == "https://app.example/7001"
    assert launched.web_page().url == f"https://app.example/{PORT}"
    assert plain.web_page().url == "https://app.example/9300"  # [tool.wintestkit.app]


def test_no_port_anywhere_is_an_error_that_says_what_to_set(world: World, tmp_path: Path) -> None:
    runtime.set_config(load_config(tmp_path))
    with pytest.raises(WebError, match=r"port=.*webview_debug_port"):
        App("Demo.exe").web_page()


@pytest.mark.parametrize("port", [0, -1, 65536, True, "9223", 1.5])
def test_a_bad_port_is_refused(world: World, app: App, port: Any) -> None:
    with pytest.raises(ValueError, match="port"):
        app.web_page(port=port)


def test_only_the_loopback_address_is_contacted(world: World, app: App, page: Page) -> None:
    app.web_page()
    assert world.endpoints == [f"http://127.0.0.1:{PORT}"]


# -- matching URLs --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "url", "expected"),
    [
        ("*", "https://app.example/x", True),
        ("https://app.example/*", "https://app.example/index.html?a=1#b", True),
        ("https://app.example/index.htm?", ORDERS, True),
        ("https://*/index.html", ORDERS, True),
        ("https://app.example/*", "https://other.example/x", False),
        ("https://app.example/index", ORDERS, False),
        ("HTTPS://APP.EXAMPLE/INDEX.HTML", ORDERS, True),
        ("https://app.example/index.html", ORDERS, True),
        ("https://app.example/index.html", ORDERS + "?x=1", False),
        (re.compile(r"/orders/\d+$"), "https://app.example/orders/42", True),
        (re.compile(r"/orders/\d+$"), "https://app.example/orders/42/edit", False),
        (re.compile(r"^https://app\.example/(index|home)\.html$"), ORDERS, True),
        ("https://app.example/a.b", "https://app.example/aXb", False),  # a dot is a dot
    ],
)
def test_url_matching(pattern: str | re.Pattern[str], url: str, expected: bool) -> None:
    assert web.UrlMatcher(pattern).matches(url) is expected


def test_a_pattern_that_is_neither_text_nor_regex_is_refused(app: App) -> None:
    with pytest.raises(TypeError, match="url must be"):
        app.web_page(42)  # type: ignore[arg-type]


def test_the_first_matching_page_wins_and_any_url_means_the_first_page(
    world: World, app: App
) -> None:
    world.page(PORT, "about:blank")
    world.page(PORT, "https://app.example/a")
    world.page(PORT, "https://app.example/b")
    assert app.web_page().url == "about:blank"
    assert app.web_page("https://app.example/*").url == "https://app.example/a"
    assert app.web_page(re.compile(r"/b$")).url == "https://app.example/b"


def test_pages_are_listed_in_order(world: World, app: App) -> None:
    world.page(PORT, "https://app.example/a")
    world.page(PORT, "https://other.example/")
    world.page(PORT, "https://app.example/b")
    assert [p.url for p in app.web_pages()] == [
        "https://app.example/a",
        "https://other.example/",
        "https://app.example/b",
    ]
    assert [p.url for p in app.web_pages("https://app.example/*")] == [
        "https://app.example/a",
        "https://app.example/b",
    ]
    assert app.web_pages("https://nothing.example/*") == []


def test_a_page_that_appears_later_is_waited_for(world: World, app: App) -> None:
    world.open_port(PORT, Page(world, "about:blank"))
    world.appearing.append((world.now + 0.5, PORT, Page(world, ORDERS)))
    assert app.web_page(ORDERS).url == ORDERS


def test_a_port_that_opens_later_is_waited_for(world: World, app: App) -> None:
    class Opens(Page):
        pass

    original = world.sleep

    def sleep(seconds: float) -> None:
        original(seconds)
        if world.now >= 1000.6 and PORT not in world.ports:
            world.page(PORT, ORDERS)

    world.sleep = sleep  # type: ignore[method-assign]
    web._sleep = sleep  # pyright: ignore[reportPrivateUsage]
    assert app.web_page(timeout=5).url == ORDERS


# -- errors that list what is there ---------------------------------------------------------------


def test_a_closed_port_says_how_to_open_it(world: World, app: App, config: WtkConfig) -> None:
    started = world.now
    with pytest.raises(WebConnectionError) as error:
        app.web_page()
    message = str(error.value)
    assert f"http://127.0.0.1:{PORT}" in message
    assert "ECONNREFUSED" in message
    assert f"webview_debug_port={PORT}" in message and f"--remote-debugging-port={PORT}" in message
    assert world.now - started >= 2  # it waited for the configured timeout first


def test_no_matching_page_lists_the_targets(world: World, app: App, config: WtkConfig) -> None:
    world.page(PORT, "https://app.example/a", "Alpha")
    world.page(PORT, "about:blank")
    with pytest.raises(WebPageNotFoundError) as error:
        app.web_page("https://nope.example/*")
    message = str(error.value)
    assert '"https://nope.example/*"' in message
    assert "1. https://app.example/a - Alpha" in message
    assert "2. about:blank" in message
    assert error.value.targets == ("https://app.example/a - Alpha", "about:blank")


def test_a_port_without_pages_says_so(world: World, app: App, config: WtkConfig) -> None:
    world.open_port(PORT)
    with pytest.raises(WebPageNotFoundError, match="no pages"):
        app.web_page()


def test_the_regex_is_named_in_the_error(world: World, app: App, config: WtkConfig) -> None:
    world.page(PORT, "https://app.example/a")
    with pytest.raises(WebPageNotFoundError, match=r"/orders/\\d\+\$/"):
        app.web_page(re.compile(r"/orders/\d+$"))


def test_a_timeout_argument_overrides_the_setting(
    world: World, app: App, config: WtkConfig
) -> None:
    world.page(PORT, "about:blank")
    started = world.now
    with pytest.raises(WebPageNotFoundError):
        app.web_page("https://nope.example/", timeout=0.3)
    assert 0.29 <= world.now - started < 1


# -- one connection per application and port ------------------------------------------------------


def test_the_connection_is_made_lazily_and_reused(world: World, app: App, page: Page) -> None:
    assert (world.drivers_started, world.connects) == (0, 0)
    first = app.web_page()
    second = app.web_page(ORDERS)
    first.find_element("#submit").click()
    assert (world.drivers_started, world.connects) == (1, 1)
    assert first.connection is second.connection
    assert app.web_pages()[0].connection is first.connection
    assert world.connects == 1


def test_another_port_or_another_app_has_its_own_connection(
    world: World, app: App, page: Page
) -> None:
    world.page(7001, "https://app.example/other")
    other_app = App("Other.exe")
    other_app.webview_debug_port = PORT
    one = app.web_page()
    two = app.web_page(port=7001)
    three = other_app.web_page()
    assert len({id(one.connection), id(two.connection), id(three.connection)}) == 3
    assert world.connects == 3


def test_closing_the_app_closes_its_connections_and_a_later_use_connects_again(
    world: World, app: App, page: Page
) -> None:
    other = App("Other.exe")
    other.webview_debug_port = PORT
    app.web_page()
    other.web_page()
    app.close_web()
    assert (world.browsers_closed, world.drivers_stopped) == (1, 1)  # the other one stays
    app.web_page()
    assert world.connects == 3
    app.close_web()
    app.close_web()  # idempotent
    assert world.drivers_stopped == 2


def test_app_close_and_kill_release_the_connections(
    world: World, app: App, page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(App, "top_level_windows", lambda self: [])
    monkeypatch.setattr(App, "wait_for_exit", lambda self, timeout: True)
    monkeypatch.setattr(App, "detach_inspector", lambda self: None)
    app.web_page()
    app.close()
    assert world.drivers_stopped == 1
    app.web_page()
    monkeypatch.setattr(App, "pids", property(lambda self: []))
    app.kill()
    assert world.drivers_stopped == 2


def test_apps_release_what_they_only_attached_to(
    world: World, page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    attached = App("Demo.exe")
    attached.webview_debug_port = PORT
    monkeypatch.setattr(App, "detach_inspector", lambda self: None)
    monkeypatch.setattr(App, "attach", staticmethod(lambda process=None, pid=None: attached))
    group = Apps()
    group.attach("Demo.exe")
    attached.web_page()
    group.close_all()
    assert world.drivers_stopped == 1


def test_the_end_of_a_test_closes_every_connection(world: World, app: App, page: Page) -> None:
    app.web_page()
    App("Temp.exe").web_page(port=PORT)  # a throwaway App, as ``Sys.Process(...)`` makes
    assert world.drivers_started == 2
    runtime.end_test()
    assert (world.drivers_stopped, world.browsers_closed) == (2, 2)


def test_a_dropped_connection_is_made_again(world: World, app: App, page: Page) -> None:
    element = app.web_page().find_element("#submit")
    world.disconnect()
    element.click()
    assert world.connects == 2 and world.drivers_started == 1
    assert [c for c in world.calls if c[0] == "click"] == [("click", "submit")]


# -- a page that is recreated ---------------------------------------------------------------------


def test_a_replaced_page_is_found_again(world: World, app: App, page: Page) -> None:
    wrapper = app.web_page()
    assert wrapper.playwright_page is page
    fresh = Page(world, ORDERS, "Orders", form_tree())
    world.replace(PORT, page, fresh)
    wrapper.find_element("#submit").click()
    assert wrapper.playwright_page is fresh
    assert world.connects == 1


def test_a_reload_that_changes_the_url_keeps_the_page(world: World, app: App, page: Page) -> None:
    wrapper = app.web_page(ORDERS)
    page.navigate("https://app.example/other.html")
    assert wrapper.url == "https://app.example/other.html"
    wrapper.find_element("#submit").click()


def test_a_page_that_closes_for_good_fails_with_the_targets(
    world: World, app: App, page: Page, config: WtkConfig
) -> None:
    wrapper = app.web_page(ORDERS)
    page.closed = True
    world.page(PORT, "about:blank")
    with pytest.raises(WebPageNotFoundError, match="about:blank"):
        wrapper.find_element("#submit", timeout=0.2)


def test_a_listed_page_finds_itself_again_by_url_and_position(world: World, app: App) -> None:
    first = world.page(
        PORT, "https://app.example/tab", root=Node("html", children=[Node("a", id="a")])
    )
    world.page(PORT, "https://app.example/tab", root=Node("html", children=[Node("b", id="b")]))
    wrappers = app.web_pages()
    new_first = Page(
        world, "https://app.example/tab", root=Node("html", children=[Node("a", id="a2")])
    )
    world.replace(PORT, first, new_first)
    assert wrappers[0].find_element("#a2").get_attribute("id") == "a2"
    assert wrappers[1].find_element("#b").get_attribute("id") == "b"


# -- elements -------------------------------------------------------------------------------------


def test_the_login_form_forms_of_the_existing_suite(world: World, app: App, page: Page) -> None:
    web_page = app.web_page("*")
    user = web_page.find_element("#userName")
    user.set_text("alice")
    web_page.find_element("#submit").click()
    assert user.text == "alice"
    assert [c for c in world.calls if c[0] != "count"] == [
        ("fill", ""),
        ("type", "alice"),
        ("click", "submit"),
    ]


def test_set_text_clears_before_it_types(world: World, app: App, page: Page) -> None:
    field = app.web_page().find_element("#userName")
    field.set_text("first")
    field.set_text("second")
    assert field.text == "second"
    assert [c for c in world.calls if c[0] in {"fill", "type"}] == [
        ("fill", ""),
        ("type", "first"),
        ("fill", ""),
        ("type", "second"),
    ]


def test_set_text_with_an_empty_string_only_clears(world: World, app: App, page: Page) -> None:
    field = app.web_page().find_element("#userName")
    field.set_text("x")
    field.set_text("")
    assert field.text == ""


def test_text_is_the_value_of_a_field_and_the_text_of_anything_else(app: App, page: Page) -> None:
    web_page = app.web_page()
    assert web_page.find_element("#submit").text == "Sign in"
    assert web_page.find_element("#userName").text == ""


def test_attributes_and_visibility(app: App, page: Page) -> None:
    web_page = app.web_page()
    assert web_page.find_element("#userName").get_attribute("type") == "text"
    assert web_page.find_element("#userName").get_attribute("missing") is None
    assert web_page.find_element("#submit").is_visible() is True
    assert web_page.find_element("#hidden").is_visible() is False


def test_visibility_of_an_absent_element_is_false_and_never_waits(
    world: World, app: App, page: Page
) -> None:
    element = app.web_page().find_element("#submit")
    page.root.children = [c for c in page.root.children if c.attrs.get("id") != "submit"]
    started = world.now
    assert element.is_visible() is False
    assert world.now == started


def test_elements_chain_below_each_other(app: App, page: Page) -> None:
    form = app.web_page().find_element("#orderForm")
    assert form.find_element("#inner").get_attribute("class") == "wrap"
    with pytest.raises(ElementNotFoundError):
        form.find_element("#submit", timeout=0)


def test_an_unclickable_element_times_out_with_a_clear_error(
    app: App, page: Page, config: WtkConfig
) -> None:
    with pytest.raises(
        WaitTimeoutError,
        match=r"#hidden .*not ready to click.*Timeout 500ms exceeded[.] [(]last step: element is not visible[)]",
    ):
        app.web_page().find_element("#hidden").click(timeout=0.5)


def test_a_playwright_failure_that_is_not_a_timeout_is_an_action_error(
    app: App, page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    element = app.web_page().find_element("#submit")

    def boom(self: Any, *, timeout: float) -> None:
        raise FakeError("Element is outside of the viewport\nCall log: ...")

    monkeypatch.setattr("web_fakes.Locator.click", boom)
    with pytest.raises(ActionError, match=r"Could not click #submit.*outside of the viewport"):
        element.click()


def test_an_invalid_selector_is_an_invalid_locator_error(app: App, page: Page) -> None:
    with pytest.raises(InvalidLocatorError, match=r"selector '\(' cannot be evaluated"):
        app.web_page().find_element("(")


# -- shadow roots ---------------------------------------------------------------------------------


def test_the_shadow_root_chain_of_the_existing_suite(app: App, page: Page) -> None:
    web_page = app.web_page(ORDERS)
    button = (
        web_page.find_element("#orderForm")
        .shadow_root(0)
        .find_element("[type='primary']")
        .shadow_root(0)
        .find_element("button")
    )
    assert button.text == "Deep"
    button.click()


def test_the_migration_spellings_chain_the_same_way(app: App, page: Page) -> None:
    button = (
        app.Page(ORDERS)
        .FindElement("#orderForm")
        .ShadowRoot(0)
        .FindElement("[type='primary']")
        .ShadowRoot(0)
        .FindElement("button")
    )
    button.Click()
    assert app.Page("*").QuerySelector("#submit") is not None
    assert app.Page("*").FindElement("#userName").SetText("x") is None


def test_lookups_are_scoped_to_the_shadow_root_of_their_host(app: App, page: Page) -> None:
    web_page = app.web_page()
    first = web_page.find_element("#orderForm").shadow_root(0)
    second = web_page.find_element("#other").shadow_root(0)
    # Both hosts hold an ``x-button[type=primary]``: unscoped it would be ambiguous.
    with pytest.raises(AmbiguousElementError):
        web_page.find_element("[type='primary']")
    assert first.find_element("[type='primary']") is not second.find_element("[type='primary']")
    assert first.find_element("#inner").get_attribute("class") == "wrap"
    with pytest.raises(ElementNotFoundError):
        second.find_element("#inner", timeout=0)


def test_a_plain_selector_reaches_into_open_shadow_roots_too(app: App, page: Page) -> None:
    assert app.web_page().find_element("#deep").text == "Deep"


def test_shadow_root_has_one_index(app: App, page: Page) -> None:
    host = app.web_page().find_element("#orderForm")
    with pytest.raises(ValueError, match="only index"):
        host.shadow_root(1)
    with pytest.raises(ValueError, match="only index"):
        host.shadow_root(-1)


def test_an_element_without_an_open_shadow_root_fails_clearly(app: App, page: Page) -> None:
    web_page = app.web_page()
    with pytest.raises(ElementNotFoundError, match=r"#plain .*no open shadow root"):
        web_page.find_element("#plain").shadow_root(timeout=0)
    with pytest.raises(ElementNotFoundError, match="closed one cannot be reached"):
        web_page.find_element("#closed").shadow_root(timeout=0)


def test_a_shadow_root_that_is_attached_later_is_waited_for(
    world: World, app: App, page: Page
) -> None:
    plain = app.web_page().find_element("#plain")
    node = next(c for c in page.root.children if c.attrs.get("id") == "plain")
    original = web._sleep  # pyright: ignore[reportPrivateUsage]

    def sleep(seconds: float) -> None:
        original(seconds)
        node.shadow, node.shadow_mode = [Node("p", id="late")], "open"

    web._sleep = sleep  # pyright: ignore[reportPrivateUsage]
    try:
        assert plain.shadow_root().find_element("#late").get_attribute("id") == "late"
    finally:
        web._sleep = original  # pyright: ignore[reportPrivateUsage]


# -- strictness, first and nth --------------------------------------------------------------------


def test_several_matches_fail_at_once_with_an_ambiguity_error(
    world: World, app: App, page: Page, config: WtkConfig
) -> None:
    web_page = app.web_page()
    started = world.now
    with pytest.raises(AmbiguousElementError) as error:
        web_page.find_element(".row")
    assert world.now == started  # waiting cannot fix it
    assert "3 elements match .row" in str(error.value)
    assert "first=True, nth=i" in str(error.value)
    assert error.value.diagnostic.kind == "ambiguous"
    assert error.value.diagnostic.match_count == 3


def test_first_and_nth_choose_on_purpose(app: App, page: Page) -> None:
    web_page = app.web_page()
    assert web_page.find_element(".row", first=True).text == "one"
    assert web_page.find_element(".row", nth=2).text == "three"
    assert web_page.find_element("#submit", first=True).text == "Sign in"


def test_nth_beyond_the_matches_is_not_found(app: App, page: Page, config: WtkConfig) -> None:
    with pytest.raises(ElementNotFoundError, match=r"has 3 matches.*nth=3 does not exist"):
        app.web_page().find_element(".row", nth=3)


def test_first_and_nth_together_are_refused(app: App, page: Page) -> None:
    with pytest.raises(ValueError, match="not both"):
        app.web_page().find_element(".row", first=True, nth=1)
    with pytest.raises(ValueError, match="non-negative"):
        app.web_page().find_element(".row", nth=-1)


def test_nothing_matching_waits_for_the_timeout_and_names_the_selector(
    world: World, app: App, page: Page, config: WtkConfig
) -> None:
    started = world.now
    with pytest.raises(ElementNotFoundError) as error:
        app.web_page().find_element("#nothing")
    assert world.now - started >= 2
    assert "No element matches #nothing" in str(error.value)
    assert error.value.diagnostic.kind == "not_found"


def test_an_element_that_appears_during_the_wait_is_found(
    world: World, app: App, page: Page, config: WtkConfig
) -> None:
    late = Node("div", id="late")
    original = web._sleep  # pyright: ignore[reportPrivateUsage]
    ticks = 0

    def sleep(seconds: float) -> None:
        nonlocal ticks
        original(seconds)
        ticks += 1
        if ticks == 3:
            page.root.children.append(late)

    web._sleep = sleep  # pyright: ignore[reportPrivateUsage]
    try:
        assert app.web_page().find_element("#late").get_attribute("id") == "late"
    finally:
        web._sleep = original  # pyright: ignore[reportPrivateUsage]


def test_query_selector_does_not_wait_or_insist_on_one_match(
    world: World, app: App, page: Page, config: WtkConfig
) -> None:
    web_page = app.web_page()
    started = world.now
    assert web_page.query_selector("#nothing") is None
    assert world.now == started
    first = web_page.query_selector(".row")
    assert first is not None and first.text == "one"


def test_query_selector_can_be_given_a_wait(world: World, app: App, page: Page) -> None:
    started = world.now
    assert app.web_page().query_selector("#nothing", timeout=0.5) is None
    assert world.now - started >= 0.5


def test_find_elements_is_a_snapshot_of_usable_elements(app: App, page: Page) -> None:
    rows = app.web_page().find_elements(".row")
    assert [row.text for row in rows] == ["one", "two", "three"]
    assert app.web_page().find_elements("#nothing") == []


def test_find_elements_waits_only_when_asked(world: World, app: App, page: Page) -> None:
    web_page = app.web_page()
    started = world.now
    assert web_page.find_elements("#nothing") == []
    assert world.now == started
    assert web_page.find_elements("#nothing", timeout=0.4) == []
    assert world.now - started >= 0.4


def test_the_elements_below_an_element_and_a_shadow_root(app: App, page: Page) -> None:
    shadow = app.web_page().find_element("#orderForm").shadow_root()
    assert len(shadow.find_elements("x-button")) == 1
    assert shadow.query_selector("#inner") is not None


# -- steps in the report --------------------------------------------------------------------------


def test_every_lookup_and_action_is_a_step(
    app: App, page: Page, steps: list[runtime.StepRecord]
) -> None:
    web_page = app.web_page(ORDERS)
    field = web_page.find_element("#userName")
    field.set_text("alice")
    assert field.text == "alice"
    assert field.get_attribute("type") == "text"
    assert field.is_visible()
    web_page.find_element("#submit").click()
    web_page.query_selector("#nothing")
    web_page.find_elements(".row")
    web_page.find_element("#orderForm").shadow_root()
    web_page_list = app.web_pages()
    assert len(web_page_list) == 1
    assert [s.action for s in steps] == [
        "web.page",
        "web.find",
        "web.set_text",
        "web.text",
        "web.get_attribute",
        "web.is_visible",
        "web.find",
        "web.click",
        "web.query",
        "web.find_all",
        "web.find",
        "web.shadow_root",
        "web.pages",
    ]
    assert all(s.status == "passed" for s in steps)
    page_step, find, set_text = steps[0], steps[1], steps[2]
    assert page_step.args == {"url": f'"{ORDERS}"', "port": PORT, "matched": ORDERS}
    assert find.args["css"] == "#userName" and find.args["page"] == ORDERS
    assert find.locator == "#userName"
    assert find.target == f'web page "{ORDERS}" (port {PORT})'
    assert set_text.args == {"text": "alice"}
    assert steps[4].args == {"name": "type", "value": "text"}
    assert steps[8].args == {"css": "#nothing", "found": False}
    assert steps[9].args == {"css": ".row", "count": 3}
    assert steps[11].locator == "#orderForm"


def test_chained_lookups_name_the_whole_path(
    app: App, page: Page, steps: list[runtime.StepRecord]
) -> None:
    app.web_page().find_element("#orderForm").shadow_root().find_element("[type='primary']").click()
    click = steps[-1]
    assert click.action == "web.click"
    assert click.locator == "#orderForm >> #shadow-root >> [type='primary']"


def test_a_failed_lookup_is_a_failed_step_with_the_error(
    app: App, page: Page, steps: list[runtime.StepRecord]
) -> None:
    with pytest.raises(AmbiguousElementError):
        app.web_page().find_element(".row")
    failed = steps[-1]
    assert (failed.action, failed.status) == ("web.find", "failed")
    assert failed.error is not None and failed.error["type"] == "AmbiguousElementError"
    assert failed.error["diagnostic"]["kind"] == "ambiguous"


def test_a_password_is_never_in_the_report(
    app: App, page: Page, steps: list[runtime.StepRecord]
) -> None:
    field = app.web_page().find_element("#password")
    field.set_text("hunter2")
    assert field.text == "hunter2"
    set_text, read = steps[-2], steps[-1]
    assert set_text.args == {"text": "***"} and read.args == {"text": "***"}
    assert "hunter2" not in repr([s.to_dict() for s in steps])


def test_secret_text_is_hidden_on_any_field(
    app: App, page: Page, steps: list[runtime.StepRecord]
) -> None:
    app.web_page().find_element("#userName").set_text("token-123", secret=True)
    assert steps[-1].args == {"text": "***"}


def test_text_is_shown_for_an_ordinary_field(
    app: App, page: Page, steps: list[runtime.StepRecord]
) -> None:
    app.web_page().find_element("#userName").set_text("alice")
    assert steps[-1].args == {"text": "alice"}


def test_a_missing_field_is_reported_even_when_typing_a_secret(
    app: App, page: Page, config: WtkConfig, steps: list[runtime.StepRecord]
) -> None:
    field = app.web_page().find_element("#userName")
    page.root.children.clear()
    with pytest.raises(ElementNotFoundError):
        field.set_text("secret-value", timeout=0, secret=True)
    failed = steps[-1]
    assert failed.status == "failed" and failed.error is not None
    assert failed.error["type"] == "ElementNotFoundError"
    assert "secret-value" not in repr(failed.to_dict())


def test_the_timeout_setting_governs_every_wait(
    world: World, app: App, page: Page, tmp_path: Path
) -> None:
    runtime.set_config(replace(load_config(tmp_path), timeout=0.6))
    started = world.now
    with pytest.raises(ElementNotFoundError):
        app.web_page().find_element("#nothing")
    assert 0.6 <= world.now - started < 1.5


def test_the_underlying_playwright_objects_are_reachable(app: App, page: Page) -> None:
    web_page = app.web_page()
    assert web_page.playwright_page is page
    assert web_page.title == "Orders"
    element = web_page.find_element("#submit")
    assert element.locator.count() == 1
