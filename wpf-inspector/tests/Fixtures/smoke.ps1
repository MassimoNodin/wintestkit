Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$env:DOTNET_ROOT_X64 = 'C:\Users\massi\AppData\Local\wintestkit-dev\dotnet'
$root = Join-Path $PSScriptRoot 'WpfFixture/bin/cells'
$failed = $false
foreach ($cell in @('net48-x86','net48-x64','net8.0-windows-x86','net8.0-windows-x64','net10.0-windows-x86','net10.0-windows-x64')) {
  if ($cell -eq 'net8.0-windows-x64') { $env:DOTNET_ROOT_X64 = 'C:\Program Files\dotnet' } else { $env:DOTNET_ROOT_X64 = 'C:\Users\massi\AppData\Local\wintestkit-dev\dotnet' }
  $exe = Join-Path $root "$cell/WinTestKit.Fixture.exe"
  $p = Start-Process -FilePath $exe -PassThru
  try {
    $found = $null
    for ($i=0; $i -lt 40; $i++) {
      Start-Sleep -Milliseconds 250
      $p.Refresh(); if ($p.HasExited) { break }
      $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $p.Id)
      $found = [System.Windows.Automation.AutomationElement]::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children, $condition)
      if ($found -and $found.Current.Name -eq "WinTestKit WPF Fixture") { break }; $found = $null
    }
    if ($found) {
      $id = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, 'FixtureControl')
      $control = $null
      for ($j=0; $j -lt 20 -and !$control; $j++) { Start-Sleep -Milliseconds 250; $control = $found.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $id) }
      if (!$control) { $failed = $true }
      Write-Output "$cell pid=$($p.Id) window=$($found.Current.Name) control=$([bool]$control) hash=$((Get-FileHash $exe -Algorithm SHA256).Hash)"
    } else { $failed = $true; Write-Output "$cell no UIA window exited=$($p.HasExited)" }
  } finally { $p.Refresh(); if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }; $p.Dispose() }
}

if ($failed) { exit 1 }
