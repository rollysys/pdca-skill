#!/usr/bin/env python3
"""PDCA Plan-gate: block code mutation tools when no active plan.

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
import re
import shlex
import sys
from pathlib import Path

from subagent_state import has_completed_subagent

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
BASH_TOOL = "Bash"
PLAN_REL = ".pdca/current_plan.md"
DISABLED_FILE = Path.home() / ".pdca" / "disabled.json"
SAFE_BASH_PREFIXES = (
    "ls",
    "pwd",
    "cat",
    "head",
    "tail",
    "wc",
    "stat",
    "tree",
    "find",
    "rg",
    "grep",
    "sed -n",
    "awk ",
    "jq ",
    "git status",
    "git diff",
    "git log",
    "git show",
    "git grep",
    "git rev-parse",
    "git branch",
    "pytest",
    "python -m pytest",
    "uv run pytest",
    "npm test",
    "pnpm test",
    "yarn test",
    "cargo test",
    "go test",
    "make test",
)
MUTATING_BASH_PATTERNS = (
    r"(^|[^\w])(>|>>|1>|2>|&>|<<<)",
    r"\btee\b",
    r"\brm\b",
    r"\bmv\b",
    r"\bcp\b",
    r"\binstall\b",
    r"\bmkdir\b",
    r"\btouch\b",
    r"\bln\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\btruncate\b",
    r"\bdd\b",
    r"\bpatch\b",
    r"\bgit\s+apply\b",
    r"\bsed\s+-i\b",
    r"\bperl\s+-p[i0-9]*\b",
    r"\bnpm\s+install\b",
    r"\bpnpm\s+install\b",
    r"\byarn\s+install\b",
    r"\bpip(?:3)?\s+install\b",
    r"\buv\s+pip\s+install\b",
    r"\bpoetry\s+add\b",
    r"\bcargo\s+add\b",
    r"\bgo\s+generate\b",
    r"\bmake\b(?!\s+test\b)",
)


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


def bash_command(tool_input: dict) -> str:
    for key in ("command", "cmd", "bash_command"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def is_safe_readonly_bash(command: str) -> bool:
    compact = " ".join(command.split())
    if not compact:
        return False
    return any(compact == prefix or compact.startswith(prefix + " ") for prefix in SAFE_BASH_PREFIXES)


def is_plan_only_bash_write(command: str) -> bool:
    return ".pdca/current_plan.md" in command and not re.search(
        r"(^|[^\w])(\.\./|/etc/|/usr/|/var/|/tmp/)",
        command,
    )


def is_mutating_bash(command: str) -> bool:
    compact = " ".join(command.split())
    if not compact:
        return False
    for pattern in MUTATING_BASH_PATTERNS:
        if re.search(pattern, compact):
            return True
    try:
        parts = shlex.split(compact)
    except ValueError:
        return True
    if not parts:
        return False
    return False


def deny_missing_subagent() -> None:
    deny(
        "PDCA subagent-gate: active plan is present, but no completed subagent has run "
        "in this session yet. Before mutating code, spawn a subagent (for example "
        "Explore/Plan/custom agent), wait for it to finish, then continue."
    )


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        passthrough()
        return

    tool_name = payload.get("tool_name", "")
    if tool_name not in WRITE_TOOLS and tool_name != BASH_TOOL:
        passthrough()
        return

    cwd_str = payload.get("cwd") or os.getcwd()
    if is_disabled(cwd_str):
        passthrough()
        return

    cwd = Path(cwd_str)
    tool_input = payload.get("tool_input") or {}

    if tool_name in WRITE_TOOLS and is_plan_self_target(tool_input, cwd):
        passthrough()
        return

    if tool_name == BASH_TOOL:
        command = bash_command(tool_input)
        if is_safe_readonly_bash(command):
            passthrough()
            return
        if is_plan_only_bash_write(command):
            passthrough()
            return

    plan_path = cwd / PLAN_REL
    status = parse_status(plan_path)

    if status == "active":
        session_id = payload.get("session_id", "")
        if not has_completed_subagent(session_id, cwd_str):
            deny_missing_subagent()
            return
        passthrough()
        return

    if tool_name == BASH_TOOL:
        command = bash_command(tool_input)
        if is_mutating_bash(command):
            deny(
                "PDCA plan-gate: mutating Bash is blocked until `.pdca/current_plan.md` "
                "has frontmatter `status: active`. Only read-only inspection/test commands "
                "or writes to the plan itself are allowed before the plan is active."
            )
            return
        deny(
            "PDCA plan-gate: Bash command is not recognized as read-only. "
            "Before the plan is active, only inspection/test commands or writes to "
            "`.pdca/current_plan.md` are allowed."
        )
        return

    if status is None:
        deny(
            f"PDCA plan-gate: no plan at {PLAN_REL}. "
            "Write SMART plan with frontmatter `status: active` before editing code. "
            "Template: ~/.claude/skills/pdca/plan_template.md"
        )
        return

    deny(
        f"PDCA plan-gate: plan status='{status}', must be 'active' to allow Edit/Write. "
        "Either flip status to 'active' (if work is starting) or write a new plan "
        "(if previous one is done)."
    )


if __name__ == "__main__":
    main()
