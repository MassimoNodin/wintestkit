param([switch]$Hold)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class DesktopWake {
    [DllImport("user32.dll", SetLastError=true)] public static extern IntPtr OpenInputDesktop(uint flags, bool inherit, uint access);
    [DllImport("user32.dll", SetLastError=true)] public static extern bool CloseDesktop(IntPtr desktop);
    [DllImport("user32.dll", CharSet=CharSet.Unicode, SetLastError=true)] public static extern bool GetUserObjectInformation(IntPtr handle, int index, StringBuilder info, int length, out int needed);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, int dx, int dy, uint data, UIntPtr extra);
    [DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags);
}
'@
if ($Hold) {
    if ([DesktopWake]::SetThreadExecutionState([uint32]2147483651) -eq 0) { throw 'Could not keep the display awake.' }
    try { while ($true) { Start-Sleep -Seconds 60 } }
    finally { [void][DesktopWake]::SetThreadExecutionState([uint32]2147483648) }
    return
}
if ([Diagnostics.Process]::GetCurrentProcess().SessionId -eq 0) { throw 'Desktop CI requires a logged-in interactive session, not a service (session 0).' }
$desktop = [DesktopWake]::OpenInputDesktop(0, $false, 0x0001)
if ($desktop -eq [IntPtr]::Zero) { throw 'Cannot open the input desktop; log in and unlock the runner session.' }
try {
    $name = [Text.StringBuilder]::new(256)
    $needed = 0
    if (-not [DesktopWake]::GetUserObjectInformation($desktop, 2, $name, 512, [ref]$needed) -or $name.ToString() -ne 'Default') {
        throw 'The input desktop is not the unlocked Default desktop; unlock the runner session.'
    }
} finally { [void][DesktopWake]::CloseDesktop($desktop) }
[DesktopWake]::mouse_event(1, 1, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 50
[DesktopWake]::mouse_event(1, -1, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Seconds 2
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [Windows.Forms.SystemInformation]::VirtualScreen
if ($bounds.Width -le 0 -or $bounds.Height -le 0) { throw 'No display is available to capture.' }
$bitmap = [Drawing.Bitmap]::new($bounds.Width, $bounds.Height)
$graphics = [Drawing.Graphics]::FromImage($bitmap)
try {
    $graphics.CopyFromScreen($bounds.Location, [Drawing.Point]::Empty, $bounds.Size)
    $nonBlack = $false
    for ($y = 0; $y -lt $bounds.Height -and -not $nonBlack; $y += 8) {
        for ($x = 0; $x -lt $bounds.Width; $x += 8) {
            $pixel = $bitmap.GetPixel($x, $y)
            if ($pixel.R -or $pixel.G -or $pixel.B) { $nonBlack = $true; break }
        }
    }
    if (-not $nonBlack) { throw 'Display capture is black; wake the display and keep the desktop unlocked.' }
} finally { $graphics.Dispose(); $bitmap.Dispose() }
Write-Host 'Interactive desktop and non-black display capture verified.'
