# Running tests

## `wtk run`

`wtk run` runs pytest with the WinTestKit plugin from the project root. It first runs the quick
environment checks of `wtk doctor` (skip them with `--no-env-check`).

```powershell
wtk run                                   # every test
wtk run tests/test_login.py               # one file
wtk run tests/test_login.py::test_valid_login
wtk run -k login -x                       # pytest keyword filter, stop at the first failure
wtk run --lf                              # re-run the last failures
wtk run --launch per-test --timeout 20    # override configuration for this run
wtk run --junit junit.xml --report out/report
wtk run -- -p no:cacheprovider --maxfail=3  # raw pytest arguments after --
```

| Option | Meaning |
|---|---|
| `TESTS` | Test ids or paths |
| `--launch {per-test,per-session,attach}` | How to get the application (see below) |
| `--timeout SECONDS` | Default auto-wait |
| `--app PATH` | Application executable |
| `--input-mode {pattern,mouse}` | Default click strategy |
| `--screenshots {off,on-failure,every-step}` | When to capture screenshots |
| `--highlight` | Flash each element before acting |
| `--slowmo MS` | Pause after every action (for watching a run) |
| `--report DIR` / `--no-report` | Report directory / don't write a report |
| `--junit PATH` | Also write JUnit XML |
| `--events URL` | Stream run events (see below) |
| `-k EXPR`, `-m EXPR`, `-x`, `--lf` | As in pytest |

Plain `pytest` works the same way: the plugin activates in any project with a `[tool.wintestkit]`
table and has matching `--wtk-*` options (`pytest --wtk-launch per-test --wtk-timeout 20`). Run
`pytest --help` to see them.

## Configuration

Settings live in `pyproject.toml`. Precedence, highest first: command-line options, `WTK_*`
environment variables, `[tool.wintestkit]`, defaults.

```toml
[tool.wintestkit]
launch = "per-session"        # per-test | per-session | attach
timeout = 10.0                # default auto-wait in seconds
input_mode = "pattern"        # pattern | mouse
screenshots = "on-failure"    # off | on-failure | every-step
report_dir = "wtk-report"
highlight_actions = false
slow_mo_ms = 0
python_paths = ["."]          # where the CLI and VS Code import screens from

[tool.wintestkit.app]
path = "C:/Program Files/Contoso/Orders.exe"
args = ["--no-splash"]
cwd = "C:/Program Files/Contoso"
env = { ORDERS_ENV = "test" }
process = "Orders.exe"        # process to attach to (default: the exe name of path)
startup_timeout = 30.0
close_timeout = 10.0
```

Relative paths are relative to the directory of `pyproject.toml`. The environment variables are
`WTK_APP_PATH`, `WTK_LAUNCH`, `WTK_TIMEOUT`, `WTK_INPUT_MODE` and `WTK_SCREENSHOTS`; `WTK_LOG`
sets the log level of the `wintestkit` logger (`DEBUG`, `INFO`, …).

## Launch modes

The `app` fixture provides the application under test:

| Mode | Behaviour |
|---|---|
| `per-session` (default) | Launch once for the whole run and close it at the end. If a test closes or crashes the application, the next test starts it again |
| `per-test` | Launch before and close after every test: slow but fully isolated |
| `attach` | Attach to an already running instance (`app.process`, or the exe name of `app.path`); never launch or close it |

Override the mode for one test with a marker:

```python
# pseudo-code
@pytest.mark.wtk(launch="per-test")
def test_first_start_shows_the_welcome_page(app): ...
```

### Resetting state between tests

With `per-session`, tests share one application instance, so each test should start from a known
state. Put the reset in an autouse fixture; the demo project uses the application's own
**File > Reset**:

```python
# examples/demo-tests/conftest.py
@pytest.fixture(autouse=True)
def reset_demo(main: MainScreen) -> None:
    """Start every test from a clean app: the app is shared by the whole session."""
    main.menu_file.click()
    main.menu_reset.click()
    expect(main.status).to_have_text("Ready")
```

Other options: close open dialogs and navigate home, restore test data through an API or
database, or use `per-test` for the few tests that need a fresh process.

## Fixtures and markers

| Fixture | Scope | Provides |
|---|---|---|
| `app` | test | The `App` under test, according to the launch mode |
| `screen` | test | A factory: `screen(MainScreen)` returns `MainScreen(app)` |
| `wtk_config` | session | The effective `WtkConfig` |

`@pytest.mark.wtk(launch=..., timeout=...)` overrides the launch mode or default timeout for one
test. Use ordinary pytest markers and paths to organize suites (`wtk run -m smoke`,
`wtk run tests/orders`).

## Report

Every run writes `wtk-report/index.html` (or `--report DIR`) and prints its path:

```text
Report: C:/work/orders-tests/wtk-report/index.html
```

The report is a single HTML file that opens from disk without a server. It has summary chips that
filter by outcome, a search box, and per test: the failure message and location, the resolution
diagnostic, every step with its duration (the failed step is highlighted), screenshots, a link to
the UI tree dump and captured stdout, stderr and logs. Failure artifacts are stored under
`wtk-report/artifacts/<test>/` (`window.png`, `desktop.png`, `tree.txt`). Results are also saved
as `wtk-report/results.json`.

WinTestKit clears only the files it created in the report directory (`index.html`,
`results.json`, `artifacts/`) at the start of a run. To regenerate `index.html` from
`results.json`, or open it:

```powershell
wtk report --open
wtk report out/report
```

## JUnit XML

`wtk run --junit junit.xml` (pytest's `--junitxml`) writes JUnit XML for CI systems.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | All tests passed |
| 1 | Some tests failed |
| 2 | Usage or configuration error |
| 3 | The environment is not ready (see `wtk doctor`) |
| 4 | Interrupted or internal error |
| 5 | No tests were collected |

## Events

`--events` streams the run as newline-delimited JSON, either to a TCP listener
(`--events tcp://127.0.0.1:5000`) or to a file (`--events events.ndjson`). VS Code uses this to
update the Test Explorer live. The events are `session_start`, `collected`, `test_start`, `step`,
`test_output`, `test_end` and `session_end`; their exact shapes are defined by
[`schemas/events.schema.json`](../../schemas/events.schema.json). `session_end` includes the run
summary and the paths of the report and JUnit file.
