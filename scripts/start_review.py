#!/usr/bin/env python3
"""PDCA Check: validate plan completion + run Claude review on the current session.

Usage:
  python3 start_review.py [--cwd PATH] [--timeout SECS] [--max-chars N]

Workflow:
  1. Read .pdca/current_plan.md (cwd), parse plan_slug.
  2. Resolve current session from explicit session metadata exported by SessionStart.
  3. Filter transcript: drop bulky tool_result bodies, keep prompts / assistant text
     / tool_use signatures.
  4. Validate completion evidence, then mark plan status: done.
  5. claude --print (synchronous) → write review to
     ~/.pdca/reviews/<encoded_cwd>__<plan_slug>__<sid>.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PDCA_ROOT = Path.home() / ".pdca"
SESSIONS_DIR = PDCA_ROOT / "sessions"
SESSIONS_BY_SESSION_DIR = SESSIONS_DIR / "by_session"
REVIEWS_DIR = PDCA_ROOT / "reviews"
SKILL_DIR = Path(__file__).resolve().parent.parent
PROMPT_PATH = SKILL_DIR / "scripts" / "review_prompt.md"
PLAN_REL = ".pdca/current_plan.md"

DEFAULT_TIMEOUT = 300
DEFAULT_MAX_CHARS = 320_000  # ~ reviewer-friendly transcript chunk size


def encode_cwd(cwd: str) -> str:
    return cwd.replace("/", "-")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm_block = text[3:end]
    body = text[end + 4 :].lstrip("\n")
    fm: dict[str, str] = {}
    for line in fm_block.splitlines():
        line = line.rstrip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body


def slug_from_h1(body: str) -> str:
    for line in body.splitlines():
        m = re.match(r"^#\s+Plan:\s*(.+)$", line.strip())
        if m:
            raw = m.group(1).strip()
            slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", raw).strip("-").lower()
            return slug[:60] or "plan"
    return "plan"


def mark_plan_done(plan_path: Path) -> None:
    text = plan_path.read_text(encoding="utf-8")
    new = re.sub(
        r"^status:\s*\S+\s*$",
        "status: done",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    plan_path.write_text(new, encoding="utf-8")


def load_session_pointer(session_id: str) -> dict[str, str]:
    p = SESSIONS_BY_SESSION_DIR / f"{session_id}.json"
    if not p.is_file():
        sys.exit(
            f"[pdca] no session pointer at {p}. "
            "SessionStart hook must have run in this exact session."
        )
    return json.loads(p.read_text(encoding="utf-8"))


def resolve_current_session(
    cwd: str,
    explicit_session_id: str,
    explicit_transcript_path: str,
) -> tuple[str, Path | None]:
    session_id = explicit_session_id or os.environ.get("PDCA_SESSION_ID", "")
    transcript_raw = explicit_transcript_path or os.environ.get("PDCA_TRANSCRIPT_PATH", "")

    if session_id:
        info = load_session_pointer(session_id)
        if info.get("cwd") != cwd:
            sys.exit(
                "[pdca] current session does not belong to this cwd. "
                "Refusing to review another session."
            )
        transcript_raw = transcript_raw or info.get("transcript_path", "")
    elif transcript_raw:
        session_id = "unknown-session"
    else:
        sys.exit(
            "[pdca] missing current session context. "
            "Run /pdca-done from the active Claude session after SessionStart exports "
            "PDCA_SESSION_ID and PDCA_TRANSCRIPT_PATH."
        )

    transcript_path = Path(transcript_raw) if transcript_raw else None
    return session_id, transcript_path


def filter_transcript(jsonl_path: Path, max_chars: int) -> str:
    """Slim Claude Code transcript: keep user/assistant text + tool_use header,
    drop tool_result bodies. Returns single text blob."""
    if not jsonl_path.is_file():
        return f"[transcript missing: {jsonl_path}]"
    out: list[str] = []
    used = 0
    with jsonl_path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            piece = _slim_event(ev)
            if not piece:
                continue
            n = len(piece) + 2
            if used + n > max_chars:
                out.append("…[truncated]")
                break
            out.append(piece)
            used += n
    return "\n\n".join(out)


def _slim_event(ev: dict) -> str | None:
    t = ev.get("type")
    if t == "user":
        msg = ev.get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return f"[user] {content.strip()}" if content.strip() else None
        if isinstance(content, list):
            parts = []
            for blk in content:
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") == "tool_result":
                    parts.append(f"[tool_result] (omitted, id={blk.get('tool_use_id', '?')})")
                elif blk.get("type") == "text":
                    parts.append(f"[user] {(blk.get('text') or '').strip()}")
            return "\n".join(p for p in parts if p) or None
        return None
    if t == "assistant":
        msg = ev.get("message") or {}
        parts = []
        for blk in msg.get("content") or []:
            if not isinstance(blk, dict):
                continue
            kind = blk.get("type")
            if kind == "text":
                parts.append(f"[assistant] {(blk.get('text') or '').strip()}")
            elif kind == "thinking":
                parts.append(f"[thinking] {(blk.get('thinking') or '').strip()[:400]}")
            elif kind == "tool_use":
                name = blk.get("name", "?")
                inp = blk.get("input") or {}
                # keep first 200 chars of input only
                summary = json.dumps(inp, ensure_ascii=False)[:200]
                parts.append(f"[tool_use] {name} {summary}")
        return "\n".join(p for p in parts if p.strip()) or None
    return None


def validate_plan_completion(plan_text: str) -> list[str]:
    failures: list[str] = []
    unchecked = re.findall(r"^\s*-\s*\[\s\]\s+.+$", plan_text, flags=re.MULTILINE)
    if unchecked:
        failures.append("plan still has unchecked steps")

    evidence = extract_evidence_block(plan_text)
    if not evidence:
        failures.append("plan is missing a non-empty '## 验收记录' section")
    return failures


def extract_evidence_block(plan_text: str) -> str:
    lines = plan_text.splitlines()
    capture = False
    buf: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if capture:
                break
            capture = stripped in {"## 验收记录", "## Evidence"}
            continue
        if capture:
            buf.append(line)

    text = "\n".join(buf).strip()
    if not text:
        return ""
    if any(token in text for token in ("<命令>", "<结果>", "TODO", "todo")):
        return ""
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cwd", default=os.getcwd(), help="Working directory (default $PWD)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    ap.add_argument("--session-id", default="", help="Current Claude session id")
    ap.add_argument("--transcript-path", default="", help="Current Claude transcript path")
    args = ap.parse_args()

    # Do NOT resolve symlinks here: must match the raw `cwd` that session_start.py
    # received from Claude Code (which is also unresolved). Otherwise the session
    # pointer lookup misses on macOS /tmp → /private/tmp aliases.
    cwd = args.cwd
    plan_path = Path(cwd) / PLAN_REL
    if not plan_path.is_file():
        sys.exit(f"[pdca] no plan at {plan_path}")
    plan_text = plan_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(plan_text)
    status = fm.get("status", "?")
    if status not in {"active", "done"}:
        sys.exit(f"[pdca] plan status='{status}', expected 'active' (or already 'done').")

    if status == "active":
        failures = validate_plan_completion(plan_text)
        if failures:
            sys.exit("[pdca] refusing to mark plan done: " + "; ".join(failures))

    plan_slug = fm.get("plan_slug") or slug_from_h1(body)
    sid, transcript_path = resolve_current_session(
        cwd=cwd,
        explicit_session_id=args.session_id,
        explicit_transcript_path=args.transcript_path,
    )

    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    review_path = REVIEWS_DIR / f"{encode_cwd(cwd)}__{plan_slug}__{sid}.md"

    if not PROMPT_PATH.is_file():
        sys.exit(f"[pdca] missing prompt template: {PROMPT_PATH}")
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    transcript_blob = (
        filter_transcript(transcript_path, args.max_chars)
        if transcript_path
        else "[no transcript path]"
    )
    stdin_blob = (
        f"=== PLAN ===\n{plan_text}\n\n"
        f"=== SESSION TRANSCRIPT (filtered) ===\n{transcript_blob}\n"
    )

    print(f"[pdca] running Claude review (timeout {args.timeout}s)…", file=sys.stderr)
    print(f"[pdca]   cwd     = {cwd}", file=sys.stderr)
    print(f"[pdca]   sid     = {sid}", file=sys.stderr)
    print(f"[pdca]   slug    = {plan_slug}", file=sys.stderr)
    print(f"[pdca]   review  → {review_path}", file=sys.stderr)
    t0 = time.time()
    try:
        proc = subprocess.run(
            [
                "claude",
                "--print",
                "--output-format",
                "text",
                "--bare",
                "--tools",
                "",
                "--system-prompt",
                prompt,
            ],
            input=stdin_blob,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            check=False,
        )
    except FileNotFoundError:
        sys.exit("[pdca] claude CLI not found in PATH")
    except subprocess.TimeoutExpired as e:
        partial = e.stdout or ""
        review_path.write_text(
            f"# PDCA review (TIMED OUT after {args.timeout}s)\n\n```\n{partial}\n```\n",
            encoding="utf-8",
        )
        sys.exit(f"[pdca] claude timeout; partial output saved to {review_path}")

    elapsed = time.time() - t0
    if proc.returncode != 0:
        review_path.write_text(
            f"# PDCA review (claude exit={proc.returncode})\n\n## stderr\n```\n{proc.stderr}\n```\n\n## stdout\n```\n{proc.stdout}\n```\n",
            encoding="utf-8",
        )
        sys.exit(f"[pdca] claude exit={proc.returncode}; output saved to {review_path}")

    header = (
        f"# PDCA Review — {plan_slug}\n\n"
        f"- session_id: `{sid}`\n"
        f"- cwd: `{cwd}`\n"
        f"- plan: `{plan_path}`\n"
        f"- generated: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n"
        f"- reviewer: `claude --print --bare`\n"
        f"- claude elapsed: {elapsed:.1f}s\n\n---\n\n"
    )
    review_path.write_text(header + proc.stdout, encoding="utf-8")

    if status == "active":
        mark_plan_done(plan_path)
        print(f"[pdca] plan marked done: {plan_path}", file=sys.stderr)

    print(str(review_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
