# Migrating from TestComplete

WinTestKit covers the part of TestComplete used for **WPF desktop testing**, with Python and
pytest instead of a proprietary IDE and project format.

## Concept mapping

| TestComplete | WinTestKit |
|---|---|
| Project suite / project | A folder with `pyproject.toml` containing `[tool.wintestkit]` |
| Tested Applications | `[tool.wintestkit.app]` (`path`, `args`, `cwd`, `env`) and the launch mode |
| NameMapping | `Page` classes with `Element` attributes |
| Aliases | Page attribute names (`main.sign_in`) |
| Mapping criteria (properties) | `automation_id`, `name`, `control_type`, `class_name`, `index` |
| Mapped object hierarchy | `within=` |
| Conditional / extended find | Regular expressions in `name=` and friends, `Elements(...).filter()` |
| Object Spy / Object Browser | The Spy (`wtk spy` or the VS Code Spy view) and `wtk inspect` |
| Highlight on screen | `wtk highlight` or the **Highlight** CodeLens |
| Keyword tests / script routines | pytest test functions |
| Checkpoints (property, region) | `expect(...)` assertions |
| `WaitProperty`, `WaitChild`, `Exists` | Automatic waiting in actions and `expect`; `wait_for()`, `exists()` |
| Auto-wait timeout | `timeout` setting, per-element `timeout=`, per-call `timeout=` |
| Event handlers (`OnUnexpectedWindow`, …) | pytest fixtures (setup and teardown) |
| Test items / execution plan | Test files, folders and pytest markers (`wtk run -m smoke`) |
| Data-driven loops | `@pytest.mark.parametrize` |
| TestExecute / command-line runs | `wtk run` (or `pytest`) |
| Test log | The HTML report (`wtk-report/index.html`) and JUnit XML |
| Visualizer screenshots | `screenshots = "on-failure"` or `"every-step"` |

## What's different

- **Strict matching.** A mapped object in TestComplete may silently resolve to the first of several
  matches. WinTestKit fails when a locator matches more than one element, so ambiguous mappings
  surface at the line that is wrong. Expect to add `within=` scopes while migrating.
- **UI Automation only.** There is no image-based or OCR recognition. Controls a screen reader can't
  see can't be tested; for WPF that is rare.
- **No recorder.** Use the Spy to build pages and write tests in Python; the editor
  completes element names from your pages.
- **Code review and version control.** Pages and tests are plain Python files that diff, review
  and merge like any other code.

## A migrated test

A keyword test that signs in and checks the welcome text becomes a page and a test function:

```python
# pseudo-code
def test_invalid_login(main: MainPage) -> None:
    main.username.type("admin")
    main.password.type("wrong")
    main.sign_in.click()
    expect(main.status).to_have_text("Invalid credentials")
```

A data-driven loop over a table becomes a parametrized test:

```python
# pseudo-code
@pytest.mark.parametrize(
    ("username", "password", "message"),
    [
        ("admin", "secret", "Welcome, admin"),
        ("admin", "nope", "Invalid credentials"),
        ("guest", "secret", "Invalid credentials"),
        ("", "", "Invalid credentials"),
    ],
)
```

## Suggested order

1. Configure the application in `pyproject.toml` and check the machine with `wtk doctor`.
2. Translate the NameMapping for one window into a `Page`, using the Spy to confirm each
   locator. Run **Check All Elements** in VS Code (or `wtk check`) until it is green.
3. Move the tests that use that window, replacing checkpoints with `expect` and removing explicit
   waits.
4. Repeat per window, then switch CI from TestExecute to `wtk run` ([CI](ci.md)).
