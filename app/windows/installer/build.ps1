# Builds the Sora Windows installer: release build, MSVC runtime, Inno Setup.
$ErrorActionPreference = 'Stop'
$app = Resolve-Path "$PSScriptRoot\..\.."
$env:PATH = "$app\..\data\tools;$env:PATH"   # nuget.exe for flutter_tts

Push-Location $app
try {
    flutter build windows --release
    if ($LASTEXITCODE) { throw "flutter build failed" }

    $release = "$app\build\windows\x64\runner\Release"
    foreach ($dll in 'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll') {
        Copy-Item "$env:WINDIR\System32\$dll" $release -Force
    }

    $iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
              "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) { throw "Inno Setup 6 not found (winget install JRSoftware.InnoSetup)" }
    & $iscc "$PSScriptRoot\sora.iss"
    if ($LASTEXITCODE) { throw "ISCC failed" }
} finally { Pop-Location }
