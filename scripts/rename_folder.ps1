# Move the project folder to its new name (default E:\Sora) and fix everything that stores the path.
#
# Windows can't rename a folder while anything has it open, so first:
#   - close VS Code (all its windows) and any File Explorer window or terminal that is inside the folder;
#   - open PowerShell from the Start menu (it starts in your home folder, not in this one).
# Then run it with its full path:
#   powershell -ExecutionPolicy Bypass -File "E:\Luna 3.0.1\scripts\rename_folder.ps1"
#   powershell -ExecutionPolicy Bypass -File "E:\Luna 3.0.1\scripts\rename_folder.ps1" -NewPath "E:\Sora 3.0.1"
# It stops what it can itself: Sora's server, PC agent and app, and the Gradle / Kotlin / Dart helpers
# that builds leave running.
param([string]$NewPath = "E:\Sora")

$ErrorActionPreference = "Stop"
$old = Split-Path $PSScriptRoot -Parent
if (Test-Path $NewPath) { throw "$NewPath already exists" }
Set-Location $env:USERPROFILE  # this window mustn't be the one holding the folder

# 1. Stop Sora (server, PC agent, the app and its corner orb) and the build helpers.
Get-Process sora -ErrorAction SilentlyContinue | Stop-Process -Force
Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and (
        ($_.ExecutablePath -like "$old\*") -or
        ($_.CommandLine -like "*$old*" -and $_.Name -notmatch '^(Code|explorer|powershell|pwsh|cmd|WindowsTerminal)\.exe$') -or
        ($_.Name -match '^(java|dart|dartvm|dartaotruntime)\.exe$' -and $_.CommandLine -match 'GradleDaemon|KotlinCompileDaemon|language-server|tooling-daemon|devtools|flutter_tools')
    )
} | ForEach-Object {
    "stopping $($_.Name) ($($_.ProcessId))"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

# 2. Move the folder (a few tries: a stopped process can take a moment to let go).
$moved = $false
for ($try = 1; $try -le 3 -and -not $moved; $try++) {
    try {
        Move-Item -LiteralPath $old -Destination $NewPath
        $moved = $true
    } catch {
        Start-Sleep -Seconds 3
    }
}
if (-not $moved) {
    $open = Get-Process Code -ErrorAction SilentlyContinue
    "Still in use, so nothing was moved."
    if ($open) { "VS Code is still running: close all its windows (File > Exit)." }
    "Also close File Explorer windows and terminals that are inside $old, then run this again."
    exit 1
}
"moved $old -> $NewPath"

# 3. Paths inside .env (e.g. WHISPER_MODEL_DIR), with either slash style.
$envFile = Join-Path $NewPath ".env"
$text = [IO.File]::ReadAllText($envFile)
$text = $text.Replace($old, $NewPath).Replace($old.Replace('\', '/'), $NewPath.Replace('\', '/'))
[IO.File]::WriteAllText($envFile, $text, (New-Object Text.UTF8Encoding $false))
".env paths updated"

# 4. The backend is installed in editable mode, which remembers its folder.
& (Join-Path $NewPath ".venv\Scripts\python.exe") -m pip install -e (Join-Path $NewPath "backend") --no-deps -q
"backend reinstalled"

# 5. Build caches that remember the old folder (the next build makes them again; the APK and the
#    installer already built stay).
foreach ($cache in @("app\build\windows", "app\.dart_tool", "app\android\.gradle", "app\packages\sora_phone\.dart_tool")) {
    $p = Join-Path $NewPath $cache
    if (Test-Path $p) { Remove-Item -LiteralPath $p -Recurse -Force; "cleared $cache" }
}

# 6. Startup shortcuts point at the new folder; start the server and agent again.
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $NewPath "scripts\install_autostart.ps1")
$startup = [Environment]::GetFolderPath("Startup")
Start-Process explorer.exe "`"$startup\Sora server.lnk`""
Start-Process explorer.exe "`"$startup\Sora PC agent.lnk`""

# 7. Claude Code keeps per-folder memory under ~/.claude/projects/<folder as a name>; copy it.
function ProjectKey([string]$p) { ($p.Substring(0, 1).ToLower() + $p.Substring(1)) -replace '[:\\/ .]', '-' }
$projects = Join-Path $env:USERPROFILE ".claude\projects"
$from = Join-Path $projects (ProjectKey $old)
$to = Join-Path $projects (ProjectKey $NewPath)
if ((Test-Path $from) -and -not (Test-Path $to)) { Copy-Item $from $to -Recurse; "Claude memory copied to $to" }

"done - open $NewPath in VS Code, then open the Sora app (it finds the server at its new place)"
