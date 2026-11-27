# WebView2 content

A WPF or WinForms application can host web pages in a WebView2 control. WinTestKit drives the
content of those pages (type into a field, click a button, read text) through the browser's
remote debugging port, in the same test as the desktop controls around them. It uses
[Playwright for Python](https://playwright.dev/python/) to *attach to the running WebView2*
(`connect_over_cdp`), so **no browser is downloaded** and the application keeps running as it is.

The web API is optional. WinTestKit imports and works fully without it; the first call of a web
API without the extra raises `WebExtraMissingError`, which names it.

## Install

```powershell
pip install "wintestkit[web]"
```

or `uv add "wintestkit[web]"`. The extra pins `playwright==1.65.1`.

## Open the debugging port

WebView2 opens the port when the process is started with the Chromium switch
`--remote-debugging-port=<port>`. Either let WinTestKit do it or let the application do it.

**WinTestKit starts the application.** Give the port to the launch, or set it once in the
configuration:

```python
# pseudo-code
app = App.launch(path, webview_debug_port=9223)
```

```toml
[tool.wintestkit.app]
path = "bin/Debug/Host.exe"
webview_debug_port = 9223
```

The launched process gets `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9223`.
A value that is already there (from `app.env`, `App.launch(env=...)` or the environment of the
test runner) is kept and the switch is appended; the same port already in it is left alone, and
another port is an `AppError` rather than a test that connects to a port nobody listens on. The
port must be a number from 1 to 65535. An elevated launch through the shell (`elevated=True`
from a runner that is not elevated) cannot take environment variables, so it cannot take
`webview_debug_port` either.

**The application passes the switch itself.** Then connecting only needs the port. Do not set
`webview_debug_port` for a launch (it would add a second switch); name the port where you use it:

```python
# pseudo-code
page = app.web_page("*", port=9223)
```

An application that is only attached to (not launched by the test) takes its port from
`webview_debug_port` in the configuration, which is then used for connecting alone.

### Security

The port listens on the loopback interface (`127.0.0.1`), and WinTestKit only ever connects there.
That is not a lock: **while the port is open, any process on the machine, of any user, can read
and drive every page of that WebView2**, including pages the user is signed in to. Open it for
test runs and test machines only, never in a shipped build or on a shared server that other
people can sign in to, and pick a port that is not used for anything else.

## Find a page

```python
# pseudo-code
def test_sign_in(app):
    page = app.web_page("https://app.example/*")
    page.find_element("#Input_Username").set_text("alice")
    page.find_element("#Input_Password").set_text("secret-value")
    page.find_element("button[type=submit]").click()
```

`app.web_page(url="*", *, port=None, timeout=None)` returns the first page of the WebView2
content whose URL matches. `url` takes `*` (any run of characters) and `?` (one character)
wildcards, compared whole and without regard to case, or a compiled regular expression that is
searched in the URL (`re.compile(r"/orders/\d+$")`). `"*"`, the default, is any page.
`app.web_pages(url="*")` lists every match in the order the browser has them, for a test that
looks at each.

`timeout` defaults to the test timeout setting (`timeout` in the configuration, `WTK_TIMEOUT`,
the `wtk` marker). It covers waiting for the port to answer (the application may still be
starting) and for a matching page to exist. If it runs out, the error says what it found:

- the port is closed: `WebConnectionError` names the address and how to open the port;
- the port answers but no page matches: `WebPageNotFoundError` lists the pages (URL and title) it
  has, or says it has none.

The wrapper has these members:

| Member | What it does |
|---|---|
| `playwright_page` | The underlying Playwright `Page`, for everything this API does not cover |
| `url`, `title` | The current URL and title |
| `find_element(css)`, `query_selector(css)`, `find_elements(css)` | Lookups, below |

### Connections

The connection is made on first use, once per `App` and port, and reused by every page and element
of that application. It is closed with `app.close()`, `app.kill()` and `app.close_gracefully()`, by
`app.close_web()`, and at the end of each test, whatever `App` objects the test made. Closing it
never closes the application's WebView2.

A wrapper remembers *which page* it is, not the Playwright object. When the page is reloaded the
object stays; when the application replaces its WebView (or the connection drops), the wrapper
looks for the page again among the ones that match, and reconnects when needed. Only the
`playwright_page` you saved in a variable earlier is not updated: read it from the wrapper when
you need it.

## Find and act on elements

```python
# pseudo-code
def test_orders(app):
    page = app.web_page("https://app.example/*")
    form = page.find_element("#orderForm")
    form.find_element("input[name=customer]").set_text("Contoso")
    form.find_element("button.save").click()
    assert page.find_element("#status").text == "Saved"
    assert page.find_element("#status").get_attribute("data-state") == "ok"
    assert page.find_element("#spinner").is_visible() is False
```

`find_element(css, *, first=False, nth=None, timeout=None)` waits for the element and returns it.
Selectors are Playwright selectors: CSS, plus `text=`, `role=` and so on.

| Element member | What it does |
|---|---|
| `find_element(css)`, `find_elements(css)`, `query_selector(css)` | The same lookups, searching inside this element |
| `shadow_root(index=0)` | Scope the following lookups to this element's open shadow root; see below |
| `click()` | Click once the element is visible, stable, enabled and not covered |
| `set_text(text, secret=False)` | Clear the field, then type `text` |
| `text` | A field's value, otherwise the element's rendered text |
| `get_attribute(name)` | The attribute's value, or `None` |
| `is_visible()` | Whether it exists and is visible; looks once, never waits |
| `locator` | The Playwright `Locator`, for everything else |

Every lookup and action looks the element up again, so an element object stays valid when the page
re-renders. Waits use the test timeout setting; every action takes `timeout=`.

### One match: strictness

`find_element` follows the same strict rule as desktop locators. No match fails with
`ElementNotFoundError` after the wait; **several matches fail at once** with
`AmbiguousElementError` (waiting cannot fix it) that says how many matched and where. To pick on
purpose, say so:

```python
# pseudo-code
page.find_element("li.row", first=True).click()
page.find_element("li.row", nth=2).click()
rows = page.find_elements("li.row")       # a list of elements; no wait unless timeout= is given
```

`find_elements` returns a snapshot list (empty when nothing matches) of elements that find
themselves again by position. `query_selector(css)` is Playwright's: it does not wait unless
`timeout=` is given, returns the first of several matches, and returns `None` for none, so it
suits "is there such an element right now" checks.

### Shadow roots

`shadow_root(0)` scopes the lookups that follow to the element's open shadow root, so a chain
through nested custom elements reads as it is built:

```python
# pseudo-code
button = (
    page.find_element("#orderForm")
    .shadow_root(0)
    .find_element("[type='primary']")
    .shadow_root(0)
    .find_element("button")
)
button.click()
```

`index` exists so ported code keeps working; an element has one shadow root, so `0` is the only
valid value. A host without an open shadow root (closed roots cannot be reached by any script)
fails with `ElementNotFoundError` once the wait is over.

**A plain CSS selector reaches into open shadow roots as well**: Playwright's selector engine
pierces them. `page.find_element("#orderForm button")` finds the same button as the chain above,
and is often shorter. The chain is still useful to keep a lookup inside one host when several
hosts contain the same inner markup; note that elements the host *slots in* from the page also
match inside it, because the scope is the host's subtree.

## In reports

Every page lookup, element lookup and action is a report step, like the desktop actions:
`web.page`, `web.pages`, `web.find`, `web.find_all`, `web.query`, `web.shadow_root`, `web.click`,
`web.set_text`, `web.text`, `web.get_attribute` and `web.is_visible`. The step's locator shows the
selector path from the page (`#orderForm >> #shadow-root >> [type='primary']`). The text typed
into a password input is replaced by `***`, as is anything passed with `secret=True`, and so is
a password field's `text`.

## Limits

- The API is synchronous and must be used from the test's thread, like the rest of WinTestKit.
- Only pages (targets of type page) of the WebView2 content are visible; the desktop controls
  around them keep using the regular locators.
- `set_text` types key by key after clearing. For a field that rejects typed input, use the
  Playwright locator: `element.locator.fill("text")`.
- The Playwright objects (`playwright_page`, `locator`) are not report steps.
