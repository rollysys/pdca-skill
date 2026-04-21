#!/usr/bin/env python3
"""Persist per-session subagent usage for PDCA gating."""
from __future__ import annotations

import json
import time
from pathlib import Path

PDCA_ROOT = Path.home() / ".pdca"
SUBAGENT_SESSIONS_DIR = PDCA_ROOT / "subagents" / "by_session"


def _session_path(session_id: str) -> Path:
    return SUBAGENT_SESSIONS_DIR / f"{session_id}.json"


def load_state(session_id: str) -> dict:
    path = _session_path(session_id)
    if not path.is_file():
        return {"session_id": session_id, "completed_count": 0, "completed_agents": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"session_id": session_id, "completed_count": 0, "completed_agents": []}
    if not isinstance(data, dict):
        return {"session_id": session_id, "completed_count": 0, "completed_agents": []}
    data.setdefault("session_id", session_id)
    data.setdefault("completed_count", 0)
    data.setdefault("completed_agents", [])
    return data


def initialize_session(session_id: str, cwd: str) -> None:
    if not session_id:
        return
    SUBAGENT_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    payload = load_state(session_id)
    payload["cwd"] = cwd
    payload.setdefault("created_at", int(time.time()))
    payload["updated_at"] = int(time.time())
    _session_path(session_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def mark_subagent_completed(
    session_id: str,
    cwd: str,
    agent_id: str,
    agent_type: str,
    last_message: str,
) -> None:
    if not session_id:
        return
    SUBAGENT_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    payload = load_state(session_id)
    payload["cwd"] = cwd
    payload["updated_at"] = int(time.time())
    payload["completed_count"] = int(payload.get("completed_count", 0)) + 1
    agents = payload.get("completed_agents") or []
    if not isinstance(agents, list):
        agents = []
    agents.append(
        {
            "agent_id": agent_id,
            "agent_type": agent_type or "unknown",
            "last_message": (last_message or "").strip()[:400],
            "ts": int(time.time()),
        }
    )
    payload["completed_agents"] = agents[-10:]
    _session_path(session_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def has_completed_subagent(session_id: str, cwd: str) -> bool:
    if not session_id:
        return False
    payload = load_state(session_id)
    return payload.get("cwd") == cwd and int(payload.get("completed_count", 0)) > 0
