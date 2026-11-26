# Save diagnostics

Use **WinTestKit: Save Diagnostics…** from the Command Palette, or choose **Save diagnostics** from an error or the setup panel. Choose what to collect and optionally describe what went wrong. Environment details are always included. The log, doctor checks and WinTestKit settings are selected by default. The Spy trace is optional and may contain values read from your application. Test run reports are not collected.

The extension writes a temporary folder and opens its README for review. Choose **Open folder** to inspect or edit every file. Select **Save zip…** to save the current folder contents locally, or **Cancel** to delete the temporary folder. Nothing is uploaded. Move the zip yourself only after reviewing it.

The bundle includes version and interpreter information, compatibility policy, server and inspector state, and available last failures. Selected files can include the WinTestKit log, `doctor.json`, effective VS Code settings and WinTestKit project configuration. The doctor command does not launch the application. Files are limited to 5 MB, retaining the end when truncated.

User name, computer name, domain, home path and email addresses are replaced in collected text; settings whose keys resemble passwords, tokens, secrets, keys or credentials are also redacted. Counts and collection errors appear in the README and manifest. Automatic redaction cannot identify every sensitive value: inspect the contents, including application names and paths, before sharing. Edits made during review are included as written.

A maintainer can unzip the bundle and point a coding agent at `README.md`. Start with the last failure, log errors and doctor checks.

The optional **Inspector injector log** is selected by default. It includes `%APPDATA%\Snoop\SnoopLog.txt` as `logs/snoop-injector.log`, redacted and capped at 5 MB. If absent, the summary records it as not present.
