# Build the wintestkit wheel and smoke-test it in a fresh virtual environment.
# Usage: pwsh scripts/check_wheel.ps1   (from any directory)
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo "python"
$dist = Join-Path $python "dist"
$venv = Join-Path ([IO.Path]::GetTempPath()) ("wtk-wheel-" + [Guid]::NewGuid().ToString("N"))
$previousVirtualEnv = $env:VIRTUAL_ENV

function Invoke-Checked {
    param([string]$Description, [scriptblock]$Command)
    Write-Host "==> $Description"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Description failed (exit $LASTEXITCODE)" }
}

try {
    if ([IO.Path]::GetFullPath($dist) -ne [IO.Path]::GetFullPath((Join-Path $repo "python/dist"))) {
        throw "Refusing to clean an unexpected distribution directory: $dist"
    }
    if (Test-Path -LiteralPath $dist) { Remove-Item -LiteralPath $dist -Recurse -Force }
    Invoke-Checked "Build source distribution" { uv build --directory $python --sdist }
    $sdist = Get-ChildItem -LiteralPath $dist -Filter "wintestkit-*.tar.gz" | Select-Object -First 1
    if (-not $sdist) { throw "No source distribution in $dist" }
    Invoke-Checked "Build wheel from source distribution" { uv build $sdist.FullName --wheel --out-dir $dist }
    $distributions = Get-ChildItem -LiteralPath $dist -File | Where-Object { $_.Name -match '\.(whl|tar\.gz)$' }
    Invoke-Checked "Validate distribution metadata" { uv run --directory $python --locked twine check --strict $distributions.FullName }
    $wheel = Get-ChildItem -LiteralPath $dist -Filter "wintestkit-*-py3-none-any.whl" | Select-Object -First 1
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
    Invoke-Checked "Install wheel without extra dependencies" { uv pip install --python (Join-Path $bin "python.exe") $wheel.FullName }
    Invoke-Checked "Check installed dependencies" { uv pip check --python (Join-Path $bin "python.exe") }

    Invoke-Checked "wtk --version" { & (Join-Path $bin "wtk.exe") --version }
    Write-Host "==> wtk doctor --json"
    $doctor = & (Join-Path $bin "wtk.exe") doctor --json | Out-String
    # Exit 3 means an environment check failed (e.g. no interactive desktop); the JSON is still valid.
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 3) { throw "wtk doctor failed (exit $LASTEXITCODE)" }
    $null = $doctor | ConvertFrom-Json
    Invoke-Checked "import wintestkit" { & (Join-Path $bin "python.exe") -c "import wintestkit; print(wintestkit.__version__)" }

    Write-Host "==> pytest plugin registered"
    $help = & (Join-Path $bin "python.exe") -m pytest --help | Out-String
    if ($LASTEXITCODE -ne 0) { throw "pytest --help failed" }
    if ($help -notmatch "wtk-launch") { throw "pytest --help does not list --wtk-launch" }
    $smoke = Join-Path $venv "smoke"
    New-Item -ItemType Directory -Path $smoke | Out-Null
    @("def test_installed_wheel():", "    assert True") | Set-Content -LiteralPath (Join-Path $smoke "test_wheel.py") -Encoding utf8
    Push-Location $smoke
    try {
        Invoke-Checked "Run tests through the installed CLI" { & (Join-Path $bin "wtk.exe") run --no-env-check --no-report --no-html test_wheel.py }
    } finally {
        Pop-Location
    }
    Write-Host "Wheel OK: $($wheel.Name)"
} finally {
    if ($null -eq $previousVirtualEnv) {
        Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
    } else {
        $env:VIRTUAL_ENV = $previousVirtualEnv
    }
    $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    $resolvedVenv = [IO.Path]::GetFullPath($venv)
    if (-not $resolvedVenv.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($resolvedVenv) -notmatch '^wtk-wheel-[a-f0-9]{32}$') {
        throw "Refusing to clean an unexpected temporary directory: $resolvedVenv"
    }
    if (Test-Path -LiteralPath $resolvedVenv) { Remove-Item -LiteralPath $resolvedVenv -Recurse -Force }
}
