"""The PC agent's pure logic, testable on any OS: `python -m pytest pc_agent/tests` (Windows calls are stubbed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
