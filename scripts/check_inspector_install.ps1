# Build local wheels, populate a local dependency wheelhouse, then install offline.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$temp = Join-Path ([IO.Path]::GetTempPath()) ('wtk-install-' + [guid]::NewGuid().ToString('N'))
$fixture = Join-Path $root 'wpf-inspector/tests/Fixtures/WpfFixture/bin/cells/net10.0-windows-x64/WinTestKit.Fixture.exe'
if (-not (Test-Path -LiteralPath $fixture -PathType Leaf)) { throw "Published fixture missing: $fixture" }
try {
    $dist = Join-Path $temp 'dist'; $venv = Join-Path $temp 'venv'; $cwd = Join-Path $temp 'work'
    New-Item -ItemType Directory -Force -Path $dist, $cwd | Out-Null
    & uv build --directory (Join-Path $root 'python') --wheel --out-dir $dist
    if ($LASTEXITCODE -ne 0) { throw 'Core wheel build failed.' }
    & uv build --directory (Join-Path $root 'inspector-payload') --wheel --out-dir $dist
    if ($LASTEXITCODE -ne 0) { throw 'Inspector wheel build failed.' }
    $core = @(Get-ChildItem -LiteralPath $dist -Filter 'wintestkit-*.whl')
    $inspector = @(Get-ChildItem -LiteralPath $dist -Filter 'wintestkit_inspector-*.whl')
    if ($core.Count -ne 1 -or $inspector.Count -ne 1) { throw 'Expected exactly one wheel of each kind.' }
    # Download dependencies ahead of time; the venv installation itself is strictly offline.
    & python -m pip download --only-binary=:all: --python-version 3.12 --dest $dist $core[0].FullName
    if ($LASTEXITCODE -ne 0) { throw 'Dependency wheelhouse preparation failed.' }
    & uv venv --python 3.12 $venv
    if ($LASTEXITCODE -ne 0) { throw 'Venv creation failed.' }
    $python = Join-Path $venv 'Scripts/python.exe'
    & uv pip install --python $python --no-index --find-links $dist $core[0].FullName $inspector[0].FullName
    if ($LASTEXITCODE -ne 0) { throw 'Offline wheel installation failed.' }
    & uv pip check --python $python
    if ($LASTEXITCODE -ne 0) { throw 'Installed dependencies invalid.' }
    $yaml = "backend: auto`ninspector:`n  enabled: true`n  attach: on-launch`napp:`n  path: '$($fixture.Replace("'", "''"))'`n  cwd: '$($fixture.Substring(0, $fixture.LastIndexOf('\')).Replace("'", "''"))'`n"
    [IO.File]::WriteAllText((Join-Path $cwd 'wintestkit.yaml'), $yaml)
    Push-Location $cwd
    try {
        $doctor = & $python -I -m wintestkit doctor --json
        if ($LASTEXITCODE -ne 0) { throw "Doctor failed: $doctor" }
        $doctor = & $python -I -m wintestkit doctor --agent --json
        if ($LASTEXITCODE -ne 0) { throw "Doctor agent failed: $doctor" }
        $checks = $doctor | ConvertFrom-Json
        if (@($checks | Where-Object { $_.id -eq 'wpf_agent' -and $_.status -eq 'ok' }).Count -ne 1) { throw "Agent doctor did not pass: $doctor" }
        & $python -I (Join-Path $PSScriptRoot 'inspector_install_smoke.py') $fixture $root
        if ($LASTEXITCODE -ne 0) { throw 'Installed fixture smoke failed.' }
    } finally { Pop-Location }
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
