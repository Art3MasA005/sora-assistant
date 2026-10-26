# Start the Sora server and PC agent when you sign in to Windows (no console windows).
# The Windows app's Settings -> "Start with Windows" does the same; this is for setting it up by hand.
#   powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1            # add
#   powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1 -Remove    # remove
# Logs: data\logs\server.log and data\logs\agent.log
param([switch]$Remove)

$root = Split-Path $PSScriptRoot -Parent
# Sora.exe (scripts\sora_host\build.ps1) is Python under Sora's name; pythonw.exe if it isn't built.
$pythonw = Join-Path $root ".venv\Scripts\Sora.exe"
if (-not (Test-Path $pythonw)) { $pythonw = Join-Path $root ".venv\Scripts\pythonw.exe" }
$startup = [Environment]::GetFolderPath("Startup")
$items = @{ "Sora server" = "server"; "Sora PC agent" = "agent" }

foreach ($name in $items.Keys) {
    $lnk = Join-Path $startup "$name.lnk"
    if ($Remove) {
        if (Test-Path $lnk) { Remove-Item $lnk; "removed $name" }
        continue
    }
    $shell = New-Object -ComObject WScript.Shell
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = $pythonw
    $s.Arguments = "`"$root\scripts\run_hidden.py`" $($items[$name])"
    $s.WorkingDirectory = $root
    $s.Description = "Sora ($($items[$name]))"
    $s.Save()
    "added $name -> $lnk"
}
