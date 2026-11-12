param(
    [string]$DotnetRoot
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$inspectorRoot = Join-Path $root 'wpf-inspector'
. (Join-Path $PSScriptRoot 'resolve_dotnet.ps1')
$dotnet = Resolve-InspectorDotnet -DotnetRoot $DotnetRoot -InspectorRoot $inspectorRoot
$fixture = Join-Path $inspectorRoot 'tests/Fixtures/WpfFixture/WpfFixture.csproj'
$harness = Join-Path $inspectorRoot 'tests/Harness/OwnedAttach/OwnedAttach.csproj'
Push-Location $inspectorRoot
try {
    & $dotnet restore $fixture --locked-mode
    if ($LASTEXITCODE -ne 0) { throw "Fixture restore failed ($LASTEXITCODE)." }
    foreach ($tfm in @('net48', 'net8.0-windows', 'net10.0-windows')) {
        foreach ($architecture in @('x86', 'x64')) {
            $runtime = "win-$architecture"
            $output = Join-Path $inspectorRoot "tests/Fixtures/WpfFixture/bin/cells/$tfm-$architecture"
            & $dotnet publish $fixture -c Release -f $tfm -r $runtime --self-contained false --no-restore "-p:PlatformTarget=$architecture" -o $output
            if ($LASTEXITCODE -ne 0) { throw "Fixture publish failed for $tfm/$architecture ($LASTEXITCODE)." }
        }
    }
    & $dotnet restore $harness --locked-mode
    if ($LASTEXITCODE -ne 0) { throw "OwnedAttach restore failed ($LASTEXITCODE)." }
    & $dotnet build $harness -c Release --no-restore
    if ($LASTEXITCODE -ne 0) { throw "OwnedAttach build failed ($LASTEXITCODE)." }
} finally { Pop-Location }
