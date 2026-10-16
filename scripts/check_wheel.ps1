# Build the wintestkit wheel and smoke-test it in a fresh virtual environment.
# Usage: pwsh scripts/check_wheel.ps1   (from any directory)
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo "python"
$dist = Join-Path $python "dist"
$venv = Join-Path ([IO.Path]::GetTempPath()) ("wtk-wheel-" + [Guid]::NewGuid().ToString("N"))

function Invoke-Checked {
    param([string]$Description, [scriptblock]$Command)
    Write-Host "==> $Description"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Description failed (exit $LASTEXITCODE)" }
}

try {
    if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
    Invoke-Checked "Build sdist and wheel" { uv build --directory $python }
    $wheel = Get-ChildItem $dist -Filter "wintestkit-*-py3-none-any.whl" | Select-Object -First 1
    if (-not $wheel) { throw "No py3-none-any wheel in $dist" }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($wheel.FullName)
    try {
        $names = $zip.Entries | ForEach-Object { $_.FullName }
    } finally {
        $zip.Dispose()
    }
    foreach ($required in @("wintestkit/py.typed", "wintestkit/report/template.html")) {
        if ($names -notcontains $required) { throw "Wheel is missing $required" }
    }
    if (-not ($names | Where-Object { $_ -like "wintestkit/scaffold/*.tmpl" })) {
        throw "Wheel is missing the scaffold templates"
    }
    foreach ($skill in @("SKILL.md", "references/api.md", "references/fixing-breakages.md", "references/migration-from-testcomplete.md")) {
        if ($names -notcontains "wintestkit/scaffold/skills/wintestkit-tests/$skill") { throw "Wheel is missing the agent skill file $skill" }
    }

    Invoke-Checked "Create virtual environment" { uv venv --python 3.12 $venv }
    $env:VIRTUAL_ENV = $venv
    $bin = Join-Path $venv "Scripts"
    Invoke-Checked "Install wheel" { uv pip install --python (Join-Path $bin "python.exe") $wheel.FullName pytest }

    Invoke-Checked "wtk --version" { & (Join-Path $bin "wtk.exe") --version }
    Write-Host "==> wtk doctor --json"
    $doctor = & (Join-Path $bin "wtk.exe") doctor --json | Out-String
    # Exit 3 means an environment check failed (e.g. no interactive desktop); the JSON is still valid.
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 3) { throw "wtk doctor failed (exit $LASTEXITCODE)" }
    $null = $doctor | ConvertFrom-Json
    Invoke-Checked "import wintestkit" { & (Join-Path $bin "python.exe") -c "import wintestkit; print(wintestkit.__version__)" }

    Write-Host "==> pytest plugin registered"
    $help = & (Join-Path $bin "python.exe") -m pytest --help | Out-String
    if ($help -notmatch "wtk-launch") { throw "pytest --help does not list --wtk-launch" }
    Write-Host "Wheel OK: $($wheel.Name)"
} finally {
    Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
    if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }
}
