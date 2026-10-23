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
| `--report DIR` / `--no-report` | Report directory / disable reports and automatic capture artifacts |
| `--no-html` | Write `results.json` but not `index.html` (the VS Code Testing view uses this) |
| `--junit PATH` | Also write JUnit XML |
| `--events URL` | Stream run events (see below) |
| `--replay {off,on,retain-on-failure}` | Record continuous screenshot replays; off by default |
| `--replay-fps FPS` | Sampling rate, greater than 0 and at most 30 (default 15) |
| `--replay-scope {window,desktop}` | Capture the application window (default) or opt into the full desktop |
| `--wtk-ui-tree-diff` | Opt into UI tree diff evidence against prior passing baselines (pytest flag) |
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
highlight_color: "#FF0000"   # outline colour, quoted because # starts a YAML comment
slow_mo_ms: 0
```

Prefer a path relative to the project directory (for example `bin/Debug/Orders.exe`) for `app.path`
in shared YAML. An absolute path there is accepted, but it only works on machines that have the file
in exactly that place, so teammates and CI fail to start the application unless they override it in
local YAML; the VS Code Configuration page warns about it. Keep machine-specific paths in local YAML.
Legacy paths remain supported; move machine-specific ones from `pyproject.toml` to local YAML. Keep secrets out of shared
configuration; advanced `app.env` settings accept string values in local YAML.
Relative paths resolve from the project directory. Environment variables include
`WTK_APP_PATH`, `WTK_LAUNCH`, `WTK_TIMEOUT`, `WTK_INPUT_MODE`, `WTK_SCREENSHOTS`, `WTK_REPLAY`,
`WTK_REPLAY_FPS`, `WTK_REPLAY_SCOPE`, and `WTK_OBJECT_PREVIEWS`; `WTK_LOG`
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
outside the process (a database, files, a server), put the reset in an autouse fixture; for
example, using the application's own **File > Reset**:

```python
# pseudo-code
@pytest.fixture(autouse=True)
def reset_app(main: MainPage) -> None:
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

`wtk run --no-report` (plain pytest: `--wtk-no-report`) disables automatic failure
and step screenshots, UI tree evidence, replays and saved-object previews, as well
as report output. It does not delete older artifacts, suppress test stdout or
explicit event/JUnit outputs, or prevent screenshots explicitly requested by your
own test code. `--no-html` only suppresses HTML and is not a privacy switch.
With reports enabled, failure capture can include the whole desktop, including
when a failing test has no `app` fixture; keep reports private and review them.

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

## Check Element captures

Click a declared single element's **Check exists** CodeLens in VS Code to save two images
after a successful unique lookup: a clean element crop and its owning application window
with the element outlined in red. Only that element is checked and captured. Test runs, flows,
discovery, Spy inspection, **Highlight**, and whole-page checks do not update these images.
Hover over the element name in Python to view the saved crop and capture time, with links to
open the full crop or app context. Viewing an image never takes another capture.

Capture is best-effort and never changes the check result. Password or sensitive targets,
unavailable windows, and untrustworthy or partially visible bounds are skipped. Capture uses
the owning window rather than a desktop screenshot, without bringing it forward. It may be
unavailable for applications whose windows cannot be captured reliably.

A bounded privacy scan also skips windows with recognized sensitive controls, or when the
control tree cannot be checked completely within its limits. This is not a guarantee that all
secrets can be detected in application pixels. Derived grid rows and cells do not replace the
image belonging to the declared grid.

The latest published pair and its manifest live under `object-previews/` in the project root,
keyed by the declaring page member. This is separate from `wtk-report/`: clearing reports
does not remove saved-object images. Copy this directory with the page source when moving or
sharing the project. A new capture deletes the pair it replaces; one an open reader still holds
is removed the next time that element is captured.

Images can contain sensitive application data, including other controls in the window image.
Review them before committing or sharing the project. Disable future capture in shared
`wintestkit.yaml` or machine-specific `wintestkit.local.yaml`:

```yaml
object_previews: false
```

The environment override is `WTK_OBJECT_PREVIEWS=false`. Disabling capture does not delete
existing images; remove `object-previews/` separately if they must not be retained.

Whether the images are committed is one decision for the whole repository, so it lives only in
the shared `wintestkit.yaml` (a machine's own file cannot change it) and stays off until
`object_previews` is on:

```yaml
object_previews: true
object_previews_share: true   # default false
```

With `object_previews_share` off, WinTestKit adds `object-previews/` to `.gitignore` the first time
it saves a capture, so images stay on each machine. Turning it on removes that exact line (a rule
you wrote differently, such as `/object-previews/`, is left alone and must be removed by hand).
Images Git already tracks stay tracked when sharing is turned off; run
`git rm -r --cached object-previews` to stop tracking them. In VS Code, **Share Check Element
captures in the repository** is in Repository Settings under Evidence and is disabled until
**Save Check Element captures** is enabled there; User Settings only show its state and a button
to Repository Settings.

A failed check or skipped capture keeps the previous pair. Treat it as a saved reference,
not proof of the current UI. Run **Check exists** again after changing a locator or screen.
Older automatic test captures are ignored by the hover until an explicit check replaces them.

## UI tree diff evidence

Enable with `pytest --wtk-ui-tree-diff`. On successful tests, WinTestKit captures a bounded main
window tree and keeps one baseline per test ID and configured app target. Later failures for that
same pair write a text diff to `tree-diff.txt` in the test's artifacts and record it as `treeDiff`
in `results.json`; the HTML report does not display it. Baselines are capped at 512 KiB each, and
the baseline directory keeps at most 500 files, pruning oldest entries. Screen coordinates are
removed before comparison; names, AutomationIds, classes, and hierarchy remain.

Capture is disabled with `--wtk-no-report` or `--wtk-screenshots=off`, and is opt-in by default.
Baseline capture and writes are best-effort, so they do not fail a passing test. Keep the local
report directory private: tree text can contain application labels or identifiers.

The comparison covers the bounded main window, not a selected failing container. It requires a
prior passing run of the same test and target and is a structural text diff, not a semantic or
visual assertion. There may be no useful diff when a test has no `app` fixture or the UIA tree is
unavailable.

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
