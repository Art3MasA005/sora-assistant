# Builds .venv\Scripts\Sora.exe (see sora_host.c). Needs the VS C++ Build Tools.
#   powershell -ExecutionPolicy Bypass -File scripts\sora_host\build.ps1
# Run it again after updating Python to a new minor version (the DLL name changes).
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = Split-Path (Split-Path $here -Parent) -Parent
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$out = Join-Path $root ".venv\Scripts\Sora.exe"

# python314.dll for Python 3.14
$dll = & $venvPython -c "import sys; print(f'python{sys.version_info[0]}{sys.version_info[1]}.dll')"

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw "Visual Studio C++ Build Tools not found" }
$vcvars = Join-Path $vs "VC\Auxiliary\Build\vcvars64.bat"

$tmp = Join-Path $env:TEMP "sora_host_build"
New-Item -ItemType Directory -Force $tmp | Out-Null
$cmd = "`"$vcvars`" >nul && cd /d `"$here`" && rc /nologo /fo `"$tmp\sora_host.res`" sora_host.rc && " +
       "cl /nologo /O2 /W3 /MT /DUNICODE /D_UNICODE /DPY_DLL=L\`"$dll\`" /Fo`"$tmp\\`" sora_host.c `"$tmp\sora_host.res`" user32.lib " +
       "/link /SUBSYSTEM:WINDOWS /OUT:`"$out`""
cmd /c $cmd
if ($LASTEXITCODE -ne 0) { throw "build failed" }
"built $out ($dll)"
