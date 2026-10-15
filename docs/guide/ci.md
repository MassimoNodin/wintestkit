# Running UI tests in CI

UI Automation needs a real, **interactive, unlocked desktop**: the build agent must run inside a
logged-on user session, not as a Windows service, and the session must never lock. Most CI
failures of UI tests come from the machine setup, not the tests. Make `wtk doctor` the first step
of every pipeline so a bad machine fails in seconds with a clear reason.

## Prepare a self-hosted runner

1. **Use a dedicated machine or VM and user account** for UI tests. Install the application under
   test, Python 3.12+ and `uv` (or pip).
2. **Log on automatically.** Configure auto-logon for the test account, for example with
   [Sysinternals Autologon](https://learn.microsoft.com/sysinternals/downloads/autologon), which
   stores the password encrypted.
3. **Run the agent as an interactive process, not a service.**
   - GitHub Actions: run `config.cmd` and answer **No** when asked to run as a service. Start
     `run.cmd` at logon, for example with a Task Scheduler task triggered **At log on** of the test
     user with **Run only when user is logged on**.
   - Azure Pipelines: configure the agent with
     `config.cmd --runAsAutoLogon --windowsLogonAccount <user> --windowsLogonPassword <password>`,
     which sets up auto-logon and starts the agent interactively.
4. **Never lock the session.** Turn off the screen saver and the lock screen timeout, and set the
   display and sleep timeouts to *Never* (`powercfg /change monitor-timeout-ac 0` and
   `powercfg /change standby-timeout-ac 0`). Check that no group policy (*Interactive logon:
   Machine inactivity limit*, screen saver policies) locks it anyway.
5. **Fix the resolution and scaling.** Use the same resolution and display scale (100% is
   simplest) as the machines where tests are written. Screenshots, mouse coordinates and
   layout-dependent behaviour change with them; `wtk doctor` reports the current scale.
6. **Match the elevation.** UI Automation can't control an elevated (administrator) application
   from a non-elevated process. If the application requires administrator rights, start the agent
   elevated too (a Task Scheduler task with **Run with highest privileges**).

### Remote Desktop

Disconnecting a Remote Desktop session **locks** it, and tests then fail (`wtk doctor` reports
*Desktop is unlocked* as failed).
To leave a machine you've been using over RDP, move the session to the console instead of
disconnecting. From an administrator command prompt **inside** the RDP session:

```bat
tscon %sessionname% /dest:console
```

The RDP window closes and the session keeps running unlocked. Also, a minimized RDP window stops
rendering, which breaks screenshots and mouse input; keep it open or use `tscon`.

## GitHub Actions

```yaml
name: UI tests
on:
  push:
  workflow_dispatch:

jobs:
  ui-tests:
    runs-on: [self-hosted, windows, ui-tests]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --locked
      - name: Check environment
        run: uv run wtk doctor
      - name: Run UI tests
        run: uv run wtk run --junit junit.xml
      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: ui-test-report
          path: |
            wtk-report/
            junit.xml
```

## Azure DevOps

```yaml
trigger:
  - main

pool:
  name: UI Tests # self-hosted agents running interactively

steps:
  - checkout: self
  - script: pip install uv && uv sync --locked
    displayName: Install dependencies
  - script: uv run wtk doctor
    displayName: Check environment
  - script: uv run wtk run --junit junit.xml
    displayName: Run UI tests
  - task: PublishTestResults@2
    condition: always()
    inputs:
      testResultsFormat: JUnit
      testResultsFiles: junit.xml
  - task: PublishPipelineArtifact@1
    condition: always()
    inputs:
      targetPath: wtk-report
      artifact: ui-test-report
```

## Artifacts

Always publish `wtk-report/`, also when the run fails: it contains the HTML report, `results.json`
and, for each failed test, screenshots of the window and desktop and a dump of the UI tree. JUnit
XML (`--junit`) lets the CI system show test results natively.

## Exit codes

`wtk doctor` exits with **3** when a check fails (warnings don't fail it). `wtk run` exits with
**1** when tests fail, **3** when the environment isn't ready and **5** when no tests were
collected. See [Running tests](running-tests.md#exit-codes).

## GitHub-hosted runners

The repository CI checks the Python package and extension without building an example app or
running the legacy app-dependent suites. For your own UI tests, use a self-hosted Windows
runner with your application installed and an interactive, unlocked session. Keep your UI
pipeline separate from checks that do not require a desktop.
