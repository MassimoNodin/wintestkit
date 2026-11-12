function Resolve-InspectorDotnet {
    param([string]$DotnetRoot, [string]$InspectorRoot)
    $candidates = @()
    if ($DotnetRoot) {
        $candidates += $DotnetRoot
    } else {
        if ($env:DOTNET_ROOT) { $candidates += $env:DOTNET_ROOT }
        $command = Get-Command dotnet.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) { $candidates += (Split-Path $command.Source -Parent) }
        if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA 'wintestkit-dev\dotnet') }
    }
    $tried = @()
    Push-Location $InspectorRoot
    try {
        foreach ($candidate in $candidates) {
            $sdkRoot = [IO.Path]::GetFullPath($candidate)
            $dotnet = Join-Path $sdkRoot 'dotnet.exe'
            $tried += $dotnet
            if (-not (Test-Path -LiteralPath $dotnet -PathType Leaf)) { continue }
            $previousPreference = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            try {
                $output = & $dotnet --version 2>&1
                $exitCode = $LASTEXITCODE
            } catch {
                $exitCode = -1
            } finally { $ErrorActionPreference = $previousPreference }
            if ($exitCode -eq 0) {
                $env:DOTNET_ROOT = $sdkRoot
                return $dotnet
            }
        }
    } finally { Pop-Location }
    $globalJson = Join-Path $InspectorRoot 'global.json'
    $requirement = Get-Content -Raw -LiteralPath $globalJson
    throw "Cannot find a compatible dotnet SDK. Candidates tried: $($tried -join ', '). Requirement in ${globalJson}: $requirement"
}
