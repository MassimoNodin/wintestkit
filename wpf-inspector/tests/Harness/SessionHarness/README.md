# Session harness

Run SessionHarness --fake <bootstrap-path> to host one in-process session with canned inspection responses. The bootstrap path must be under the normal agent bootstrap root and identify the harness process. The harness waits up to 10 seconds for the file, allowing a launcher to create it after obtaining the process ID. The bootstrap is consumed by the regular validated reader. The process exits when the session closes or times out.

Exit codes: 0 for a normal session end, 1 for bootstrap or session failure, and 2 for invalid arguments.
