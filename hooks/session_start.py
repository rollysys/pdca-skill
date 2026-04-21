#!/usr/bin/env python3
"""PDCA SessionStart hook:
  1. Persist current session pointer metadata for the current session.
  2. Export session metadata into Bash env for /pdca-done.
  3. Inject concise lessons from recent reviews for *this* cwd into Claude's context.

Stdin: Claude Code hook input JSON {session_id, transcript_path, cwd, source, ...}
Stdout: {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from subagent_state import initialize_session

PDCA_ROOT = Path.home() / ".pdca"
SESSIONS_DIR = PDCA_ROOT / "sessions"
SESSIONS_BY_SESSION_DIR = SESSIONS_DIR / "by_session"
SESSIONS_BY_CWD_DIR = SESSIONS_DIR / "by_cwd"
REVIEWS_DIR = PDCA_ROOT / "reviews"
DISABLED_FILE = PDCA_ROOT / "disabled.json"
PLAN_REL = ".pdca/current_plan.md"
RECENT_N = 5
LESSON_MAX_ITEMS = 8

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

## Subagent rule

Before mutating code in the main thread, spawn at least one subagent and wait for
it to finish. PDCA plan-gate blocks main-thread code mutation until a completed
subagent has run in the current session.
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
    SESSIONS_BY_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_BY_CWD_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": session_id,
        "transcript_path": transcript_path,
        "cwd": cwd,
        "ts": int(time.time()),
    }
    try:
        (SESSIONS_BY_SESSION_DIR / f"{session_id}.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        (SESSIONS_BY_CWD_DIR / f"{encode_cwd(cwd)}.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass  # best effort


def collect_recent_reviews(cwd: str) -> list[Path]:
    if not REVIEWS_DIR.is_dir():
        return []
    prefix = encode_cwd(cwd) + "__"
    candidates = [p for p in REVIEWS_DIR.iterdir() if p.is_file() and p.name.startswith(prefix)]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[:RECENT_N]


def persist_session_env(session_id: str, transcript_path: str) -> None:
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if not env_file or not session_id or not transcript_path:
        return
    try:
        with Path(env_file).open("a", encoding="utf-8") as fh:
            fh.write(f"export PDCA_SESSION_ID={_sh_quote(session_id)}\n")
            fh.write(f"export PDCA_TRANSCRIPT_PATH={_sh_quote(transcript_path)}\n")
    except OSError:
        pass


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def extract_review_lessons(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    lessons = _extract_section_bullets(text, "## MEMORY CANDIDATES")
    if not lessons:
        lessons.extend(_extract_section_bullets(text, "## 4. 经验 (Experience worth keeping)"))
        lessons.extend(_extract_section_bullets(text, "## 5. 教训 (Lessons / pitfalls)"))

    verdict = _extract_final_verdict(text)
    items: list[str] = []
    if verdict:
        items.append(f"{path.stem}: {verdict}")
    for lesson in lessons:
        if lesson.lower() == "none":
            continue
        items.append(f"{path.stem}: {lesson}")
    return items


def _extract_section_bullets(text: str, heading: str) -> list[str]:
    start = text.find(heading)
    if start < 0:
        return []
    after = text[start + len(heading) :]
    lines = after.splitlines()
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


def _extract_final_verdict(text: str) -> str | None:
    marker = "## FINAL VERDICT"
    start = text.find(marker)
    if start < 0:
        return None
    after = text[start + len(marker) :]
    for line in after.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            return stripped[2:].strip()
        if stripped.startswith("## "):
            break
    return None


def build_lessons_context(cwd: str) -> str | None:
    seen: set[str] = set()
    items: list[str] = []
    for path in collect_recent_reviews(cwd):
        for item in extract_review_lessons(path):
            key = " ".join(item.lower().split())
            if key in seen:
                continue
            seen.add(key)
            items.append(f"- {item}")
            if len(items) >= LESSON_MAX_ITEMS:
                break
        if len(items) >= LESSON_MAX_ITEMS:
            break
    if not items:
        return None
    return "# PDCA — carried lessons (this cwd)\n\n" + "\n".join(items)


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
        persist_session_env(session_id, transcript_path)
        initialize_session(session_id, cwd)

    if is_disabled(cwd):
        emit(None)
        return

    parts: list[str] = []

    if parse_plan_status(cwd) == "active":
        parts.append(ACTIVE_PLAN_BANNER)

    lessons_context = build_lessons_context(cwd)
    if lessons_context:
        parts.append(lessons_context)

    emit("\n\n".join(parts) if parts else None)


if __name__ == "__main__":
    main()
