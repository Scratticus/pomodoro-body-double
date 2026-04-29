#!/usr/bin/env python3
"""
From-clone runner. Resolves pomodoro-open/ relative to this file and starts the
Claude Code adapter against the default data dir (~/.claude/productivity/).

For installed use, install.sh writes a launcher to ~/.claude/productivity/
that points at this clone's adapter directly.
"""

import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ADAPTER_PATH = os.path.join(SCRIPT_DIR, "pomodoro-open", "adapter_claude.py")

if __name__ == "__main__":
    sys.exit(subprocess.run(
        ["python3", ADAPTER_PATH],
        cwd=os.path.join(SCRIPT_DIR, "pomodoro-open"),
    ).returncode)
