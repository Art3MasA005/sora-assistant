"""PC settings Sora can change: screen brightness, Wi-Fi, Bluetooth and dark mode.

Each takes value (a level, or 1/0 for on/off); without one it reports how it is now.
"""

from __future__ import annotations

import ctypes
import json
import sys

from windows_actions import ActionError, _powershell

# The radios through Windows' own Radio API (the quick-settings switches), which needs no admin rights.
RADIO_SCRIPT = r"""
param($kind, $state)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
[Windows.Devices.Radios.Radio, Windows.System.Devices, ContentType = WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioAccessStatus, Windows.System.Devices, ContentType = WindowsRuntime] | Out-Null
Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
$radio = $radios | Where-Object { "$($_.Kind)" -eq $kind } | Select-Object -First 1
if (-not $radio) { throw "this PC has no $kind" }
if ($state -eq 'On' -or $state -eq 'Off') {
  [Windows.Devices.Radios.RadioState, Windows.System.Devices, ContentType = WindowsRuntime] | Out-Null
  $done = Await ($radio.SetStateAsync([Windows.Devices.Radios.RadioState]$state)) ([Windows.Devices.Radios.RadioAccessStatus])
  if ("$done" -ne 'Allowed') { throw "Windows did not allow it ($done)" }
}
@{ state = "$($radio.State)" } | ConvertTo-Json -Compress
"""

BRIGHTNESS_SCRIPT = r"""
param($level)
# $level is a number; -1 only reads it (an empty value could arrive as $null, and $null -ne '' is true)
$now = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $now) { throw "this screen's brightness can't be set from Windows (an external monitor sets its own)" }
if ([int]$level -ge 0) {
  $methods = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | Select-Object -First 1
  Invoke-CimMethod -InputObject $methods -MethodName WmiSetBrightness -Arguments @{ Timeout = 1; Brightness = [byte]$level } | Out-Null
  $now = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | Select-Object -First 1
}
@{ brightness = [int]$now.CurrentBrightness } | ConvertTo-Json -Compress
"""


def _on_off(params: dict) -> str:
    """"On", "Off" or "" (just tell): from value 1/0, or target on/off."""
    value = params.get("value")
    word = str(params.get("target") or "").strip().lower()
    if value is not None:
        return "On" if str(value) == "1" else "Off"
    return {"on": "On", "off": "Off"}.get(word, "")


def _radio(kind: str, params: dict) -> dict:
    out = _powershell(RADIO_SCRIPT, kind, _on_off(params), timeout=30)
    return json.loads(out or "{}")


def wifi(params: dict) -> dict:
    return {"wifi": _radio("WiFi", params).get("state")}


def bluetooth(params: dict) -> dict:
    return {"bluetooth": _radio("Bluetooth", params).get("state")}


def brightness_level(params: dict, current: int | None) -> int | None:
    """The level to set: value 0-100, or target up/down (10 at a time, from [current]); None: just tell."""
    word = str(params.get("target") or "").strip().lower()
    if params.get("value") is not None:
        level = int(params["value"])
    elif word in {"up", "down"} and current is not None:
        level = current + (10 if word == "up" else -10)
    else:
        return None
    return max(0, min(100, level))


def brightness(params: dict) -> dict:
    current = json.loads(_powershell(BRIGHTNESS_SCRIPT, "-1", timeout=30) or "{}").get("brightness")
    level = brightness_level(params, current)
    if level is None:
        return {"brightness": current}
    return json.loads(_powershell(BRIGHTNESS_SCRIPT, str(level), timeout=30) or "{}")


PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def dark_mode(params: dict) -> dict:
    """value=1 dark, 0 light (apps and Windows both); no value: which it is now."""
    if sys.platform != "win32":
        raise ActionError("dark mode is a Windows setting")
    import winreg

    on = _on_off(params)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
        if on:
            light = 0 if on == "On" else 1
            winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, light)
            winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, light)
            # Tell open windows the colours changed, so they follow without a restart.
            result = ctypes.c_size_t()
            ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "ImmersiveColorSet", 0x0002, 3000,
                                                     ctypes.byref(result))
        apps_light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
    return {"dark_mode": not apps_light}
