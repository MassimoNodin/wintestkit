# Rebuild the unsigned payload twice and compare every staged and distribution byte.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$temp = Join-Path ([IO.Path]::GetTempPath()) ('wtk-repro-' + [guid]::NewGuid().ToString('N'))
$oldEpoch = $env:SOURCE_DATE_EPOCH
try {
    New-Item -ItemType Directory -Path $temp | Out-Null
    $env:SOURCE_DATE_EPOCH = '315532800'
    foreach ($run in @(1, 2)) {
        & (Join-Path $PSScriptRoot 'build_inspector.ps1') -Configuration Release -LockedRestore -Rebuild
        if (-not $?) { throw "Payload build $run failed." }
        $out = Join-Path $temp "$run"
        New-Item -ItemType Directory -Path $out | Out-Null
        Copy-Item -LiteralPath (Join-Path $root 'inspector-payload/src/wintestkit_inspector/payload') -Destination (Join-Path $out 'payload') -Recurse
        & uv build --directory (Join-Path $root 'inspector-payload') --wheel --out-dir (Join-Path $out 'dist')
        if ($LASTEXITCODE -ne 0) { throw 'Inspector wheel build failed.' }
        & uv build --directory (Join-Path $root 'python') --sdist --out-dir (Join-Path $out 'dist')
        if ($LASTEXITCODE -ne 0) { throw 'Core sdist build failed.' }
        $sdist = @(Get-ChildItem -LiteralPath (Join-Path $out 'dist') -Filter 'wintestkit-*.tar.gz')
        if ($sdist.Count -ne 1) { throw 'Expected exactly one core sdist.' }
        & uv build $sdist[0].FullName --wheel --out-dir (Join-Path $out 'dist')
        if ($LASTEXITCODE -ne 0) { throw 'Core wheel build failed.' }
    }
    $hashes = @()
    foreach ($run in @(1, 2)) {
        $dir = Join-Path $temp "$run"
        $hashes += ,@{ }
        Get-ChildItem -LiteralPath $dir -Recurse -File | ForEach-Object {
            $rel = $_.FullName.Substring($dir.Length + 1).Replace('\', '/')
            $hashes[$run - 1][$rel] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    $names = @($hashes[0].Keys + $hashes[1].Keys | Sort-Object -Unique)
    $different = $false
    foreach ($name in $names) {
        $a = $hashes[0][$name]; $b = $hashes[1][$name]
        Write-Host "$name $a $b"
        if (-not $a -or -not $b -or $a -cne $b) { $different = $true }
    }
    if ($different) { throw 'Reproducibility comparison failed.' }
    Write-Host "Reproducible: $($names.Count) files match."
} finally {
    $env:SOURCE_DATE_EPOCH = $oldEpoch
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
