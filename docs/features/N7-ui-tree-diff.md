# N7: opt-in UI tree diff evidence

Enable with `pytest --wtk-ui-tree-diff`. On successful tests, WinTestKit captures a bounded main
window tree and keeps one baseline per test ID and configured app target. Later failures for that
same pair can show a text diff link in the HTML report. Baselines are capped at 512 KiB each, and
the baseline directory keeps at most 500 files, pruning oldest entries. Screen coordinates are
removed before comparison; names, AutomationIds, classes, and hierarchy remain.

Capture is disabled with `--wtk-no-report` or `--wtk-screenshots=off`, and is opt-in by default.
Baseline capture and writes are best-effort, so they do not fail a passing test. Keep the local
report directory private: tree text can contain application labels or identifiers.

The comparison covers the bounded main window, not a selected failing container. It requires a
prior passing run of the same test and target and is a structural text diff, not a semantic or
visual assertion. There may be no useful diff when a test has no `app` fixture or the UIA tree is
unavailable.
