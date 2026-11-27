"""A fake Playwright/CDP layer for the WebView2 content tests: no browser, no network.

``World`` stands for the machine: debugging ports with their pages, and the counters of what the
code did (drivers started, connections made, calls issued). ``install`` replaces the Playwright
loader and the clock of ``wintestkit.web`` so that waiting is instantaneous and deterministic.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest

from wintestkit import web


class FakeError(Exception):
    """``playwright.sync_api.Error``."""


class FakeTimeout(FakeError):
    """``playwright.sync_api.TimeoutError``."""


class Node:
    """A DOM element: attributes, text, children and an optional open (or closed) shadow root."""

    def __init__(
        self,
        tag: str = "div",
        *,
        id: str | None = None,
        text: str = "",
        value: str | None = None,
        visible: bool = True,
        shadow: list[Node] | None = None,
        shadow_mode: str = "open",
        children: list[Node] | None = None,
        **attrs: str,
    ) -> None:
        self.tag = tag
        self.attrs: dict[str, str] = {**attrs}
        if id is not None:
            self.attrs["id"] = id
        self.text = text
        self.value = value if value is not None else ""
        self.visible = visible
        self.children = children or []
        self.shadow = shadow
        self.shadow_mode = shadow_mode if shadow is not None else None

    def descendants(self) -> list[Node]:
        """Every element below this one, shadow trees included (Playwright pierces open roots)."""
        found: list[Node] = []
        for child in [*self.children, *(self.shadow or [])]:
            found.append(child)
            found.extend(child.descendants())
        return found

    def matches(self, css: str) -> bool:
        """``tag``, ``#id``, ``.class`` and ``[name]`` / ``[name='value']`` selectors, combined."""
        for part in re.findall(r"#[\w-]+|\.[\w-]+|\[[^\]]+\]|^[a-zA-Z][\w-]*", css):
            if part.startswith("#"):
                ok = self.attrs.get("id") == part[1:]
            elif part.startswith("."):
                ok = part[1:] in self.attrs.get("class", "").split()
            elif part.startswith("["):
                name, sep, expected = part[1:-1].partition("=")
                expected = expected.strip("'\"")
                ok = name in self.attrs and (not sep or self.attrs[name] == expected)
            else:
                ok = self.tag == part
            if not ok:
                return False
        return True


class Locator:
    def __init__(self, page: Page, nodes: Callable[[], list[Node]], css: str = "") -> None:
        self.page = page
        self._nodes = nodes
        self.css = css

    def _selector_check(self, css: str) -> None:
        if css.count("(") != css.count(")") or css.strip() in {"", ">>"}:
            raise FakeError(f"Unexpected token in selector {css!r}")

    def locator(self, selector: str) -> Locator:
        self._selector_check(selector)
        parent = self._nodes
        return Locator(
            self.page,
            lambda: [d for n in parent() for d in n.descendants() if d.matches(selector)],
            f"{self.css} >> {selector}",
        )

    def nth(self, index: int) -> Locator:
        parent = self._nodes
        return Locator(
            self.page, lambda: parent()[index : index + 1] if index >= 0 else [], self.css
        )

    def count(self) -> int:
        self.page.world.calls.append(("count", self.css))
        self._check_alive()
        return len(self._nodes())

    def _check_alive(self) -> None:
        if self.page.closed:
            raise FakeError("Target page, context or browser has been closed")

    def _one(self, action: str, timeout: float) -> Node:
        self._check_alive()
        nodes = self._nodes()
        if len(nodes) > 1:
            raise FakeError(f"strict mode violation: resolved to {len(nodes)} elements")
        if not nodes:
            raise FakeTimeout(f"Timeout {timeout:g}ms exceeded.\nwaiting for locator({self.css!r})")
        if action in {"click", "fill", "press_sequentially"} and not nodes[0].visible:
            raise FakeTimeout(
                f"Locator.{action}: Timeout {timeout:g}ms exceeded.\nCall log:\n"
                "  - waiting for element to be visible\n  -   element is not visible"
            )
        return nodes[0]

    def click(self, *, timeout: float) -> None:
        node = self._one("click", timeout)
        self.page.world.calls.append(("click", node.attrs.get("id", node.tag)))

    def fill(self, value: str, *, timeout: float) -> None:
        node = self._one("fill", timeout)
        node.value = value
        self.page.world.calls.append(("fill", value))

    def press_sequentially(self, text: str, *, timeout: float) -> None:
        node = self._one("press_sequentially", timeout)
        node.value += text
        self.page.world.calls.append(("type", text))

    def get_attribute(self, name: str, *, timeout: float) -> str | None:
        return self._one("get_attribute", timeout).attrs.get(name)

    def evaluate(self, expression: str, *, timeout: float) -> Any:
        node = self._one("evaluate", timeout)
        if expression == web._SHADOW_MODE:  # pyright: ignore[reportPrivateUsage]
            return node.shadow_mode
        if expression == web._READ_TEXT:  # pyright: ignore[reportPrivateUsage]
            is_field = node.tag in {"input", "textarea", "select"}
            return {
                "secret": node.tag == "input" and node.attrs.get("type") == "password",
                "text": node.value if is_field else node.text,
            }
        raise FakeError(f"unexpected script {expression!r}")

    def is_visible(self) -> bool:
        self._check_alive()
        nodes = self._nodes()
        if len(nodes) > 1:
            raise FakeError(f"strict mode violation: resolved to {len(nodes)} elements")
        return bool(nodes) and nodes[0].visible


class Page:
    def __init__(self, world: World, url: str, title: str = "", root: Node | None = None) -> None:
        self.world = world
        self._url = url
        self._title = title
        self.closed = False
        self.root = root or Node("html")

    @property
    def url(self) -> str:
        return self._url

    def navigate(self, url: str) -> None:
        self._url = url

    def title(self) -> str:
        return self._title

    def is_closed(self) -> bool:
        return self.closed

    def wait_for_timeout(self, timeout: float) -> None:
        self.world.calls.append(("pump", f"{timeout:g}"))
        self.world.pump(timeout / 1000)

    def locator(self, selector: str) -> Locator:
        root = Locator(self, lambda: [self.root])
        return root.locator(selector)


class Context:
    def __init__(self, browser: Browser) -> None:
        self.browser = browser

    @property
    def pages(self) -> list[Page]:
        return [p for p in self.browser.world.ports[self.browser.port] if not p.closed]


class Browser:
    def __init__(self, world: World, port: int) -> None:
        self.world = world
        self.port = port
        self.connected = True
        self.closed = False
        self.contexts = [Context(self)]

    def is_connected(self) -> bool:
        return self.connected

    def close(self) -> None:
        self.closed = True
        self.connected = False
        self.world.browsers_closed += 1


class _Chromium:
    def __init__(self, world: World) -> None:
        self.world = world

    def connect_over_cdp(self, endpoint: str, *, timeout: float) -> Browser:
        world = self.world
        world.endpoints.append(endpoint)
        match = re.fullmatch(r"http://127\.0\.0\.1:(\d+)", endpoint)
        assert match, f"connected to {endpoint}: only 127.0.0.1 may be used"
        port = int(match.group(1))
        if port not in world.ports:
            raise FakeError(f"BrowserType.connect_over_cdp: connect ECONNREFUSED 127.0.0.1:{port}")
        world.connects += 1
        browser = Browser(world, port)
        world.browsers.append(browser)
        return browser


class Driver:
    def __init__(self, world: World) -> None:
        self.world = world
        self.chromium = _Chromium(world)

    def start(self) -> Driver:
        self.world.drivers_started += 1
        return self

    def stop(self) -> None:
        self.world.drivers_stopped += 1


class World:
    """Ports with their pages, a clock, and the counters the tests assert on."""

    def __init__(self) -> None:
        self.ports: dict[int, list[Page]] = {}
        self.now = 1000.0
        self.drivers_started = 0
        self.drivers_stopped = 0
        self.connects = 0
        self.browsers_closed = 0
        self.browsers: list[Browser] = []
        self.endpoints: list[str] = []
        self.calls: list[tuple[str, str]] = []
        #: Pages that appear after the given number of seconds of waiting: (at, port, page).
        self.appearing: list[tuple[float, int, Page]] = []

    # -- the clock ------------------------------------------------------------------------------

    def sleep(self, seconds: float) -> None:
        self.pump(seconds)

    def pump(self, seconds: float) -> None:
        self.now += seconds
        for item in list(self.appearing):
            at, port, page = item
            if self.now >= at:
                self.ports[port].append(page)
                self.appearing.remove(item)

    # -- the machine ----------------------------------------------------------------------------

    def open_port(self, port: int, *pages: Page) -> list[Page]:
        self.ports[port] = list(pages)
        return self.ports[port]

    def page(self, port: int, url: str, title: str = "", root: Node | None = None) -> Page:
        page = Page(self, url, title, root)
        self.ports.setdefault(port, []).append(page)
        return page

    def replace(self, port: int, old: Page, new: Page) -> None:
        """The application recreated its WebView: ``old`` closes, ``new`` takes its place."""
        pages = self.ports[port]
        old.closed = True
        pages[pages.index(old)] = new

    def disconnect(self) -> None:
        for browser in self.browsers:
            browser.connected = False

    def api(self) -> web.PlaywrightApi:
        return web.PlaywrightApi(
            sync_playwright=lambda: Driver(self), error=FakeError, timeout_error=FakeTimeout
        )

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(web, "_api_loader", self.api)
        monkeypatch.setattr(web, "_clock", lambda: self.now)
        monkeypatch.setattr(web, "_sleep", self.sleep)
