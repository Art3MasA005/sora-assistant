"""Read the repo-root .env without importing sora (settings must be overridden before sora loads)."""

from __future__ import annotations

from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values
