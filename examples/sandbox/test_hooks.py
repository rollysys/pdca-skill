#!/usr/bin/env python3
"""Offline simulation of the PDCA hooks (no real Claude Code session needed).

Feeds canned hook-input JSON into the scripts and asserts on stdout/exit-code.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

SANDBOX = Path(__file__).resolve().parent
PLAN_DIR = SANDBOX / ".pdca"
PLAN = PLAN_DIR / "current_plan.md"
# The hooks live with the installed skill, which is expected at the default
# path. Override via PDCA_SKILL_DIR if you installed it elsewhere.
import os  # noqa: E402
SKILL_DIR = Path(
    os.environ.get("PDCA_SKILL_DIR", str(Path.home() / ".claude" / "skills" / "pdca"))
)
HOOKS = SKILL_DIR / "hooks"
PRE = HOOKS / "pre_tool_use.py"
SS = HOOKS / "session_start.py"
TOGGLE = SKILL_DIR / "scripts" / "toggle.py"
REVIEWS = Path.home() / ".pdca" / "reviews"
SESSIONS = Path.home() / ".pdca" / "sessions"
DISABLED = Path.home() / ".pdca" / "disabled.json"

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"


def run_hook(script: Path, payload: dict) -> tuple[int, str]:
    p = subprocess.run(
        ["python3", str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return p.returncode, p.stdout


def expect_passthrough(rc: int, out: str, label: str) -> bool:
    ok = rc == 0 and not out.strip()
    print(f"{PASS if ok else FAIL}  {label} (rc={rc} stdout={out.strip()!r})")
    return ok


def expect_deny(rc: int, out: str, label: str, reason_substr: str = "") -> bool:
    ok = rc == 0
    if ok:
        try:
            j = json.loads(out)
            d = j["hookSpecificOutput"]["permissionDecision"]
            r = j["hookSpecificOutput"].get("permissionDecisionReason", "")
            ok = d == "deny" and (reason_substr in r if reason_substr else True)
        except (json.JSONDecodeError, KeyError):
            ok = False
    print(f"{PASS if ok else FAIL}  {label} (rc={rc}, out={out[:120]!r})")
    return ok


def reset_sandbox():
    if PLAN_DIR.exists():
        shutil.rmtree(PLAN_DIR)


def write_plan(status: str):
    PLAN_DIR.mkdir(exist_ok=True)
    PLAN.write_text(
        f"---\nstatus: {status}\nplan_slug: test\n---\n# Plan: smoke test\n"
    )


def base_input(tool_name: str, file_path: str = "") -> dict:
    return {
        "session_id": "test-sid-123",
        "transcript_path": "/tmp/fake.jsonl",
        "cwd": str(SANDBOX),
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {"file_path": file_path} if file_path else {},
        "tool_use_id": "tu_123",
    }


def main():
    print("\n=== PreToolUse hook tests ===\n")
    results = []

    reset_sandbox()
    rc, out = run_hook(PRE, base_input("Write", "/tmp/foo.txt"))
    results.append(expect_deny(rc, out, "no plan + Write /tmp/foo.txt → deny", "no plan"))

    reset_sandbox()
    rc, out = run_hook(PRE, base_input("Write", str(PLAN)))
    results.append(expect_passthrough(rc, out, "no plan + Write the plan itself → passthrough"))

    write_plan("draft")
    rc, out = run_hook(PRE, base_input("Edit", "/tmp/foo.txt"))
    results.append(expect_deny(rc, out, "plan=draft + Edit other → deny", "draft"))

    write_plan("active")
    rc, out = run_hook(PRE, base_input("Edit", "/tmp/foo.txt"))
    results.append(expect_passthrough(rc, out, "plan=active + Edit other → passthrough"))

    write_plan("done")
    rc, out = run_hook(PRE, base_input("Write", "/tmp/foo.txt"))
    results.append(expect_deny(rc, out, "plan=done + Write other → deny", "done"))

    rc, out = run_hook(PRE, base_input("Read", "/tmp/foo.txt"))
    results.append(expect_passthrough(rc, out, "Read tool (not gated) → passthrough"))

    rc, out = run_hook(PRE, base_input("Bash"))
    results.append(expect_passthrough(rc, out, "Bash tool (not gated) → passthrough"))

    print("\n=== SessionStart hook tests ===\n")

    enc = str(SANDBOX).replace("/", "-")
    if SESSIONS.exists():
        for p in SESSIONS.glob(f"{enc}.json"):
            p.unlink()
    if REVIEWS.exists():
        for p in REVIEWS.glob(f"{enc}__*.md"):
            p.unlink()

    payload = {
        "session_id": "ss-sid-1",
        "transcript_path": "/tmp/fake.jsonl",
        "cwd": str(SANDBOX),
        "hook_event_name": "SessionStart",
        "source": "startup",
    }

    rc, out = run_hook(SS, payload)
    pointer = SESSIONS / f"{enc}.json"
    ok_ptr = pointer.is_file() and json.loads(pointer.read_text())["session_id"] == "ss-sid-1"
    print(f"{PASS if ok_ptr else FAIL}  session pointer written to {pointer.name}")
    results.append(ok_ptr)

    print(f"{PASS if rc == 0 and not out.strip() else FAIL}  no reviews → empty stdout (rc={rc})")
    results.append(rc == 0 and not out.strip())

    REVIEWS.mkdir(parents=True, exist_ok=True)
    fake_review = REVIEWS / f"{enc}__test__ss-sid-0.md"
    fake_review.write_text("# Fake review\n\nSome content.\n")
    rc, out = run_hook(SS, payload)
    has_ctx = False
    if rc == 0 and out.strip():
        try:
            j = json.loads(out)
            ctx = j["hookSpecificOutput"]["additionalContext"]
            has_ctx = "Fake review" in ctx and "PDCA — recent reviews" in ctx
        except (json.JSONDecodeError, KeyError):
            pass
    print(f"{PASS if has_ctx else FAIL}  review present → injected as additionalContext")
    results.append(has_ctx)
    fake_review.unlink(missing_ok=True)

    print("\n=== Active-plan banner ===\n")
    write_plan("active")
    rc, out = run_hook(SS, payload)
    has_banner = False
    if rc == 0 and out.strip():
        try:
            j = json.loads(out)
            ctx = j["hookSpecificOutput"]["additionalContext"]
            has_banner = "PDCA mode: ACTIVE plan" in ctx and "/pdca-done" in ctx
        except (json.JSONDecodeError, KeyError):
            pass
    print(f"{PASS if has_banner else FAIL}  active plan → SessionStart banner injected")
    results.append(has_banner)
    reset_sandbox()

    print("\n=== Toggle (on/off) ===\n")
    # Snapshot disabled.json so we don't permanently change user state
    backup = DISABLED.read_text() if DISABLED.exists() else None
    try:
        # Disable sandbox
        subprocess.run(["python3", str(TOGGLE), "off", "--cwd", str(SANDBOX)],
                       capture_output=True, check=True)
        rc, out = run_hook(PRE, base_input("Write", "/tmp/whatever.txt"))
        results.append(expect_passthrough(rc, out, "disabled cwd + Write → passthrough (gate bypassed)"))

        # Even with active plan, banner should NOT inject when disabled
        write_plan("active")
        rc, out = run_hook(SS, payload)
        ok = rc == 0 and not out.strip()
        print(f"{PASS if ok else FAIL}  disabled cwd → SessionStart no injection (rc={rc} out_empty={not out.strip()})")
        results.append(ok)
        reset_sandbox()

        # Re-enable
        subprocess.run(["python3", str(TOGGLE), "on", "--cwd", str(SANDBOX)],
                       capture_output=True, check=True)
        rc, out = run_hook(PRE, base_input("Write", "/tmp/whatever.txt"))
        results.append(expect_deny(rc, out, "re-enabled + Write (no plan) → deny", "no plan"))
    finally:
        # Restore state
        if backup is None:
            DISABLED.unlink(missing_ok=True)
        else:
            DISABLED.write_text(backup)

    reset_sandbox()
    n = len(results)
    ok = sum(1 for r in results if r)
    print(f"\n=== {ok}/{n} passed ===")
    return 0 if ok == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
