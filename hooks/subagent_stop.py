#!/usr/bin/env python3
"""Record completed subagent work for the current PDCA session."""
from __future__ import annotations

import json
import os
import sys

from subagent_state import mark_subagent_completed


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    session_id = payload.get("session_id", "")
    cwd = payload.get("cwd") or os.getcwd()
    agent_id = payload.get("agent_id", "")
    agent_type = payload.get("agent_type", "")
    last_message = payload.get("last_assistant_message", "")

    try:
        mark_subagent_completed(
            session_id=session_id,
            cwd=cwd,
            agent_id=agent_id,
            agent_type=agent_type,
            last_message=last_message,
        )
    except OSError:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
