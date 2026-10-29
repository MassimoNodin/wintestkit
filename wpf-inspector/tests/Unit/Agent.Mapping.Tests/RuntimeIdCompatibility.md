# Runtime-ID round-trip observations

Verified on Windows on 2026-10-27 with the local WinTestKit SDK (10.0.400).
Both test targets ran as x64 processes. The Agent also builds for net8.0-windows;
this record does not claim a net8 or x86 UIA round trip.

| Test target | Actual WPF UIA element ID | Same object's internal peer ID | Top-level window UIA ID |
| --- | --- | --- | --- |
| net10.0-windows (WindowsDesktop 10.0.11) | [7,35724,31157831] | [7,35724,31157831] | [42,76819838] |
| net48 (.NET Framework 4.8) | [7,54960,8446268] | [7,54960,8446268] | [42,93852164] |

In these executions, WPF controls exposed three-component runtime IDs with a
leading 7 and the current process ID as the second component. The remaining
component is opaque. Top-level HWND elements exposed two-component IDs beginning
with 42; the second component corresponded to the window handle in these runs.
These are observations, not mapping formulas or stable identifiers across runs.
The mapper compares complete arrays obtained through PeerRuntimeIdAdapter and
uses the separately supplied, verified native handle for HWND roots.

TwentyFourRealUiaSelectionsRoundTripToExactObjects records fresh actual arrays
through xUnit output on every run. It reads AutomationElement.FromHandle and
TreeWalker.RawViewWalker from an MTA worker while the owning STA Dispatcher runs,
then proves reference equality through ObjectRegistry for all 24 selections.
The same suite covers a real nested HwndHost/HwndSource, a Popup presentation root,
a custom ButtonAutomationPeer, and a Hyperlink content peer. The 32-candidate
two-Dispatcher test proves exactly one index build per Dispatcher.

Synthetic adapter tests cover duplicate IDs (ambiguous), an unowned peer,
adapter failure, scan-time ID changes, and deterministic time-budget exhaustion.
They supplement rather than replace the real System.Windows.Automation round trips.

All 37 pre-existing tests are retained. The shared WPF test collection keeps its
single Application alive until all test classes complete, avoiding WPF's
process-wide no-new-windows behavior after Application.Shutdown. Fixture windows
use ShowActivated=false and are closed in finally/Dispose; popup and nested HWND
sources are closed with their owning fixtures.

A selection resolved only after its window closes returns notFound because its
presentation source is gone. A peer that disconnects or changes identity between
indexing (or a cache hit) and registration returns stale. Invalid/foreign HWNDs
return notFound without falling back to peer matching.
