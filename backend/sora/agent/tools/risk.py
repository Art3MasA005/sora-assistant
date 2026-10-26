"""Which shell commands are serious enough to ask the owner first.

The owner's rule: ordinary commands (run the script, the tests, install the requirements) just run;
only what deletes, turns something off, kills, wipes, rewrites history or reaches outside asks. Used
for the PC's run_command and VS Code's terminal (and commands that type into it).
"""

from __future__ import annotations

import re

_RISKY = re.compile(
    r"""
    # deleting files and folders
    \b(rm|rmdir|rd|del|erase|unlink|shred|Remove-Item|Clear-Content|Clear-RecycleBin)\b
    # turning the PC (or a service) off, ending processes
    | \b(shutdown|poweroff|halt|reboot|logoff|Stop-Computer|Restart-Computer|Stop-Process|Stop-Service|taskkill|tskill|pkill|killall)\b
    | \bkill\s+-
    | \b(sc|net)\s+(stop|delete)\b
    | rundll32[^\n]*powrprof
    # disks, the boot setup, the registry
    | \b(format)\s+[a-z]:
    | \b(diskpart|mkfs\S*|bcdedit|cipher\s+/w)\b
    | \bdd\s+if=
    | \breg\s+delete\b | \bRemove-ItemProperty\b
    # git that loses work or reaches outside
    | \bgit\s+(push|clean|reset\s+--hard|branch\s+-D|stash\s+(drop|clear)|checkout\s+--\s|restore\b)
    # removing software
    | \buninstall\b | \bwinget\s+remove\b
    # databases
    | \bdrop\s+(table|database|schema)\b | \btruncate\s+table\b
    # running what was just downloaded, or as someone else
    | (iwr|irm|Invoke-WebRequest|Invoke-RestMethod|curl|wget)\b[^\n]*\|\s*(iex|Invoke-Expression|sh|bash|python)\b
    | \b(runas|sudo)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def risky_command(command: str | None) -> bool:
    """Would running [command] delete, turn off, kill, wipe or push something?"""
    return bool(command) and _RISKY.search(command) is not None
