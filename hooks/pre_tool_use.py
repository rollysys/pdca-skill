#!/usr/bin/env python3
"""PDCA Plan-gate: block Edit/Write tools when no active plan.

Stdin: Claude Code hook input JSON
  {session_id, cwd, hook_event_name, tool_name, tool_input, tool_use_id}

Stdout (deny):
  {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                          "permissionDecision": "deny",
                          "permissionDecisionReason": "..."}}

Empty stdout + exit 0 = passthrough (default permission system runs).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

GATED_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
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


def deny(reason: str) -> None:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(out))
    sys.exit(0)


def passthrough() -> None:
    sys.exit(0)


def parse_status(plan_path: Path) -> str | None:
    """Return frontmatter status field, or None if file missing/malformed."""
    if not plan_path.is_file():
        return None
    try:
        text = plan_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    fm = text[3:end]
    for line in fm.splitlines():
        line = line.strip()
        if line.startswith("status:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return None


def is_plan_self_target(tool_input: dict, cwd: Path) -> bool:
    """Allow editing the plan file itself (bootstrap)."""
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not target:
        return False
    try:
        p = Path(target).expanduser()
        if not p.is_absolute():
            p = (cwd / p).resolve()
        else:
            p = p.resolve()
        plan_abs = (cwd / PLAN_REL).resolve()
        return p == plan_abs
    except (OSError, ValueError):
        return False


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        passthrough()
        return

    tool_name = payload.get("tool_name", "")
    if tool_name not in GATED_TOOLS:
        passthrough()
        return

    cwd_str = payload.get("cwd") or os.getcwd()
    if is_disabled(cwd_str):
        passthrough()
        return

    cwd = Path(cwd_str)
    tool_input = payload.get("tool_input") or {}

    if is_plan_self_target(tool_input, cwd):
        passthrough()
        return

    plan_path = cwd / PLAN_REL
    status = parse_status(plan_path)

    if status is None:
        deny(
            f"PDCA plan-gate: no plan at {PLAN_REL}. "
            "Write SMART plan with frontmatter `status: active` before editing code. "
            "Template: ~/.claude/skills/pdca/plan_template.md"
        )
        return

    if status != "active":
        deny(
            f"PDCA plan-gate: plan status='{status}', must be 'active' to allow Edit/Write. "
            "Either flip status to 'active' (if work is starting) or write a new plan "
            "(if previous one is done)."
        )
        return

    passthrough()


if __name__ == "__main__":
    main()
