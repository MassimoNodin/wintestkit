import { execFile } from "node:child_process";
import * as path from "node:path";
import { promisify } from "node:util";
import * as vscode from "vscode";
const execute = promisify(execFile);

export async function executableIcon(
  file: string,
): Promise<vscode.Uri | undefined> {
  if (process.platform !== "win32") return;
  const encoded = Buffer.from(file, "utf8").toString("base64");
  const script =
    "Add-Type -AssemblyName System.Drawing; $icon=$null; $bitmap=$null; $stream=$null; try { " +
    "$file=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" +
    encoded +
    "')); " +
    "if (![IO.Path]::IsPathRooted($file)) { $name=[IO.Path]::GetFileNameWithoutExtension($file); $processes=[Diagnostics.Process]::GetProcessesByName($name); try { if ($processes.Length) { $file=$processes[0].MainModule.FileName } } finally { foreach ($entry in $processes) { $entry.Dispose() } } }; " +
    "if ([IO.Path]::IsPathRooted($file)) { $icon=[Drawing.Icon]::ExtractAssociatedIcon($file) }; if ($icon) { $bitmap=$icon.ToBitmap(); $stream=[IO.MemoryStream]::new(); $bitmap.Save($stream,[Drawing.Imaging.ImageFormat]::Png); [Convert]::ToBase64String($stream.ToArray()) } " +
    "} finally { if ($stream) {$stream.Dispose()}; if ($bitmap) {$bitmap.Dispose()}; if ($icon) {$icon.Dispose()} }";
  try {
    const { stdout } = await execute(
      path.join(
        process.env.SystemRoot || "C:\\Windows",
        "System32",
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe",
      ),
      [
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
        Buffer.from(script, "utf16le").toString("base64"),
      ],
      { windowsHide: true, timeout: 8000, maxBuffer: 262144 },
    );
    const png = stdout.trim();
    if (/^[A-Za-z0-9+/]+={0,2}$/.test(png))
      return vscode.Uri.parse("data:image/png;base64," + png);
  } catch {
    return;
  }
}
