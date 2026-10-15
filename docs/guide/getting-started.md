# Getting started

## Install

WinTestKit is a Python package with a pytest plugin and a `wtk` command. Add it to your test
project:

```powershell
uv add --dev wintestkit
```

or, with pip in a virtual environment:

```powershell
pip install wintestkit
```

Its only runtime dependency is `comtypes`. Then check that the machine can run UI tests:

```powershell
wtk doctor
```

`wtk doctor` verifies the Windows version, that the desktop is unlocked, that UI Automation
works, display scaling, your project configuration and whether the application is running at the
same elevation level. See [Troubleshooting](troubleshooting.md) for what each check means.

## Create a project

```powershell
wtk init --app "C:/Program Files/Contoso/Orders.exe"
```

`wtk init` never overwrites your files (use `--force` to replace the starter Python files). It:

- adds `[tool.pytest.ini_options]` and `[tool.wintestkit]` tables to `pyproject.toml`,
- creates `screens/main.py` with an empty `MainScreen`,
- creates `tests/test_smoke.py`, which checks that the main window appears,
- adds `wtk-report/` to `.gitignore`.

The configuration it writes looks like this:

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]

[tool.wintestkit]
launch = "per-session"

[tool.wintestkit.app]
path = "C:/Program Files/Contoso/Orders.exe"
```

In VS Code, **WinTestKit: Initialize Project** does the same.

## Describe the first screen

Start the application (`wtk run` and VS Code launch it for you; for exploring, start it yourself
or use **WinTestKit: Launch App**) and find its controls with the Spy:

```powershell
wtk spy
```

Hold **Ctrl** and click a control in your application. The Spy prints its properties and a
suggested locator; press **Esc** to exit. `wtk inspect` prints the whole UI Automation tree of
the application instead. The [VS Code Spy view](vscode.md#spy) does the same with a click-to-insert
button.

Copy the suggested locators into a screen class. This is the demo application's main window:

```python
# examples/demo-tests/screens/main.py
from wintestkit import Element, Elements, Screen, Window


class MainScreen(Screen):
    window = Window(title="WTK Demo")
```

```python
# examples/demo-tests/screens/main.py
    # credentials
    credentials = Element(control_type="Group", name="Credentials")
    username = Element(control_type="Edit", class_name="TextBox", within=credentials)
    password = Element(control_type="Edit", class_name="PasswordBox", within=credentials)
    remember_me = Element(control_type="CheckBox", name="Remember me", within=credentials)
    sign_in = Element(control_type="Button", name="Sign in", within=credentials)
```

Confirm a locator before using it:

```powershell
wtk highlight screens/main.py::MainScreen.sign_in
wtk check screens/main.py
```

`highlight` draws a frame around the control; `check` resolves every element of every screen in
the file and reports the ones that are missing or ambiguous.

## Write a test

Tests are ordinary pytest functions. The `app` fixture launches (or reuses) the application; the
demo project wraps it in a `main` fixture that returns the bound screen:

```python
# examples/demo-tests/conftest.py
@pytest.fixture
def main(screen) -> MainScreen:  # type: ignore[no-untyped-def]
    """The main window screen, bound to the application under test."""
    return screen(MainScreen)
```

```python
# examples/demo-tests/tests/test_login.py
def test_valid_login(main: MainScreen) -> None:
    main.username.type("admin")
    main.password.type("secret")
    main.sign_in.click()
    expect(main.status).to_have_text("Welcome, admin")
```

Every action waits for its element to exist, be enabled and be visible, and `expect` retries until
the assertion holds or the timeout expires, so there are no sleeps.

## Run it

```powershell
wtk run
```

`wtk run` checks the environment, runs pytest with the WinTestKit plugin and writes an HTML report
to `wtk-report/index.html`. Plain `pytest` works too; the plugin activates in any project with a
`[tool.wintestkit]` table. See [Running tests](running-tests.md).

## Use VS Code

Install the **WinTestKit** extension from the Marketplace. It adds **Highlight** and **Check**
actions above every element, runs and debugs tests from the Test Explorer, and has the Elements
and Spy views. See [VS Code](vscode.md).
