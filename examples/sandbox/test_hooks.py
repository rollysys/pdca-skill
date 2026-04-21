#!/usr/bin/env python3
"""Offline simulation of the PDCA hooks (no real Claude Code session needed).

Feeds canned hook-input JSON into the scripts and asserts on stdout/exit-code.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

SANDBOX = Path(__file__).resolve().parent
PLAN_DIR = SANDBOX / ".pdca"
PLAN = PLAN_DIR / "current_plan.md"
# The hooks live in a PDCA skill checkout. Override via PDCA_SKILL_DIR if needed.
SKILL_DIR = Path(
    os.environ.get("PDCA_SKILL_DIR", str(Path.home() / ".claude" / "skills" / "pdca"))
)
HOOKS = SKILL_DIR / "hooks"
PRE = HOOKS / "pre_tool_use.py"
SS = HOOKS / "session_start.py"
SUBSTOP = HOOKS / "subagent_stop.py"
TOGGLE = SKILL_DIR / "scripts" / "toggle.py"
START_REVIEW = SKILL_DIR / "scripts" / "start_review.py"
REVIEWS = Path.home() / ".pdca" / "reviews"
SESSIONS = Path.home() / ".pdca" / "sessions"
SESSIONS_BY_CWD = SESSIONS / "by_cwd"
SESSIONS_BY_SESSION = SESSIONS / "by_session"
SUBAGENTS = Path.home() / ".pdca" / "subagents" / "by_session"
DISABLED = Path.home() / ".pdca" / "disabled.json"

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"


def run_hook(script: Path, payload: dict, env: dict | None = None) -> tuple[int, str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    p = subprocess.run(
        ["python3", str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=merged_env,
    )
    return p.returncode, p.stdout


def run_script(args: list[str], env: dict | None = None) -> tuple[int, str, str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    p = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=10,
        env=merged_env,
    )
    return p.returncode, p.stdout, p.stderr


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
    if SUBAGENTS.exists():
        for p in SUBAGENTS.glob("*.json"):
            if p.name.startswith("test-sid-123") or p.name.startswith("ss-sid-1"):
                p.unlink()


def write_plan(status: str, *, with_evidence: bool = False, all_done: bool = False):
    PLAN_DIR.mkdir(exist_ok=True)
    steps = "- [x] step 1\n- [x] step 2\n" if all_done else "- [ ] step 1\n- [ ] step 2\n"
    evidence = (
        "## 验收记录\n\n- command: python3 -m pytest\n- result: 14/14 passed\n\n"
        if with_evidence
        else ""
    )
    PLAN.write_text(
        f"---\nstatus: {status}\nplan_slug: test\n---\n# Plan: smoke test\n\n"
        "## SMART\n\n"
        "- **M** (Measurable): run tests\n\n"
        "## 步骤\n\n"
        f"{steps}\n"
        f"{evidence}"
    )


def base_input(tool_name: str, file_path: str = "", command: str = "") -> dict:
    tool_input = {}
    if file_path:
        tool_input["file_path"] = file_path
    if command:
        tool_input["command"] = command
    return {
        "session_id": "test-sid-123",
        "transcript_path": "/tmp/fake.jsonl",
        "cwd": str(SANDBOX),
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
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
    results.append(expect_deny(rc, out, "plan=active + no subagent + Edit other → deny", "subagent-gate"))

    rc, out = run_hook(
        SUBSTOP,
        {
            "session_id": "test-sid-123",
            "cwd": str(SANDBOX),
            "hook_event_name": "SubagentStop",
            "agent_id": "agent-1",
            "agent_type": "Explore",
            "agent_transcript_path": "/tmp/agent.jsonl",
            "last_assistant_message": "done",
            "stop_hook_active": False,
        },
    )
    results.append(expect_passthrough(rc, out, "SubagentStop records completed subagent"))

    rc, out = run_hook(PRE, base_input("Edit", "/tmp/foo.txt"))
    results.append(expect_passthrough(rc, out, "plan=active + completed subagent + Edit other → passthrough"))

    write_plan("done")
    rc, out = run_hook(PRE, base_input("Write", "/tmp/foo.txt"))
    results.append(expect_deny(rc, out, "plan=done + Write other → deny", "done"))

    rc, out = run_hook(PRE, base_input("Read", "/tmp/foo.txt"))
    results.append(expect_passthrough(rc, out, "Read tool (not gated) → passthrough"))

    reset_sandbox()
    rc, out = run_hook(PRE, base_input("Bash", command="git status"))
    results.append(expect_passthrough(rc, out, "no plan + read-only Bash → passthrough"))

    rc, out = run_hook(PRE, base_input("Bash", command="echo hi > hello.txt"))
    results.append(expect_deny(rc, out, "no plan + mutating Bash → deny", "mutating Bash"))

    rc, out = run_hook(PRE, base_input("Bash", command="cat > .pdca/current_plan.md <<'EOF'\n---\nstatus: draft\nEOF"))
    results.append(expect_passthrough(rc, out, "no plan + Bash write plan itself → passthrough"))

    print("\n=== SessionStart hook tests ===\n")

    enc = str(SANDBOX).replace("/", "-")
    if SESSIONS_BY_CWD.exists():
        for p in SESSIONS_BY_CWD.glob(f"{enc}.json"):
            p.unlink()
    if SESSIONS_BY_SESSION.exists():
        for p in SESSIONS_BY_SESSION.glob("ss-sid-1.json"):
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

    with tempfile.NamedTemporaryFile("w+", delete=False) as envf:
        env_path = envf.name
    rc, out = run_hook(SS, payload, env={"CLAUDE_ENV_FILE": env_path})
    pointer = SESSIONS_BY_CWD / f"{enc}.json"
    session_pointer = SESSIONS_BY_SESSION / "ss-sid-1.json"
    subagent_session = SUBAGENTS / "ss-sid-1.json"
    ok_ptr = (
        pointer.is_file()
        and session_pointer.is_file()
        and subagent_session.is_file()
        and json.loads(pointer.read_text())["session_id"] == "ss-sid-1"
        and json.loads(session_pointer.read_text())["cwd"] == str(SANDBOX)
        and json.loads(subagent_session.read_text()).get("completed_count") == 0
    )
    print(f"{PASS if ok_ptr else FAIL}  session pointers and subagent state initialized")
    results.append(ok_ptr)

    env_text = Path(env_path).read_text()
    ok_env = "PDCA_SESSION_ID='ss-sid-1'" in env_text and "PDCA_TRANSCRIPT_PATH='/tmp/fake.jsonl'" in env_text
    print(f"{PASS if ok_env else FAIL}  session env exported for Bash commands")
    results.append(ok_env)
    Path(env_path).unlink(missing_ok=True)

    print(f"{PASS if rc == 0 and not out.strip() else FAIL}  no reviews → empty stdout (rc={rc})")
    results.append(rc == 0 and not out.strip())

    REVIEWS.mkdir(parents=True, exist_ok=True)
    fake_review = REVIEWS / f"{enc}__test__ss-sid-0.md"
    fake_review.write_text(
        "# Fake review\n\n"
        "## MEMORY CANDIDATES\n\n"
        "- KEEP: grep before read when narrowing scope\n"
        "- AVOID: marking plans done without evidence\n\n"
        "## FINAL VERDICT\n\n"
        "- **plan 完成度**: full | **review 净价值**: high\n"
    )
    rc, out = run_hook(SS, payload)
    has_ctx = False
    if rc == 0 and out.strip():
        try:
            j = json.loads(out)
            ctx = j["hookSpecificOutput"]["additionalContext"]
            has_ctx = "PDCA — carried lessons" in ctx and "KEEP: grep before read" in ctx
        except (json.JSONDecodeError, KeyError):
            pass
    print(f"{PASS if has_ctx else FAIL}  review present → lessons injected as additionalContext")
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

    print("\n=== start_review validation ===\n")
    write_plan("active", with_evidence=False, all_done=False)
    rc, out, err = run_script(
        ["python3", str(START_REVIEW), "--cwd", str(SANDBOX), "--session-id", "ss-sid-1", "--transcript-path", "/tmp/fake.jsonl"]
    )
    ok = rc != 0 and "unchecked steps" in err
    print(f"{PASS if ok else FAIL}  start_review rejects unchecked steps")
    results.append(ok)

    write_plan("active", with_evidence=False, all_done=True)
    rc, out, err = run_script(
        ["python3", str(START_REVIEW), "--cwd", str(SANDBOX), "--session-id", "ss-sid-1", "--transcript-path", "/tmp/fake.jsonl"]
    )
    ok = rc != 0 and "验收记录" in err
    print(f"{PASS if ok else FAIL}  start_review rejects missing evidence")
    results.append(ok)

    reset_sandbox()
    n = len(results)
    ok = sum(1 for r in results if r)
    print(f"\n=== {ok}/{n} passed ===")
    return 0 if ok == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
