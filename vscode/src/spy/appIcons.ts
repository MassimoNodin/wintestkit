import { execFile } from "node:child_process";
import * as path from "node:path";
import { promisify } from "node:util";

const run = promisify(execFile);

export function parseApplicationIcons(output: string): Record<string, string> {
  const value: unknown = JSON.parse(output.replace(/^\uFEFF/, "").trim());
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value).filter(
      ([pid, icon]) =>
        /^\d+$/.test(pid) &&
        typeof icon === "string" &&
        icon.length < 262144 &&
        /^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(icon),
    ),
  );
}

export async function readApplicationIcons(
  pids: number[],
): Promise<Record<string, string>> {
  const ids = [
    ...new Set(pids.filter((pid) => Number.isSafeInteger(pid) && pid > 0)),
  ];
  if (process.platform !== "win32" || !ids.length) return {};
  const script = [
    "Add-Type -AssemblyName System.Drawing",
    "$icons = @{}; $paths = @{}",
    "foreach ($processId in @(" + ids.join(",") + ")) {",
    "  $process = $null",
    "  try {",
    "    $process = [System.Diagnostics.Process]::GetProcessById($processId)",
    "    $file = $process.MainModule.FileName",
    "    if (!$paths.ContainsKey($file)) {",
    "      $icon = $null; $bitmap = $null; $stream = $null",
    "      try {",
    "        $icon = [System.Drawing.Icon]::ExtractAssociatedIcon($file)",
    "        if ($icon) {",
    "          $bitmap = $icon.ToBitmap()",
    "          $stream = [System.IO.MemoryStream]::new()",
    "          $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)",
    "          $paths[$file] = 'data:image/png;base64,' + [Convert]::ToBase64String($stream.ToArray())",
    "        }",
    "      } finally {",
    "        if ($stream) { $stream.Dispose() }",
    "        if ($bitmap) { $bitmap.Dispose() }",
    "        if ($icon) { $icon.Dispose() }",
    "      }",
    "    }",
    "    if ($paths.ContainsKey($file)) { $icons[[string]$processId] = $paths[$file] }",
    "  } catch {} finally {",
    "    if ($process) { $process.Dispose() }",
    "  }",
    "}",
    "ConvertTo-Json -InputObject $icons -Compress",
  ].join("\n");
  try {
    const { stdout } = await run(
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
      {
        windowsHide: true,
        timeout: 10000,
        maxBuffer: 8 * 1024 * 1024,
        encoding: "utf8",
      },
    );
    return parseApplicationIcons(stdout);
  } catch {
    return {};
  }
}
