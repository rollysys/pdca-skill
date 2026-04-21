#!/usr/bin/env python3
"""Block stopping when PDCA requires a completed subagent first."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from subagent_state import has_completed_subagent

PLAN_REL = ".pdca/current_plan.md"
DISABLED_FILE = Path.home() / ".pdca" / "disabled.json"


def is_disabled(cwd: str) -> bool:
    if not DISABLED_FILE.is_file():
        return False
    try:
        items = json.loads(DISABLED_FILE.read_text(encoding="utf-8"))
        return isinstance(items, list) and cwd in items
    except (json.JSONDecodeError, OSError):
        return False


def parse_plan_status(cwd: str) -> str | None:
    path = Path(cwd) / PLAN_REL
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    for line in text[3:end].splitlines():
        line = line.strip()
        if line.startswith("status:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return None


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    cwd = payload.get("cwd") or os.getcwd()
    session_id = payload.get("session_id", "")
    if is_disabled(cwd):
        sys.exit(0)

    if parse_plan_status(cwd) != "active":
        sys.exit(0)

    if has_completed_subagent(session_id, cwd):
        sys.exit(0)

    sys.stderr.write(
        "PDCA stop-gate: active plan is still in progress, and no completed subagent "
        "has run in this session. Spawn a subagent first, let it finish, then continue.\n"
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
