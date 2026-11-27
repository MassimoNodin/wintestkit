"""WebView2 content against a real WebView2 host application.

These tests need a desktop application that embeds WebView2, and the ``wintestkit[web]`` extra.
They are skipped unless ``WTK_WEBVIEW_TEST_HOST`` is the path of that host's exe. The host must
open a page whose address matches ``https://app.example/*`` or is a local ``file:`` URL, with:

- ``<input id="userName">`` and ``<input id="password" type="password">``;
- ``<button id="submit">`` that sets the text of ``<div id="result">`` to ``submitted`` on click;
- ``<x-card id="orderForm">`` whose open shadow root holds ``<x-button type="primary">``, whose
  own open shadow root holds a ``<button>``.

``WTK_WEBVIEW_TEST_PORT`` (default 9223) is the debugging port the tests open; the host is started
by the test with ``webview_debug_port``, so it must not pass the switch itself.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest

from wintestkit.app import App
from wintestkit.errors import AmbiguousElementError, WebPageNotFoundError

pytestmark = pytest.mark.integration

HOST = os.environ.get("WTK_WEBVIEW_TEST_HOST", "")
PORT = int(os.environ.get("WTK_WEBVIEW_TEST_PORT", "9223"))

pytest.importorskip("playwright.sync_api", reason="needs the wintestkit[web] extra")
if not HOST or not Path(HOST).is_file():
    pytest.skip(
        "WTK_WEBVIEW_TEST_HOST does not point at a WebView2 test host", allow_module_level=True
    )


@pytest.fixture
def host() -> Generator[App]:
    app = App.launch(HOST, webview_debug_port=PORT)
    try:
        yield app
    finally:
        app.close()


def test_the_first_page_is_found_with_any_url(host: App) -> None:
    page = host.web_page("*")
    assert page.url
    assert page.playwright_page.url == page.url


def test_pages_are_listed_and_a_missing_url_lists_them(host: App) -> None:
    pages = host.web_pages()
    assert pages
    with pytest.raises(WebPageNotFoundError) as error:
        host.web_page("https://nothing.example/*", timeout=1)
    assert pages[0].url in str(error.value)


def test_the_login_form_is_filled_and_submitted(host: App) -> None:
    page = host.web_page("*")
    user = page.find_element("#userName")
    user.set_text("alice")
    page.find_element("#password").set_text("hunter2")
    assert user.text == "alice"
    page.find_element("#submit").click()
    assert page.find_element("#result").text == "submitted"


def test_the_shadow_root_chain_and_the_plain_selector_reach_the_same_button(host: App) -> None:
    page = host.web_page("*")
    chained = (
        page.find_element("#orderForm")
        .shadow_root(0)
        .find_element("[type='primary']")
        .shadow_root(0)
        .find_element("button")
    )
    plain = page.find_element("#orderForm button")
    assert chained.text == plain.text
    chained.click()


def test_several_matches_are_ambiguous_unless_chosen(host: App) -> None:
    page = host.web_page("*")
    with pytest.raises(AmbiguousElementError):
        page.find_element("input")
    assert page.find_element("input", first=True).get_attribute("id") == "userName"


def test_the_page_is_found_again_after_a_reload(host: App) -> None:
    page = host.web_page("*")
    page.playwright_page.reload()
    page.find_element("#submit").click()


def test_the_connection_is_released_with_the_application(host: App) -> None:
    host.web_page("*")
    host.close_web()
    assert host.web_page("*").find_element("#submit").is_visible()
