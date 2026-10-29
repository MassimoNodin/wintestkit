$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'WinTestKit\inspector\bootstrap'
New-Item -ItemType Directory -Force $root | Out-Null
$path = Join-Path $root ([guid]::NewGuid().ToString() + '.json')
$dll = Join-Path $PSScriptRoot 'bin\Release\net10.0-windows\SessionHarness.dll'
$process = Start-Process -FilePath "$env:DOTNET_ROOT\dotnet.exe" -ArgumentList @($dll, '--fake', $path) -WindowStyle Hidden -PassThru
try {
    $session = [guid]::NewGuid().ToString()
    $identity = @{ pid = $process.Id; creationTimeUtc = $process.StartTime.ToUniversalTime().ToString('O') }
    $tokenBytes = New-Object byte[] 32
    $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($tokenBytes) } finally { $random.Dispose() }
    $token = [Convert]::ToBase64String($tokenBytes)
    $version = [System.Diagnostics.FileVersionInfo]::GetVersionInfo((Join-Path $PSScriptRoot 'bin\Release\net10.0-windows\WinTestKit.Inspector.Agent.dll')).ProductVersion
    $settings = @{ schemaVersion = 1; protocolMajor = 1; protocolMinor = 0; sessionId = $session; process = $identity; pipeName = "WinTestKit.Inspector.$($process.Id).$session"; token = $token; clientSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value; expiresUtc = [DateTime]::UtcNow.AddSeconds(30).ToString('O'); requestTimeoutMs = 1000; idleTimeoutMs = 10000; agentVersion = $version }
    $temporary = $path + '.tmp'
    [IO.File]::WriteAllText($temporary, ($settings | ConvertTo-Json -Depth 10 -Compress), (New-Object Text.UTF8Encoding $false))
    Move-Item -LiteralPath $temporary -Destination $path
    $pipe = New-Object IO.Pipes.NamedPipeClientStream('.', $settings.pipeName, [IO.Pipes.PipeDirection]::InOut)
    $pipe.Connect(10000)
    function Exchange($message) {
        $bytes = [Text.Encoding]::UTF8.GetBytes(($message | ConvertTo-Json -Depth 10 -Compress))
        $length = [BitConverter]::GetBytes([int]$bytes.Length)
        $pipe.Write($length, 0, 4); $pipe.Write($bytes, 0, $bytes.Length); $pipe.Flush()
        $reader = New-Object IO.BinaryReader($pipe, [Text.Encoding]::UTF8, $true)
        $size = $reader.ReadInt32(); $response = $reader.ReadBytes($size)
        if ($response.Length -ne $size) { throw 'Incomplete frame' }
        return ([Text.Encoding]::UTF8.GetString($response) | ConvertFrom-Json)
    }
    $hello = Exchange @{ id = 1; method = 'session.hello'; params = @{ protocolMajor = 1; protocolMinor = 0; sessionId = $session; token = $token; process = $identity } }
    if ($hello.id -ne 1 -or $hello.error) { throw 'Hello failed' }
    $close = Exchange @{ id = 2; method = 'session.close'; params = @{} }
    if ($close.id -ne 2 -or -not $close.result.closed) { throw 'Close failed' }
    $pipe.Dispose()
    if (-not $process.WaitForExit(10000) -or $process.ExitCode -ne 0) { throw 'Harness failed to exit normally' }
    Write-Output 'Harness hello and close passed.'
} finally {
    if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
    if ($temporary -and (Test-Path -LiteralPath $temporary)) { Remove-Item -LiteralPath $temporary }
}
