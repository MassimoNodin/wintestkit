param(
    [ValidateSet('Debug', 'Release')][string]$Configuration = 'Release',
    [switch]$LockedRestore,
    [switch]$Sign,
    [string]$DotnetRoot
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'resolve_dotnet.ps1')
$dotnet = Resolve-InspectorDotnet -DotnetRoot $DotnetRoot -InspectorRoot (Join-Path $root 'wpf-inspector')
$msbuild = 'C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe'
if ($Sign -and -not $env:WTK_SIGN_CERT_THUMBPRINT) { throw '-Sign requires WTK_SIGN_CERT_THUMBPRINT.' }
# Verify the complete pinned inventory before compiling or copying any upstream code.
$vendor = Join-Path $root 'wpf-inspector/third_party/snoop'
$lock = Get-Content -Raw (Join-Path $root 'wpf-inspector/third_party/snoop.lock.json') | ConvertFrom-Json
$expected = @{}
foreach ($entry in $lock.files) {
    $expected[$entry.path.Replace('/', '\')] = $true
    $file = Join-Path $vendor $entry.path
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing pinned Snoop source: $($entry.path)" }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash.ToLowerInvariant() -ne $entry.sha256) { throw "Snoop source hash mismatch: $($entry.path)" }
}
foreach ($file in Get-ChildItem -LiteralPath $vendor -File -Recurse) {
    $relative = $file.FullName.Substring($vendor.Length + 1)
    if (-not $expected.ContainsKey($relative)) { throw "Uninventoried Snoop source: $relative" }
}
$sdkInclude = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/NETFXSDK/4.8/Include/um'
foreach ($header in @('metahost.h', 'mscoree.h')) {
    if (-not (Test-Path -LiteralPath (Join-Path $sdkInclude $header) -PathType Leaf)) {
        throw "Missing $header in $sdkInclude. Install the .NET Framework 4.8 Developer Pack before building the native loader."
    }
}
Write-Host "Verified $($lock.files.Count) pinned Snoop files; CLR hosting headers: $sdkInclude"
$env:CL = "/I`"$sdkInclude`" $env:CL"

Push-Location (Join-Path $root 'wpf-inspector')
try {
    $failed = $false
    foreach ($project in @('wpf-inspector/src/Protocol/Protocol.csproj', 'wpf-inspector/src/Agent/Agent.csproj', 'wpf-inspector/src/Launcher/BundledAgent.csproj')) {
        $project = Join-Path $root $project
        $restoreArgs = @('restore', $project)
        if ($LockedRestore) { $restoreArgs += '--locked-mode' }
        & $dotnet @restoreArgs
        if ($LASTEXITCODE -ne 0) { Write-Warning "Restore failed: $project"; $failed = $true; continue }
        & $dotnet build $project -c $Configuration --no-restore
        if ($LASTEXITCODE -ne 0) { Write-Warning "Build failed: $project"; $failed = $true }
    }
    foreach ($arch in @('Win32', 'x64')) {
        $out = Join-Path $root "wpf-inspector/artifacts/launcher/$Configuration/$arch/"
        $obj = Join-Path $root "wpf-inspector/artifacts/launcher/obj/$Configuration/$arch/"
        & $msbuild (Join-Path $root 'wpf-inspector/third_party/snoop/Snoop.GenericInjector/Snoop.GenericInjector.vcxproj') /t:Build "/p:Configuration=$Configuration" "/p:Platform=$arch" /p:RootBuild=False /p:PlatformToolset=v143 /p:VCToolsVersion=14.40.33807 "/p:OutDir=$out" "/p:IntDir=$obj" /v:minimal
        if ($LASTEXITCODE -ne 0) { Write-Warning "Native build failed: $arch"; $failed = $true }
    }
    if ($failed) { throw 'Protocol, Agent, or native injector build failed; launcher build was not started.' }

    # Apply the reviewed changes only to a fresh copy of the pinned launcher sources.
    # Explicit Compile items in the patched project prevent stale files in this generated
    # directory from being included. The upstream inventory remains byte-for-byte unchanged.
    $copyRoot = Join-Path $root 'wpf-inspector/artifacts/launcher/source'
    $launcherCopy = Join-Path $copyRoot 'Snoop.InjectorLauncher'
    $sharedCopy = Join-Path $copyRoot 'Shared'
    New-Item -ItemType Directory -Force -Path $launcherCopy, $sharedCopy | Out-Null
    Copy-Item -Path (Join-Path $vendor 'Snoop.InjectorLauncher/*') -Destination $launcherCopy -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $vendor 'Shared/InjectorData.cs'), (Join-Path $vendor 'Shared/app.manifest') -Destination $sharedCopy -Force
    Copy-Item -LiteralPath (Join-Path $root 'wpf-inspector/src/Launcher/LauncherSupport.cs'), (Join-Path $root 'wpf-inspector/src/Launcher/packages.lock.json') -Destination $launcherCopy -Force
    $launcherPatch = Join-Path $root 'wpf-inspector/third_party/patches/snoop-injector-launcher.patch'
    & git -C $copyRoot apply --no-index --check $launcherPatch
    if ($LASTEXITCODE -ne 0) { throw 'Launcher patch does not match the verified Snoop source copy.' }
    & git -C $copyRoot apply --no-index $launcherPatch
    if ($LASTEXITCODE -ne 0) { throw 'Failed to apply the launcher patch to the source copy.' }

    $launcherProject = Join-Path $launcherCopy 'Snoop.InjectorLauncher.csproj'
    foreach ($target in @(@{ Native = 'Win32'; Managed = 'x86' }, @{ Native = 'x64'; Managed = 'x64' })) {
        $out = Join-Path $root "wpf-inspector/artifacts/launcher/$Configuration/$($target.Native)/"
        $restoreArgs = @('restore', $launcherProject, "-p:PlatformTarget=$($target.Managed)")
        if ($LockedRestore) { $restoreArgs += '--locked-mode' }
        & $dotnet @restoreArgs
        if ($LASTEXITCODE -ne 0) { Write-Warning "Launcher restore failed: $($target.Managed)"; $failed = $true; continue }
        & $dotnet build $launcherProject -c $Configuration --no-restore "-p:PlatformTarget=$($target.Managed)" "-p:OutputPath=$out"
        if ($LASTEXITCODE -ne 0) { Write-Warning "Launcher build failed: $($target.Managed)"; $failed = $true; continue }
        $launcherExe = Join-Path $out "Snoop.InjectorLauncher.$($target.Managed).exe"
        if (-not (Test-Path -LiteralPath $launcherExe -PathType Leaf)) { Write-Warning "Launcher output missing: $launcherExe"; $failed = $true }
    }
    if ($failed) { throw 'One or more launcher builds failed.' }

    # The payload is a development artifact unless explicitly signed.  Keep this
    # inventory in one place: no PDBs, test files, or Snoop UI are copied.
    $payload = Join-Path $root 'inspector-payload/src/wintestkit_inspector/payload'
    $copies = [ordered]@{}
    foreach ($target in @(@{ Native = 'Win32'; Managed = 'x86' }, @{ Native = 'x64'; Managed = 'x64' })) {
        $from = Join-Path $root "wpf-inspector/artifacts/launcher/$Configuration/$($target.Native)"
        foreach ($name in @("Snoop.InjectorLauncher.$($target.Managed).exe", "Snoop.InjectorLauncher.$($target.Managed).exe.config", "Snoop.GenericInjector.$($target.Managed).dll", 'CommandLine.dll')) {
            $copies["launchers/$($target.Managed)/$name"] = Join-Path $from $name
        }
    }
    foreach ($target in @(@{ Runtime = 'net48'; Tfm = 'net48' }, @{ Runtime = 'net8'; Tfm = 'net8.0-windows' }, @{ Runtime = 'net10'; Tfm = 'net10.0-windows' })) {
        $from = Join-Path $root "wpf-inspector/artifacts/bundled-agent/bin/$Configuration/$($target.Tfm)"
        foreach ($name in @('WinTestKit.Inspector.Agent.dll')) {
            $copies["agents/$($target.Runtime)/$name"] = Join-Path $from $name
        }
    }
    $copies['notices/THIRD-PARTY-NOTICES.md'] = Join-Path $root 'wpf-inspector/THIRD-PARTY-NOTICES.md'
    $copies['notices/Snoop-License.txt'] = Join-Path $vendor 'License.txt'
    $copies['notices/CommandLineParser-License.md'] = Join-Path $root 'wpf-inspector/third_party/licenses/CommandLineParser-2.9.1.License.md'
    $nugetLicense = Join-Path $env:USERPROFILE '.nuget/packages/commandlineparser/2.9.1/License.md'
    if ((Get-FileHash -LiteralPath $nugetLicense -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $copies['notices/CommandLineParser-License.md'] -Algorithm SHA256).Hash) {
        throw 'CommandLineParser notice does not match the restored, locked package.'
    }
    foreach ($source in $copies.Values) {
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Payload input missing: $source" }
    }
    # Never silently remove unlisted files from a shared checkout.
    if (Test-Path -LiteralPath $payload) {
        if ((Get-Item -LiteralPath $payload -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Payload root is a reparse point.' }
        foreach ($item in Get-ChildItem -LiteralPath $payload -Recurse -Force) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Payload contains a reparse point: $($item.FullName)" }
            if (-not $item.PSIsContainer) {
                $relative = $item.FullName.Substring($payload.Length + 1).Replace('\', '/')
                if ($relative -ne 'manifest.json' -and -not $copies.Contains($relative)) {
                    # Migrate only the redundant Protocol copies produced by the
                    # immediately preceding staged layout, and only if the old
                    # manifest authenticates their current bytes.
                    $oldManifestPath = Join-Path $payload 'manifest.json'
                    if ($relative -notmatch '^agents/(net48|net8|net10)/WinTestKit\.Inspector\.Protocol\.dll$' -or -not (Test-Path -LiteralPath $oldManifestPath -PathType Leaf)) { throw "Unexpected existing payload file: $relative" }
                    $old = Get-Content -Raw $oldManifestPath | ConvertFrom-Json
                    $record = @($old.files | Where-Object { $_.path -ceq $relative })
                    if ($record.Count -ne 1 -or $record[0].sha256 -cne (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()) { throw "Cannot safely migrate old payload file: $relative" }
                    Remove-Item -LiteralPath $item.FullName
                }
            }
        }
    }
    foreach ($entry in $copies.GetEnumerator()) {
        $destination = Join-Path $payload $entry.Key
        New-Item -ItemType Directory -Force (Split-Path $destination -Parent) | Out-Null
        Copy-Item -LiteralPath $entry.Value -Destination $destination -Force
    }
    if ($Sign) {
        $kitBin = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits/10/bin'
        $signTool = Get-ChildItem -LiteralPath $kitBin -Filter signtool.exe -Recurse -File | Where-Object { $_.Directory.Name -eq 'x64' } | Sort-Object FullName -Descending | Select-Object -First 1
        if (-not $signTool) { throw 'Signing requested but Windows SDK signtool.exe was not found.' }
        foreach ($relative in $copies.Keys | Where-Object { $_ -match '\.(exe|dll)$' }) {
            $file = Join-Path $payload $relative
            & $signTool.FullName sign /sha1 $env:WTK_SIGN_CERT_THUMBPRINT /fd SHA256 $file
            if ($LASTEXITCODE -ne 0 -or (Get-AuthenticodeSignature -LiteralPath $file).Status -ne 'Valid') { throw "Signing or signature verification failed: $relative" }
        }
    }
    $versionSource = Get-Content -Raw (Join-Path $root 'python/src/wintestkit/__init__.py')
    if ($versionSource -notmatch '(?m)^__version__\s*=\s*["'']([^"'']+)["'']') { throw 'Cannot find inspector version.' }
    $version = $Matches[1]
    $sourceCommit = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $sourceCommit -notmatch '^[0-9a-f]{40}$') { throw 'Cannot determine source commit.' }
    if (@(& git status --porcelain --untracked-files=normal).Count -gt 0) { $sourceCommit += '-dirty' }
    $files = @($copies.Keys | ForEach-Object { [ordered]@{ path = $_; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $payload $_)).Hash.ToLowerInvariant() } })
    $cells = @()
    foreach ($runtime in @('net48', 'net8', 'net10')) {
        foreach ($architecture in @('x86', 'x64')) { $cells += [ordered]@{ runtime = $runtime; architecture = $architecture; verified = $false } }
    }
    $manifest = [ordered]@{
        schemaVersion = 1; inspectorVersion = $version; protocolMajor = 1; protocolMinor = 0
        sourceCommit = $sourceCommit; upstreamCommit = $lock.commit; signed = [bool]$Sign; cells = $cells
        launchers = [ordered]@{ x86 = 'launchers/x86/Snoop.InjectorLauncher.x86.exe'; x64 = 'launchers/x64/Snoop.InjectorLauncher.x64.exe' }
        agents = [ordered]@{ net48 = 'agents/net48/WinTestKit.Inspector.Agent.dll'; net8 = 'agents/net8/WinTestKit.Inspector.Agent.dll'; net10 = 'agents/net10/WinTestKit.Inspector.Agent.dll' }
        files = $files; notices = @('notices/THIRD-PARTY-NOTICES.md', 'notices/Snoop-License.txt', 'notices/CommandLineParser-License.md')
    }
    [IO.File]::WriteAllText((Join-Path $payload 'manifest.json'), ($manifest | ConvertTo-Json -Depth 8) + "`n", (New-Object Text.UTF8Encoding($false)))
    Write-Host "Staged $($files.Count) files in $payload (signed=$([bool]$Sign); compatibility cells unverified)."
} finally { Pop-Location }
