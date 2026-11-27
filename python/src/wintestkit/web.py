"""WebView2 content: pages, elements and shadow roots over the browser remote debugging port.

A WPF (or WinForms) application that hosts WebView2 can open a Chrome DevTools Protocol port on
``127.0.0.1``. This module connects to it with Playwright (the optional ``wintestkit[web]`` extra,
through ``connect_over_cdp``, which needs no downloaded browser) and wraps what the tests use:

- :class:`WebPage`: one target of the port (``app.web_page(url)``), found by URL;
- :class:`WebElement` and :class:`WebShadowRoot`: lookups below a page, an element or an open
  shadow root, whose actions are report steps like the desktop actions.

Nothing here is imported until a web API is used, and Playwright itself is only imported when a
connection is made, so WinTestKit works fully without the extra.
"""

from __future__ import annotations

import importlib
import logging
import re
import threading
import time
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

from wintestkit import runtime
from wintestkit.engine.diagnose import Diagnostic
from wintestkit.engine.locator import describe_matcher, match_value
from wintestkit.errors import (
    ActionError,
    AmbiguousElementError,
    AppError,
    ElementNotFoundError,
    InvalidLocatorError,
    WaitTimeoutError,
    WebConnectionError,
    WebError,
    WebExtraMissingError,
    WebPageNotFoundError,
)

if TYPE_CHECKING:
    from wintestkit.app import App

log = logging.getLogger("wintestkit.web")

#: The extra that provides Playwright.
EXTRA = "wintestkit[web]"
#: WebView2 reads extra Chromium switches from this variable.
BROWSER_ARGS_VARIABLE = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
_PORT_SWITCH = "--remote-debugging-port"
#: The debugging port is only ever contacted on the loopback interface, by address.
HOST = "127.0.0.1"

_POLL_INTERVAL = 0.1
_CONNECT_RETRY = 0.25

# Patched by unit tests.
_sleep: Callable[[float], None] = time.sleep
_clock: Callable[[], float] = time.monotonic


# -- the part of Playwright that is used ----------------------------------------------------------
#
# Protocols rather than imports: the extra is optional (and not installed when type-checking), and
# the unit tests drive the same code with a fake that has this shape.


class PwRoot(Protocol):
    def locator(self, selector: str) -> PwLocator: ...


class PwLocator(PwRoot, Protocol):
    def nth(self, index: int) -> PwLocator: ...
    def count(self) -> int: ...
    def click(self, *, timeout: float) -> None: ...
    def fill(self, value: str, *, timeout: float) -> None: ...
    def press_sequentially(self, text: str, *, timeout: float) -> None: ...
    def get_attribute(self, name: str, *, timeout: float) -> str | None: ...
    def evaluate(self, expression: str, *, timeout: float) -> Any: ...
    def is_visible(self) -> bool: ...


class PwPage(PwRoot, Protocol):
    @property
    def url(self) -> str: ...
    def title(self) -> str: ...
    def is_closed(self) -> bool: ...
    def wait_for_timeout(self, timeout: float) -> None: ...


class PwContext(Protocol):
    @property
    def pages(self) -> list[PwPage]: ...


class PwBrowser(Protocol):
    @property
    def contexts(self) -> list[PwContext]: ...
    def is_connected(self) -> bool: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class PlaywrightApi:
    """The names of ``playwright.sync_api`` the connection needs."""

    sync_playwright: Callable[[], Any]
    error: type[Exception]
    timeout_error: type[Exception]


def load_playwright() -> PlaywrightApi:
    """Import Playwright; raise :class:`WebExtraMissingError` naming the extra when it is absent."""
    __tracebackhide__ = True
    try:
        module = importlib.import_module("playwright.sync_api")
    except ImportError:
        raise WebExtraMissingError(
            "WebView2 content needs Playwright, which is not installed. Install the optional "
            f'extra: pip install "{EXTRA}" (or: uv add "{EXTRA}"). It connects to the running '
            "WebView2, so no browser download is needed."
        ) from None
    return PlaywrightApi(
        sync_playwright=module.sync_playwright,
        error=module.Error,
        timeout_error=module.TimeoutError,
    )


#: How the Playwright names are found; replaced by the unit tests with a fake.
_api_loader: Callable[[], PlaywrightApi] = load_playwright


# -- the debugging port ---------------------------------------------------------------------------


def check_port(port: object, *, key: str = "webview_debug_port") -> int:
    """``port`` as a TCP port number a browser can listen on and a test can connect to."""
    __tracebackhide__ = True
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(f"{key} must be a port number from 1 to 65535, got {port!r}")
    return port


def apply_debug_port(environment: MutableMapping[str, str], port: int) -> None:
    """Make a process started with ``environment`` open the remote debugging ``port``.

    The switch is appended to ``WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`` and whatever the variable
    already holds (from ``env=`` or the runner's own environment) is kept. A variable that already
    names the same port is left as it is; one that names another port is a conflict, because the
    test would connect to a port the application does not listen on.
    """
    __tracebackhide__ = True
    port = check_port(port)
    name = next((key for key in environment if key.upper() == BROWSER_ARGS_VARIABLE), None)
    existing = environment[name] if name is not None else ""
    for match in re.finditer(rf"(?:^|\s){_PORT_SWITCH}(?:=(\S*)|(?=\s|$))", existing):
        if match.group(1) == str(port):
            return
        raise AppError(
            f"{BROWSER_ARGS_VARIABLE} already contains {match.group(0).strip()}, but "
            f"webview_debug_port is {port}. Keep one of them: remove the switch from the "
            "variable, or set webview_debug_port to the port it names."
        )
    switch = f"{_PORT_SWITCH}={port}"
    environment[name or BROWSER_ARGS_VARIABLE] = (
        f"{existing} {switch}" if existing.strip() else switch
    )


def resolve_port(app: App, port: int | None) -> int:
    """The port to use: the call's, else the application's launch port, else the configuration's."""
    __tracebackhide__ = True
    if port is not None:
        return check_port(port, key="port")
    if app.webview_debug_port is not None:
        return app.webview_debug_port
    settings = runtime.get_config().app
    if settings is not None and settings.webview_debug_port is not None:
        return settings.webview_debug_port
    raise WebError(
        "No WebView2 debugging port is known. Pass port= to web_page(), launch the application "
        "with App.launch(..., webview_debug_port=PORT), or set webview_debug_port in "
        "[tool.wintestkit.app] (an application that passes --remote-debugging-port itself only "
        "needs the port)."
    )


# -- matching targets by URL ----------------------------------------------------------------------


@dataclass(frozen=True)
class UrlMatcher:
    """A page URL pattern: ``*`` and ``?`` wildcards (any case), or a compiled regex (search)."""

    pattern: str | re.Pattern[str]
    #: Compare as a plain string, wildcard characters included (a URL that was listed).
    literal: bool = False

    def __post_init__(self) -> None:
        __tracebackhide__ = True
        if not isinstance(self.pattern, str | re.Pattern):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"url must be a string or a compiled regex, got {self.pattern!r}")

    def matches(self, url: str) -> bool:
        __tracebackhide__ = True
        pattern = self.pattern
        if isinstance(pattern, re.Pattern):
            return match_value(pattern, url)
        if not self.literal and ("*" in pattern or "?" in pattern):
            body = "".join(
                ".*" if char == "*" else "." if char == "?" else re.escape(char) for char in pattern
            )
            return re.fullmatch(body, url, re.IGNORECASE | re.DOTALL) is not None
        return pattern.casefold() == url.casefold()

    def describe(self) -> str:
        __tracebackhide__ = True
        return describe_matcher(self.pattern)


@dataclass(frozen=True)
class _Target:
    """Which page of the port a :class:`WebPage` is: the ``ordinal``-th that matches."""

    url: UrlMatcher
    ordinal: int = 0

    def pick(self, pages: list[PwPage]) -> PwPage | None:
        __tracebackhide__ = True
        matching = [page for page in pages if self.url.matches(page.url)]
        return matching[self.ordinal] if self.ordinal < len(matching) else None


def _first_line(error: BaseException) -> str:
    """The error's headline and, when Playwright gives a call log, what it last tried."""
    __tracebackhide__ = True
    lines = [line.strip() for line in str(error).splitlines() if line.strip()]
    if not lines:
        return type(error).__name__
    if "Call log:" in lines:
        log_lines = [line.lstrip("- ").strip() for line in lines[lines.index("Call log:") + 1 :]]
        if log_lines:
            return f"{lines[0]} (last step: {log_lines[-1]})"
    return lines[0]


# -- one connection per application and port ------------------------------------------------------

_open: list[Connection] = []
_open_lock = threading.Lock()


class Connection:
    """The lazy CDP connection to one port: connects on first use, reconnects when it dropped."""

    def __init__(self, port: int, api: PlaywrightApi) -> None:
        __tracebackhide__ = True
        self.port = port
        self.api = api
        self.endpoint = f"http://{HOST}:{port}"
        self.closed = False
        self._driver: Any = None
        self._browser: PwBrowser | None = None
        with _open_lock:
            _open.append(self)

    def browser(self, deadline: float) -> PwBrowser:
        """The connected browser; connects (retrying until ``deadline``) when there is none."""
        __tracebackhide__ = True
        if self._browser is not None:
            try:
                if self._browser.is_connected():
                    return self._browser
            except self.api.error:
                pass
            log.debug("the connection to port %d dropped; connecting again", self.port)
            self._browser = None
        if self._driver is None:
            try:
                self._driver = self.api.sync_playwright().start()
            except self.api.error as exc:
                raise WebError(f"Playwright could not start: {_first_line(exc)}") from exc
        while True:
            budget = max(1.0, deadline - _clock())
            try:
                self._browser = self._driver.chromium.connect_over_cdp(
                    self.endpoint, timeout=budget * 1000
                )
                self.closed = False
                return cast("PwBrowser", self._browser)
            except self.api.error as exc:
                if _clock() >= deadline:
                    raise WebConnectionError(
                        f"Nothing answers on the WebView2 debugging port {self.endpoint}: "
                        f"{_first_line(exc)}. The application must open it: launch it with "
                        f"webview_debug_port={self.port} (App.launch, or under "
                        f"[tool.wintestkit.app]) or have it pass "
                        f"--remote-debugging-port={self.port} itself, and check that it is "
                        "running and has created its WebView2 content."
                    ) from exc
            _sleep(_CONNECT_RETRY)

    def pages(self, deadline: float) -> list[PwPage]:
        """Every open page of every context of the port, in the order the browser created them."""
        __tracebackhide__ = True
        browser = self.browser(deadline)
        return [page for context in browser.contexts for page in context.pages if not _gone(page)]

    def wait(self, seconds: float, deadline: float) -> None:
        """Sleep while still reading the browser's events, so new pages show up in ``pages``."""
        __tracebackhide__ = True
        seconds = max(0.0, min(seconds, deadline - _clock()))
        pages = self.pages(deadline)
        if pages:
            pages[0].wait_for_timeout(seconds * 1000)
        else:
            # Nothing to wait on: attach again, which picks up the targets that exist by then.
            _sleep(seconds)
            self.drop()

    def drop(self) -> None:
        """Forget the browser (not the Playwright driver), so the next use connects again."""
        __tracebackhide__ = True
        browser, self._browser = self._browser, None
        if browser is not None:
            try:
                browser.close()
            except Exception as exc:
                log.debug("closing the browser connection on port %d: %s", self.port, exc)

    def close(self) -> None:
        """Disconnect and stop the driver. The application's WebView2 is left running."""
        __tracebackhide__ = True
        self.drop()
        driver, self._driver = self._driver, None
        if driver is not None:
            try:
                driver.stop()
            except Exception as exc:
                log.debug("stopping Playwright for port %d: %s", self.port, exc)
        self.closed = True
        with _open_lock:
            if self in _open:
                _open.remove(self)

    def targets(self, deadline: float) -> tuple[str, ...]:
        """One line per page of the port (URL and title), for messages."""
        __tracebackhide__ = True
        lines: list[str] = []
        for page in self.pages(deadline):
            try:
                title = page.title()
            except Exception:
                title = ""
            lines.append(f"{page.url or '(blank)'}" + (f" - {title}" if title else ""))
        return tuple(lines)


def _gone(page: PwPage) -> bool:
    __tracebackhide__ = True
    try:
        return page.is_closed()
    except Exception:
        return True


def close_all() -> None:
    """Close every connection that is still open (at the end of a test)."""
    __tracebackhide__ = True
    with _open_lock:
        connections = list(_open)
    for connection in connections:
        connection.close()


def connection_for(app: App, port: int, api: PlaywrightApi) -> Connection:
    """The application's connection to ``port``, created (not yet connected) on first use."""
    __tracebackhide__ = True
    connection = app._web_connections.get(port)  # pyright: ignore[reportPrivateUsage]
    if connection is None or connection.closed:
        connection = Connection(port, api)
        app._web_connections[port] = connection  # pyright: ignore[reportPrivateUsage]
    return connection


def close_app(app: App) -> None:
    """Close the connections of one application."""
    __tracebackhide__ = True
    connections = list(app._web_connections.values())  # pyright: ignore[reportPrivateUsage]
    app._web_connections.clear()  # pyright: ignore[reportPrivateUsage]
    for connection in connections:
        connection.close()


# -- steps ----------------------------------------------------------------------------------------


def _timeout(per_call: float | None) -> float:
    __tracebackhide__ = True
    return runtime.get_config().timeout if per_call is None else max(0.0, per_call)


def _diagnostic(kind: str, message: str, page: WebPage, locator: str, count: int) -> Diagnostic:
    __tracebackhide__ = True
    return Diagnostic(
        kind=cast("Any", kind),
        message=message,
        locator=locator,
        searched_in=page.target_name,
        match_count=count,
    )


class _Scope:
    """What can be searched: a page, an element or an open shadow root."""

    _page: WebPage

    def _base(self, deadline: float) -> PwRoot:
        """The Playwright object lookups start from (found now; the page may have been rebound)."""
        __tracebackhide__ = True
        raise NotImplementedError

    def _path(self) -> str:
        """The selectors from the page down to this scope, for reports and messages."""
        __tracebackhide__ = True
        raise NotImplementedError

    def _step(
        self, action: str, args: Mapping[str, Any] | None = None, *, secret: bool = False
    ) -> Any:
        __tracebackhide__ = True
        return runtime.step(action, self._page.target_name, self._path(), args, secret=secret)

    # -- lookups ----------------------------------------------------------------------------

    def find_element(
        self,
        css: str,
        *,
        first: bool = False,
        nth: int | None = None,
        timeout: float | None = None,
    ) -> WebElement:
        """The one element matching ``css`` below this scope; waits up to ``timeout`` for it.

        Nothing matching fails with :class:`~wintestkit.errors.ElementNotFoundError` once the
        wait is over; several matches fail at once with
        :class:`~wintestkit.errors.AmbiguousElementError`, because waiting cannot fix it. Pass
        ``first=True`` or ``nth=i`` (0-based) to choose among several on purpose. Playwright CSS
        pierces open shadow roots, so a selector also reaches into them.
        """
        __tracebackhide__ = True
        _check_choice(first, nth)
        element = WebElement(self, css, 0 if first else nth)
        args: dict[str, Any] = {"css": css, "first": first, "nth": nth}
        with element._step("web.find", args) as record:  # pyright: ignore[reportPrivateUsage]
            deadline = _clock() + _timeout(timeout)
            element._resolve(deadline)  # pyright: ignore[reportPrivateUsage]
            record.args["page"] = self._page.current_url()
        return element

    def query_selector(self, css: str, *, timeout: float = 0) -> WebElement | None:
        """The first element matching ``css``, or ``None``; looks once unless ``timeout`` is given.

        Like Playwright's ``query_selector``: no wait by default, no strictness (several matches
        give the first), and a miss is a ``None`` rather than an error.
        """
        __tracebackhide__ = True
        element = WebElement(self, css, 0)
        with element._step("web.query", {"css": css}) as record:  # pyright: ignore[reportPrivateUsage]
            try:
                element._resolve(_clock() + max(0.0, timeout))  # pyright: ignore[reportPrivateUsage]
            except ElementNotFoundError:
                record.args["found"] = False
                return None
            record.args["found"] = True
        return element

    def find_elements(self, css: str, *, timeout: float = 0) -> list[WebElement]:
        """A snapshot of every element matching ``css``, as elements that look themselves up again.

        Empty when nothing matches; it waits for a first match only when ``timeout`` is given.
        """
        __tracebackhide__ = True
        with WebElement(self, css, None)._step(  # pyright: ignore[reportPrivateUsage]
            "web.find_all", {"css": css}
        ) as record:
            deadline = _clock() + max(0.0, timeout)
            found = self._count(css, deadline)
            record.args["count"] = found
        return [WebElement(self, css, index) for index in range(found)]

    def _count(self, css: str, deadline: float) -> int:
        __tracebackhide__ = True
        page = self._page
        while True:
            base = self._base(deadline)
            try:
                found = base.locator(css).count()
            except page._api.error as exc:  # pyright: ignore[reportPrivateUsage]
                page._transient_or_invalid(exc, css)  # pyright: ignore[reportPrivateUsage]
                found = 0
            if found or _clock() >= deadline:
                return found
            _sleep(_POLL_INTERVAL)

    #: The spellings of existing suites.
    FindElement = find_element
    FindElements = find_elements
    QuerySelector = query_selector


def _check_choice(first: bool, nth: int | None) -> None:
    __tracebackhide__ = True
    if first and nth is not None:
        raise ValueError("pass first=True or nth=, not both")
    if nth is not None and (isinstance(nth, bool) or not isinstance(nth, int) or nth < 0):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ValueError(f"nth must be a non-negative integer, got {nth!r}")


class WebPage(_Scope):
    """One page of an application's WebView2 content (see :meth:`App.web_page`).

    The wrapper remembers which page it is (the ``ordinal``-th one whose URL matches), not the
    Playwright object, so it finds the page again when a reload, a new WebView or a dropped
    connection replaced it. The Playwright ``Page`` itself is :attr:`playwright_page`.
    """

    def __init__(
        self, app: App, connection: Connection, target: _Target, bound: PwPage | None = None
    ) -> None:
        __tracebackhide__ = True
        self.app = app
        self.connection = connection
        self._target = target
        self._bound: PwPage | None = bound
        self._page = self
        self._api = connection.api

    # -- identity ---------------------------------------------------------------------------

    @property
    def target_name(self) -> str:
        __tracebackhide__ = True
        return f"web page {self._target.url.describe()} (port {self.connection.port})"

    @property
    def playwright_page(self) -> PwPage:
        """The underlying Playwright ``Page``, for everything this wrapper does not cover.

        It is looked up again if the page was replaced, but a reference kept from earlier is not
        updated: fetch it from here when it is needed.
        """
        __tracebackhide__ = True
        return self._current(_clock())

    @property
    def url(self) -> str:
        """The current URL of the page."""
        __tracebackhide__ = True
        return self.current_url()

    @property
    def title(self) -> str:
        """The current title of the page."""
        __tracebackhide__ = True
        return self._current(_clock()).title()

    def current_url(self) -> str:
        __tracebackhide__ = True
        try:
            return self._current(_clock()).url
        except WebPageNotFoundError:
            return ""

    def __repr__(self) -> str:
        __tracebackhide__ = True
        return f"<WebPage {self.target_name}>"

    # -- keeping the binding ----------------------------------------------------------------

    def _current(self, deadline: float) -> PwPage:
        """The bound Playwright page, found again (waiting until ``deadline``) when it is gone."""
        __tracebackhide__ = True
        bound = self._bound
        if bound is not None and not _gone(bound) and self._connected():
            return bound
        self._bound = None
        while True:
            pages = self.connection.pages(deadline)
            page = self._target.pick(pages)
            if page is not None:
                log.debug("web page %s bound to %s", self._target.url.describe(), page.url)
                self._bound = page
                return page
            if _clock() >= deadline:
                raise _not_found(self.connection, self._target.url, deadline)
            self.connection.wait(_POLL_INTERVAL, deadline)

    def _connected(self) -> bool:
        __tracebackhide__ = True
        browser = self.connection._browser  # pyright: ignore[reportPrivateUsage]
        try:
            return browser is not None and browser.is_connected()
        except Exception:
            return False

    def _transient_or_invalid(self, error: BaseException, css: str) -> None:
        """Let a failure caused by the page going away pass (callers look again); raise others."""
        __tracebackhide__ = True
        text = str(error).lower()
        bound = self._bound
        if (bound is not None and _gone(bound)) or any(
            sign in text for sign in ("closed", "context was destroyed", "navigat", "disconnected")
        ):
            self._bound = None
            return
        raise InvalidLocatorError(
            f"The selector {css!r} cannot be evaluated: {_first_line(error)}"
        ) from error

    def _base(self, deadline: float) -> PwRoot:
        __tracebackhide__ = True
        return self._current(deadline)

    def _path(self) -> str:
        __tracebackhide__ = True
        return ""


def _not_found(connection: Connection, url: UrlMatcher, deadline: float) -> WebPageNotFoundError:
    __tracebackhide__ = True
    try:
        targets = connection.targets(max(deadline, _clock()))
    except (WebError, connection.api.error):
        targets = ()
    listing = (
        "Available targets:\n" + "\n".join(f"  {i}. {line}" for i, line in enumerate(targets, 1))
        if targets
        else "The port has no pages (the WebView2 content may not have been created yet)."
    )
    return WebPageNotFoundError(
        f"No page matching {url.describe()} on the WebView2 debugging port {connection.endpoint}."
        f"\n{listing}",
        targets,
    )


class WebElement(_Scope):
    """An element below a scope; each action looks it up again and is a report step.

    Lookups chain: ``page.find_element("#form").find_element("button")`` searches inside
    ``#form``. :meth:`shadow_root` scopes them to an open shadow root.
    """

    def __init__(self, parent: _Scope, css: str, nth: int | None) -> None:
        __tracebackhide__ = True
        self.parent = parent
        self.css = css
        self._nth = nth
        self._page = parent._page  # pyright: ignore[reportPrivateUsage]

    # -- resolution -------------------------------------------------------------------------

    def _path(self) -> str:
        __tracebackhide__ = True
        own = self.css if self._nth is None else f"{self.css} [nth={self._nth}]"
        above = self.parent._path()  # pyright: ignore[reportPrivateUsage]
        return f"{above} >> {own}" if above else own

    def _base(self, deadline: float) -> PwLocator:
        __tracebackhide__ = True
        return self._resolve(deadline)

    def _resolve(self, deadline: float) -> PwLocator:
        """The Playwright locator of this one element, once it exists (and is unique)."""
        __tracebackhide__ = True
        page = self._page
        while True:
            base = self.parent._base(deadline)  # pyright: ignore[reportPrivateUsage]
            matches: PwLocator | None = None
            try:
                matches = base.locator(self.css)
                found = matches.count()
            except page._api.error as exc:  # pyright: ignore[reportPrivateUsage]
                page._transient_or_invalid(exc, self.css)  # pyright: ignore[reportPrivateUsage]
                found = 0
            index = self._nth
            if matches is not None and index is not None and found > index:
                return matches.nth(index)
            if matches is not None and index is None and found == 1:
                return matches
            if index is None and found > 1:
                raise AmbiguousElementError(
                    _diagnostic(
                        "ambiguous",
                        f"{found} elements match {self._path()} in {page.target_name}; use "
                        "first=True, nth=i or a more specific selector",
                        page,
                        self._path(),
                        found,
                    )
                )
            if _clock() >= deadline:
                what = "index_out_of_range" if found else "not_found"
                message = (
                    f"{self._path()} has {found} matches in {page.target_name}, so nth={index} "
                    "does not exist"
                    if found
                    else f"No element matches {self._path()} in {page.target_name}"
                )
                raise ElementNotFoundError(_diagnostic(what, message, page, self._path(), found))
            _sleep(_POLL_INTERVAL)

    def _do(self, action: str, deadline: float, call: Callable[[float], Any]) -> Any:
        """Run a Playwright call with the time left; turn its failures into WinTestKit errors."""
        __tracebackhide__ = True
        api = self._page._api  # pyright: ignore[reportPrivateUsage]
        milliseconds = max(1.0, (deadline - _clock()) * 1000)
        try:
            return call(milliseconds)
        except api.timeout_error as exc:
            raise WaitTimeoutError(
                f"{self._path()} was not ready to {action} in {self._page.target_name}: "
                f"{_first_line(exc)}"
            ) from exc
        except api.error as exc:
            raise ActionError(
                f"Could not {action} {self._path()} in {self._page.target_name}: {_first_line(exc)}"
            ) from exc

    @property
    def locator(self) -> PwLocator:
        """The Playwright ``Locator`` of this element (it is found, with the default wait)."""
        __tracebackhide__ = True
        return self._resolve(_clock() + _timeout(None))

    # -- shadow roots -----------------------------------------------------------------------

    def shadow_root(self, index: int = 0, *, timeout: float | None = None) -> WebShadowRoot:
        """Scope the following lookups to this element's open shadow root.

        ``index`` exists for ported code (``ShadowRoot(0)``); an element has one shadow root, so
        0 is the only value. A closed shadow root cannot be reached by any script. Waits up to
        ``timeout`` for the root to exist, which a custom element creates when it is upgraded.
        """
        __tracebackhide__ = True
        if isinstance(index, bool) or index != 0:  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValueError(
                f"shadow_root({index!r}): an element has one shadow root, so 0 is the only index"
            )
        with self._step("web.shadow_root", {"index": index}):
            deadline = _clock() + _timeout(timeout)
            while True:
                mode = self._shadow_mode(self._resolve(deadline), deadline)
                if mode == "open":
                    return WebShadowRoot(self)
                if _clock() >= deadline:
                    raise ElementNotFoundError(
                        _diagnostic(
                            "not_found",
                            f"{self._path()} in {self._page.target_name} has no open shadow "
                            "root (a closed one cannot be reached)",
                            self._page,
                            self._path(),
                            0,
                        )
                    )
                _sleep(_POLL_INTERVAL)

    def _shadow_mode(self, host: PwLocator, deadline: float) -> object:
        __tracebackhide__ = True
        return self._do(
            "inspect the shadow root of",
            deadline,
            lambda ms: host.evaluate(_SHADOW_MODE, timeout=ms),
        )

    # -- actions ----------------------------------------------------------------------------

    def click(self, *, timeout: float | None = None) -> None:
        """Click the element once it is visible, stable, enabled and not covered (Playwright)."""
        __tracebackhide__ = True
        with self._step("web.click") as record:
            deadline = _clock() + _timeout(timeout)
            target = self._resolve(deadline)
            self._do("click", deadline, lambda ms: target.click(timeout=ms))
            record.args["page"] = self._page.current_url()

    def set_text(self, text: str, *, timeout: float | None = None, secret: bool = False) -> None:
        """Clear the element, then type ``text`` into it.

        The text is hidden in logs and reports when ``secret=True`` and for a password input.
        """
        __tracebackhide__ = True
        args = {"text": text}
        with self._step("web.set_text", args, secret=True) as record:
            deadline = _clock() + _timeout(timeout)
            try:
                target = self._resolve(deadline)
            except Exception:
                record.sensitive = False  # nothing was typed: the failure can be shown
                raise
            kind = self._do(
                "read the type of", deadline, lambda ms: target.get_attribute("type", timeout=ms)
            )
            secret = secret or (kind or "").lower() == "password"
            record.sensitive = secret
            record.set_arguments(args, secret=secret)
            self._do("clear", deadline, lambda ms: target.fill("", timeout=ms))
            if text:
                self._do(
                    "type into", deadline, lambda ms: target.press_sequentially(text, timeout=ms)
                )

    @property
    def text(self) -> str:
        """The value of an input, textarea or select, else the element's rendered text."""
        __tracebackhide__ = True
        with self._step("web.text", secret=True) as record:
            deadline = _clock() + _timeout(None)
            try:
                target = self._resolve(deadline)
            except Exception:
                record.sensitive = False
                raise
            result = self._do(
                "read the text of", deadline, lambda ms: target.evaluate(_READ_TEXT, timeout=ms)
            )
            data = cast("Mapping[str, Any]", result)
            value = str(data.get("text", ""))
            secret = bool(data.get("secret", False))
            record.sensitive = secret
            record.set_arguments({"text": value}, secret=secret)
            return value

    def get_attribute(self, name: str, *, timeout: float | None = None) -> str | None:
        """The attribute's value, or ``None`` when the element does not have it."""
        __tracebackhide__ = True
        with self._step("web.get_attribute", {"name": name}) as record:
            deadline = _clock() + _timeout(timeout)
            target = self._resolve(deadline)
            value = self._do(
                f"read the {name} attribute of",
                deadline,
                lambda ms: target.get_attribute(name, timeout=ms),
            )
            record.args["value"] = value
            return cast("str | None", value)

    def is_visible(self) -> bool:
        """Whether the element exists and is visible; looks once and never waits."""
        __tracebackhide__ = True
        with self._step("web.is_visible") as record:
            try:
                target = self._resolve(_clock())
            except ElementNotFoundError:
                visible = False
            else:
                api = self._page._api  # pyright: ignore[reportPrivateUsage]
                try:
                    visible = bool(target.is_visible())
                except api.error as exc:
                    raise ActionError(
                        f"Could not check {self._path()} in {self._page.target_name}: "
                        f"{_first_line(exc)}"
                    ) from exc
            record.args["visible"] = visible
            return visible

    def __repr__(self) -> str:
        __tracebackhide__ = True
        return f"<WebElement {self._path()} in {self._page.target_name}>"

    #: The spellings of existing suites.
    ShadowRoot = shadow_root
    Click = click
    SetText = set_text


_SHADOW_MODE = "element => element.shadowRoot ? element.shadowRoot.mode : null"
_READ_TEXT = (
    "element => ({"
    " secret: element instanceof HTMLInputElement && element.type === 'password',"
    " text: (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement"
    " || element instanceof HTMLSelectElement) ? element.value : element.innerText })"
)


class WebShadowRoot(_Scope):
    """The open shadow root of an element: lookups below it (see :meth:`WebElement.shadow_root`).

    Playwright's selectors pierce open shadow roots, so a lookup here searches the host's
    subtree, including the shadow tree. Elements the host slots in from the page match too.
    """

    def __init__(self, host: WebElement) -> None:
        __tracebackhide__ = True
        self.host = host
        self._page = host._page  # pyright: ignore[reportPrivateUsage]

    def _base(self, deadline: float) -> PwLocator:
        __tracebackhide__ = True
        return self.host._resolve(deadline)  # pyright: ignore[reportPrivateUsage]

    def _path(self) -> str:
        __tracebackhide__ = True
        return f"{self.host._path()} >> #shadow-root"  # pyright: ignore[reportPrivateUsage]

    def __repr__(self) -> str:
        __tracebackhide__ = True
        return f"<WebShadowRoot {self.host._path()} in {self._page.target_name}>"  # pyright: ignore[reportPrivateUsage]


# -- finding pages --------------------------------------------------------------------------------


def web_page(
    app: App,
    url: str | re.Pattern[str] = "*",
    *,
    port: int | None = None,
    timeout: float | None = None,
) -> WebPage:
    """The first page of the WebView2 content whose URL matches; see :meth:`App.web_page`."""
    __tracebackhide__ = True
    matcher = UrlMatcher(url)
    with runtime.step("web.page", "web", matcher.describe(), {"url": matcher.describe()}) as record:
        api = _api_loader()
        number = resolve_port(app, port)
        record.args["port"] = number
        deadline = _clock() + _timeout(timeout)
        page = WebPage(app, connection_for(app, number, api), _Target(matcher))
        record.args["matched"] = page._current(deadline).url  # pyright: ignore[reportPrivateUsage]
    return page


def web_pages(
    app: App,
    url: str | re.Pattern[str] = "*",
    *,
    port: int | None = None,
    timeout: float | None = None,
) -> list[WebPage]:
    """Every page of the WebView2 content whose URL matches, in the order the browser has them."""
    __tracebackhide__ = True
    matcher = UrlMatcher(url)
    with runtime.step(
        "web.pages", "web", matcher.describe(), {"url": matcher.describe()}
    ) as record:
        api = _api_loader()
        number = resolve_port(app, port)
        record.args["port"] = number
        connection = connection_for(app, number, api)
        deadline = _clock() + _timeout(timeout)
        found: list[WebPage] = []
        seen: dict[str, int] = {}
        for page in connection.pages(deadline):
            current = page.url
            if not matcher.matches(current):
                continue
            ordinal = seen.get(current, 0)
            seen[current] = ordinal + 1
            # Each wrapper finds its own page again by the exact URL it had when listed.
            target = _Target(UrlMatcher(current, literal=True), ordinal)
            found.append(WebPage(app, connection, target, page))
        record.args["count"] = len(found)
    return found
