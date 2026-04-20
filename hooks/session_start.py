#!/usr/bin/env python3
"""PDCA SessionStart hook:
  1. Persist current session pointer per cwd → ~/.pdca/sessions/<encoded>.json
     (so /pdca-done's reviewer can locate the transcript later).
  2. Inject up-to-N recent review summaries for *this* cwd into Claude's context.

Stdin: Claude Code hook input JSON {session_id, transcript_path, cwd, source, ...}
Stdout: {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PDCA_ROOT = Path.home() / ".pdca"
SESSIONS_DIR = PDCA_ROOT / "sessions"
REVIEWS_DIR = PDCA_ROOT / "reviews"
DISABLED_FILE = PDCA_ROOT / "disabled.json"
PLAN_REL = ".pdca/current_plan.md"
RECENT_N = 5
SUMMARY_MAX_CHARS = 800  # per review, when injecting

ACTIVE_PLAN_BANNER = """\
# PDCA mode: ACTIVE plan in this cwd

There is an **active plan** at `.pdca/current_plan.md`. Plan-gate is enforced:
Edit/Write to anything except the plan itself is blocked.

## Behavior rule (important)

When you believe the work in the current plan is **complete** (all 步骤 ticked,
M-criterion met), do NOT silently end the turn. **Ask the user**:

> "本次任务做完了, 触发 `/pdca-done` review 吗?(y/n,如果还没完请告诉我哪步还没做)"

Only after the user confirms should `/pdca-done` be invoked. If the user says
work is incomplete, update the plan instead.

## Toggle

User can `/pdca-off` to disable plan-gate in this cwd, `/pdca-on` to re-enable.
"""


def is_disabled(cwd: str) -> bool:
    if not DISABLED_FILE.is_file():
        return False
    try:
        items = json.loads(DISABLED_FILE.read_text(encoding="utf-8"))
        return isinstance(items, list) and cwd in items
    except (json.JSONDecodeError, OSError):
        return False


def parse_plan_status(cwd: str) -> str | None:
    """Return frontmatter status of .pdca/current_plan.md, or None if missing/malformed."""
    p = Path(cwd) / PLAN_REL
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
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


def encode_cwd(cwd: str) -> str:
    """Match Claude Code's encoding: '/' → '-', leading '-' kept (so '/Users/x' → '-Users-x')."""
    return cwd.replace("/", "-")


def persist_session_pointer(session_id: str, transcript_path: str, cwd: str) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    target = SESSIONS_DIR / f"{encode_cwd(cwd)}.json"
    payload = {
        "session_id": session_id,
        "transcript_path": transcript_path,
        "cwd": cwd,
        "ts": int(time.time()),
    }
    try:
        target.write_text(json.dumps(payload, indent=2))
    except OSError:
        pass  # best effort


def collect_recent_reviews(cwd: str) -> list[Path]:
    if not REVIEWS_DIR.is_dir():
        return []
    prefix = encode_cwd(cwd) + "__"
    candidates = [p for p in REVIEWS_DIR.iterdir() if p.is_file() and p.name.startswith(prefix)]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[:RECENT_N]


def review_summary(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    snippet = text[:SUMMARY_MAX_CHARS]
    if len(text) > SUMMARY_MAX_CHARS:
        snippet += "\n…(truncated)"
    return f"### {path.name}\n\n{snippet}"


def emit(additional_context: str | None) -> None:
    if not additional_context:
        sys.exit(0)
    out = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": additional_context,
        }
    }
    sys.stdout.write(json.dumps(out))
    sys.exit(0)


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        emit(None)
        return

    cwd = payload.get("cwd") or os.getcwd()
    session_id = payload.get("session_id", "")
    transcript_path = payload.get("transcript_path", "")

    if session_id and cwd:
        persist_session_pointer(session_id, transcript_path, cwd)

    if is_disabled(cwd):
        emit(None)
        return

    parts: list[str] = []

    if parse_plan_status(cwd) == "active":
        parts.append(ACTIVE_PLAN_BANNER)

    reviews = collect_recent_reviews(cwd)
    if reviews:
        parts.append("# PDCA — recent reviews (this cwd)\n")
        for p in reviews:
            s = review_summary(p)
            if s:
                parts.append(s)

    emit("\n\n".join(parts) if parts else None)


if __name__ == "__main__":
    main()
