function Resolve-InspectorDotnet {
    param([string]$DotnetRoot, [string]$InspectorRoot)
    if ($DotnetRoot) {
        $sdkRoot = $DotnetRoot
    } elseif ($env:DOTNET_ROOT) {
        $sdkRoot = $env:DOTNET_ROOT
    } else {
        $command = Get-Command dotnet.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { throw 'Cannot find dotnet SDK: specify -DotnetRoot, set DOTNET_ROOT, or add dotnet to PATH.' }
        $sdkRoot = Split-Path $command.Source -Parent
    }
    $sdkRoot = [IO.Path]::GetFullPath($sdkRoot)
    $dotnet = Join-Path $sdkRoot 'dotnet.exe'
    if (-not (Test-Path -LiteralPath $dotnet -PathType Leaf)) { throw "Cannot find dotnet SDK executable: $dotnet" }
    $env:DOTNET_ROOT = $sdkRoot
    Push-Location $InspectorRoot
    try {
        & $dotnet --version | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "The dotnet SDK at $sdkRoot does not satisfy $InspectorRoot/global.json." }
    } finally { Pop-Location }
    return $dotnet
}
