import { execFile } from "node:child_process";
import * as path from "node:path";
import { promisify } from "node:util";

const run = promisify(execFile);
const applicationIcons = new Map<string, Promise<string | undefined>>();

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

async function runScript(script: string): Promise<string> {
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
  return stdout;
}

async function extractApplicationIcons(
  files: string[],
): Promise<Record<string, string>> {
  const script = [
    "Add-Type -AssemblyName System.Drawing",
    "$icons = @{}",
    "$files = @(" +
      files.map((file) => "'" + file.replace(/'/g, "''") + "'").join(",") +
      ")",
    "for ($index = 0; $index -lt $files.Count; $index++) {",
    "  $icon = $null; $bitmap = $null; $stream = $null",
    "  try {",
    "    $icon = [System.Drawing.Icon]::ExtractAssociatedIcon($files[$index])",
    "    if ($icon) {",
    "      $bitmap = $icon.ToBitmap()",
    "      $stream = [System.IO.MemoryStream]::new()",
    "      $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)",
    "      $icons[[string]$index] = 'data:image/png;base64,' + [Convert]::ToBase64String($stream.ToArray())",
    "    }",
    "  } catch {} finally {",
    "    if ($stream) { $stream.Dispose() }",
    "    if ($bitmap) { $bitmap.Dispose() }",
    "    if ($icon) { $icon.Dispose() }",
    "  }",
    "}",
    "ConvertTo-Json -InputObject $icons -Compress",
  ].join("\n");
  try {
    return parseApplicationIcons(await runScript(script));
  } catch {
    return {};
  }
}

/** The executable of each process, by pid; a process that cannot be read (elevated) is left out. */
export async function readApplicationPaths(
  pids: number[],
): Promise<Record<string, string>> {
  const ids = [
    ...new Set(pids.filter((pid) => Number.isSafeInteger(pid) && pid > 0)),
  ];
  if (process.platform !== "win32" || !ids.length) return {};
  const script = [
    "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)",
    "$paths = @{}",
    "foreach ($processId in @(" + ids.join(",") + ")) {",
    "  $process = $null",
    "  try {",
    "    $process = [System.Diagnostics.Process]::GetProcessById($processId)",
    "    $file = $process.MainModule.FileName",
    "    if ($file) { $paths[[string]$processId] = $file }",
    "  } catch {} finally {",
    "    if ($process) { $process.Dispose() }",
    "  }",
    "}",
    "ConvertTo-Json -InputObject $paths -Compress",
  ].join("\n");
  try {
    const output = await runScript(script);
    const paths: unknown = JSON.parse(output.replace(/^\uFEFF/, "").trim());
    if (!paths || typeof paths !== "object" || Array.isArray(paths)) return {};
    return Object.fromEntries(
      ids.flatMap((pid) => {
        const file: unknown = (paths as Record<string, unknown>)[String(pid)];
        return typeof file === "string" &&
          path.win32.isAbsolute(file) &&
          !file.includes("\0")
          ? [[String(pid), path.win32.normalize(file)]]
          : [];
      }),
    );
  } catch {
    return {};
  }
}

export async function readApplicationIcons(
  pids: number[],
): Promise<Record<string, string>> {
  try {
    const processes = Object.entries(await readApplicationPaths(pids)).map(
      ([pid, file]) => [pid, file.toLowerCase()] as const,
    );
    const missing = [...new Set(processes.map(([, file]) => file))].filter(
      (file) => !applicationIcons.has(file),
    );
    if (missing.length) {
      const extraction = extractApplicationIcons(missing);
      missing.forEach((file, index) => {
        applicationIcons.set(
          file,
          extraction.then((icons) => {
            const icon = icons[String(index)];
            if (!icon) applicationIcons.delete(file);
            return icon;
          }),
        );
      });
    }
    const icons = await Promise.all(
      processes.map(async ([pid, file]) => {
        const icon = await applicationIcons.get(file);
        return icon ? [[pid, icon]] : [];
      }),
    );
    return Object.fromEntries(icons.flat());
  } catch {
    return {};
  }
}
