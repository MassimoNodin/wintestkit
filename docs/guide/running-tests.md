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
wtk run --replay retain-on-failure --replay-fps 5 --replay-scope window
wtk run -- -p no:cacheprovider --maxfail=3  # raw pytest arguments after --
```

| Option | Meaning |
|---|---|
| `TESTS` | Test ids or paths |
| `--launch {per-test,attach}` | How to get the application (see below) |
| `--timeout SECONDS` | Default auto-wait |
| `--app PATH` | Application executable |
| `--input-mode {pattern,mouse}` | Default click strategy |
| `--screenshots {off,on-failure,every-step}` | When to capture screenshots |
| `--highlight` | Flash each element before acting |
| `--slowmo MS` | Pause after every action (for watching a run) |
| `--report DIR` / `--no-report` | Report directory / don't write a report |
| `--no-html` | Write `results.json` but not `index.html` (the VS Code Testing view uses this) |
| `--junit PATH` | Also write JUnit XML |
| `--events URL` | Stream run events (see below) |
| `--replay {off,on,retain-on-failure}` | Record continuous screenshot replays; off by default |
| `--replay-fps FPS` | Sampling rate, greater than 0 and at most 30 (default 15) |
| `--replay-scope {window,desktop}` | Capture the application window (default) or opt into the full desktop |
| `-k EXPR`, `-m EXPR`, `-x`, `--lf` | As in pytest |

Plain `pytest` works the same way: the plugin activates in projects with `wintestkit.yaml`
or a legacy `[tool.wintestkit]` table, with matching `--wtk-*` options. Run
`pytest --help` to see them.

## Configuration

Shared settings live in `wintestkit.yaml`; machine overrides live in ignored
`wintestkit.local.yaml`. The Test Target gear opens their custom YAML editor.
Precedence, highest first: CLI, environment, local YAML, local TOML, shared YAML,
legacy `[tool.wintestkit]` in `pyproject.toml`, defaults. Local TOML uses that same table.

Shared `wintestkit.yaml` (commit this):

```yaml
launch: per-test
timeout: 10
input_mode: pattern
screenshots: on-failure
report_dir: wtk-report
python_paths: ["."]
app:
  process: Orders.exe
  startup_timeout: 30
  close_timeout: 10
```

Local `wintestkit.local.yaml` (do not commit this):

```yaml
app:
  path: C:/Program Files/Contoso/Orders.exe
  args: ["--no-splash"]
  cwd: C:/Program Files/Contoso
highlight_actions: false
slow_mo_ms: 0
```

Shared YAML rejects application paths. Legacy paths remain supported; move them from
`pyproject.toml` to local YAML to keep them machine-specific. Keep secrets out of shared
configuration; advanced `app.env` settings accept string values in local YAML.
Relative paths resolve from the project directory. Environment variables include
`WTK_APP_PATH`, `WTK_LAUNCH`, `WTK_TIMEOUT`, `WTK_INPUT_MODE`, `WTK_SCREENSHOTS`, `WTK_REPLAY`,
`WTK_REPLAY_FPS`, and `WTK_REPLAY_SCOPE`; `WTK_LOG`
sets the log level of the `wintestkit` logger (`DEBUG`, `INFO`, …).
Replay limits are configurable with `replay_max_frames` (default 3000) and `replay_max_bytes`
(default 104857600), including environment overrides `WTK_REPLAY_MAX_FRAMES` and
`WTK_REPLAY_MAX_BYTES`. Capture is best-effort and may truncate at these limits. Window capture
is the privacy-conscious default; desktop capture is opt-in and may include unrelated on-screen
content. Keep tracing off unless needed.

## Launch modes

The `app` fixture provides the application under test:

| Mode | Behaviour |
|---|---|
| `per-test` (default; **Launch for tests** in the Test Target view) | Launch a fresh app for every test and close it when the test ends. A copy that is already running is closed first, so every test starts from a clean app and nothing is left running afterwards |
| `attach` | Attach to an already running instance (`app.process`, or the exe name of `app.path`); never launch or close it |

The Test Target view offers exactly these two choices, and the setting it saves is the only one that decides how the app is obtained: **Attach** (use the app that is
running) and **Launch for tests** (WinTestKit starts the app and closes it when the tests finish).

Override the mode for one test with a marker:

```python
# pseudo-code
@pytest.mark.wtk(launch="per-test")
def test_first_start_shows_the_welcome_page(app): ...
```

### Resetting state between tests

Each test gets a fresh application, so most tests need no reset. If your application keeps state
outside the process (a database, files, a server), put the reset in an autouse fixture; the demo
project uses the application's own **File > Reset**:

```python
# pseudo-code
@pytest.fixture(autouse=True)
def reset_demo(main: MainPage) -> None:
    """Start every test from a clean app, including any state kept outside the process."""
    main.menu_file.click()
    main.menu_reset.click()
    expect(main.status).to_have_text("Ready")
```

Other options: close open dialogs and navigate home, restore test data through an API or
database, or `attach` to a running app when you need to inspect it by hand.

## Fixtures and markers

| Fixture | Scope | Provides |
|---|---|---|
| `app` | test | The `App` under test, according to the launch mode |
| `page` | test | A factory: `page(MainPage)` returns `MainPage(app)` |
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
`wtk-report/artifacts/<test>/` (`window.webp`, `desktop.webp`, `tree.txt`). Failure and step
screenshots, like replay frames, use lossless WebP with unchanged pixels and dimensions.
Older PNG reports remain readable. Results are also saved
as `wtk-report/results.json`.

WinTestKit clears only the files it created in the report directory (`index.html`,
`results.json`, `artifacts/`) at the start of a run. To regenerate `index.html` from
`results.json`, or open it:

```powershell
wtk report --open
wtk report out/report
```

For external tools that require PNG, import `Path` from `pathlib` and `screenshot` from
`wintestkit.uia`, then explicitly export with
`screenshot.save(screenshot.capture_screen(), Path("desktop.png"))`.

Capture functions return WebP bytes by default. `screenshot.save` writes the format selected by
the `.webp` or `.png` filename extension, converting losslessly when needed.

## Test replay

Record a continuous, timestamped screenshot recording of the app's window, played back in the report as a **Test Replay** (the `replay` options control it):

```powershell
wtk run --replay on
wtk run --replay retain-on-failure --replay-fps 5
wtk report --open
```

Or save the settings in shared or local YAML:

```yaml
replay: "retain-on-failure"
replay_fps: 15
replay_scope: window
replay_max_frames: 3000
replay_max_bytes: 104857600
```

Open a test's replay from its **Open Test Replay** button or by clicking a step. Playback runs on
the recording's own clock, so the replay keeps the pace of the real run, including waits where
the screen does not change; the speed can be set from 0.5× to 4×. The timeline places each step's dot
where the step really started, so the playhead moves at a constant speed; the **Timeline** menu
next to the speed control switches to equal steps, which spaces the dots evenly and moves the
playhead across each gap in proportion to how long that step took. Drag the timeline, click a dot or a thumbnail, or use the arrow keys to move between steps,
and Space to play or pause. This is visual replay, not an interactive UI Automation snapshot or an
MP4 recording.

Recording is off by default for `pytest` and `wtk run` (runs started from the VS Code Testing view
turn it on unless a replay mode is set) and independent of the existing screenshots setting. A background
worker targets 15 frames per second, with additional capture requests after actions. It keeps
only changed frames as lossless WebP images (`replay/*.webp`), preserving their original pixels
and dimensions. Older PNG recordings remain readable; failure and step screenshots also use WebP.
The worker drops missed sampling ticks rather than building a queue, and stops at
the per-test frame or byte limit. The report marks truncated and unavailable recordings.
Capture failures do not change the test outcome. Passing and skipped replays are deleted in
`retain-on-failure` mode; failed tests and setup/teardown errors retain them.

Window mode renders the application's main window without copying overlapping desktop
windows. Minimized or closed windows may have no frames; applications that do not support
window rendering can produce blank frames. Separate popups are not included. Choose
`--replay-scope desktop` explicitly when you need to see popups and focus changes: this records
the entire virtual desktop, including other applications. All replays can contain visible
passwords or other sensitive data; screenshot pixels are not redacted. Review artifacts before
sharing them. `--no-report` disables recording. Copy the whole report directory, including
`artifacts/`, when moving or sharing a recording; `wtk report` can regenerate the player from
saved results but cannot create frames for an older run.

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
