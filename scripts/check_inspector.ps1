param(
    [Parameter(Mandatory)][ValidateSet('Unit','Security','Integration','Matrix','Stress','Package')][string]$Suite,
    [ValidateSet('net48','net8','net10')][string]$Runtime,
    [ValidateSet('x86','x64')][string]$Architecture,
    [ValidateRange(1, 2147483647)][int]$Iterations = 100,
    [string]$PayloadRoot,
    [switch]$RequireSigned,
    [string]$DotnetRoot
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'resolve_dotnet.ps1')
$dotnet = Resolve-InspectorDotnet -DotnetRoot $DotnetRoot -InspectorRoot (Join-Path $root 'wpf-inspector')
Push-Location (Join-Path $root 'wpf-inspector')
try {
if ($Suite -eq 'Package') {
    if (-not $PayloadRoot) { $PayloadRoot = Join-Path $root 'inspector-payload/src/wintestkit_inspector/payload' }
    $PayloadRoot = [IO.Path]::GetFullPath($PayloadRoot)
    $lock = Get-Content -Raw -LiteralPath (Join-Path $root 'wpf-inspector/third_party/snoop.lock.json') | ConvertFrom-Json
    $vendor = Join-Path $root 'wpf-inspector/third_party/snoop'
    $inventory = @{}
    foreach ($entry in $lock.files) {
        $inventory[$entry.path.Replace('/', '\')] = $true
        $source = Join-Path $vendor $entry.path
        if (-not (Test-Path -LiteralPath $source -PathType Leaf) -or (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash.ToLowerInvariant() -ne $entry.sha256) { throw "Pinned Snoop source missing or changed: $($entry.path)" }
    }
    foreach ($item in Get-ChildItem -LiteralPath $vendor -File -Recurse) {
        if ($item.FullName.Substring($vendor.Length + 1) -match '(^|\\)(bin|obj)\\') { continue }
        if (-not $inventory.ContainsKey($item.FullName.Substring($vendor.Length + 1))) { throw "Uninventoried Snoop source: $($item.FullName)" }
    }
    $versionSource = Get-Content -Raw -LiteralPath (Join-Path $root 'python/src/wintestkit/__init__.py')
    if ($versionSource -notmatch '(?m)^__version__\s*=\s*["'']([^"'']+)["'']') { throw 'Cannot find inspector version.' }
    $version = $Matches[1]
    $verifierSource = Join-Path $root 'wpf-inspector/tests/Harness/OwnedAttach'
    $project = Join-Path $verifierSource 'OwnedAttach.csproj'
    & $dotnet restore $project --locked-mode
    if ($LASTEXITCODE -ne 0) { throw 'Package verifier locked restore failed.' }
    & $dotnet build $project -c Release --no-restore
    if ($LASTEXITCODE -ne 0) { throw 'Package verifier build failed.' }
    $verifier = Join-Path $verifierSource 'bin/Release/net10.0-windows/OwnedAttach.dll'
    & $dotnet $verifier package $PayloadRoot $version $lock.commit
    if ($LASTEXITCODE -ne 0) { throw 'Staged payload validation failed.' }
    $strongNameTool = Join-Path ${env:ProgramFiles(x86)} 'Microsoft SDKs/Windows/v10.0A/bin/NETFX 4.8 Tools/sn.exe'
    if (-not (Test-Path -LiteralPath $strongNameTool -PathType Leaf)) { throw 'Strong-name verification requires the .NET Framework 4.8 SDK sn.exe.' }
    foreach ($runtime in @('net48', 'net8', 'net10')) {
        & $strongNameTool -q -vf (Join-Path $PayloadRoot "agents/$runtime/WinTestKit.Inspector.Agent.dll")
        if ($LASTEXITCODE -ne 0) { throw "Strong-name verification failed for $runtime Agent." }
    }
    foreach ($pair in @(
        @('notices/THIRD-PARTY-NOTICES.md', 'wpf-inspector/THIRD-PARTY-NOTICES.md'),
        @('notices/Snoop-License.txt', 'wpf-inspector/third_party/snoop/License.txt'),
        @('notices/CommandLineParser-License.md', 'wpf-inspector/third_party/licenses/CommandLineParser-2.9.1.License.md')
    )) {
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $PayloadRoot $pair[0])).Hash -ne (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $root $pair[1])).Hash) { throw "Notice mismatch: $($pair[0])" }
    }
    $noticeText = (Get-Content -Raw -LiteralPath (Join-Path $PayloadRoot 'notices/THIRD-PARTY-NOTICES.md')).Replace("`r`n", "`n")
    $snoopLicense = (Get-Content -Raw -LiteralPath (Join-Path $PayloadRoot 'notices/Snoop-License.txt')).Replace("`r`n", "`n").Trim()
    if (-not $noticeText.Contains($snoopLicense) -or -not $noticeText.Contains('CommandLineParser 2.9.1')) { throw 'Third-party notice is incomplete.' }
    $manifest = Get-Content -Raw -LiteralPath (Join-Path $PayloadRoot 'manifest.json') | ConvertFrom-Json
    if ($RequireSigned -and -not $manifest.signed) { throw 'A signed release payload was required; this payload is unsigned.' }
    if ($manifest.signed) {
        foreach ($entry in $manifest.files | Where-Object { $_.path -match '\.(exe|dll)$' }) {
            $signature = Get-AuthenticodeSignature -LiteralPath (Join-Path $PayloadRoot $entry.path)
            if ($signature.Status -ne 'Valid') { throw "Invalid Authenticode signature: $($entry.path) ($($signature.Status))" }
        }
    } else { Write-Host 'Unsigned development payload; no release signature claim.' }
    Write-Host "Package: verified $($lock.files.Count) pinned Snoop sources and exact staged notices. Wheel/release checks are separate."
    return
}
$env:WTK_TEST_RUNTIME = $Runtime
$env:WTK_TEST_ARCH = $Architecture
$env:WTK_TEST_ITERATIONS = "$Iterations"
$results = Join-Path $root 'wpf-inspector/artifacts/verification'
New-Item -ItemType Directory -Force $results | Out-Null
$run = Join-Path $results ([guid]::NewGuid().ToString())
New-Item -ItemType Directory $run | Out-Null
& $dotnet test (Join-Path $root 'wpf-inspector/WinTestKit.Inspector.sln') -c Release --filter "Category=$Suite" --logger trx --results-directory $run
if ($LASTEXITCODE -ne 0) { throw "dotnet test failed for $Suite ($LASTEXITCODE)." }
$trxs = @(Get-ChildItem -LiteralPath $run -Filter '*.trx')
if ($trxs.Count -eq 0) { throw "No tests found for required category $Suite (no TRX)." }
$total = 0
foreach ($trx in $trxs) {
    [xml]$report = Get-Content -Raw -LiteralPath $trx.FullName
    $counters = $report.TestRun.ResultSummary.Counters
    if (-not $counters) { throw "Missing test counters in $($trx.FullName)." }
    $total += [int]$counters.total
    if ([int]$counters.failed -ne 0 -or [int]$counters.notExecuted -ne 0 -or [int]$counters.passed -ne [int]$counters.total) { throw "Failed or skipped required tests in $($trx.FullName)." }
}
if ($total -eq 0) { throw "No tests found for required category $Suite." }
Write-Host "$Suite`: $total tests passed."
} finally { Pop-Location }
