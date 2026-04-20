#!/usr/bin/env python3
"""Enable/disable PDCA mode for a specific cwd.

Storage: ~/.pdca/disabled.json — list of absolute cwd paths.
When a cwd is in the list, both hooks short-circuit (no gating, no injection).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PDCA_ROOT = Path.home() / ".pdca"
DISABLED_FILE = PDCA_ROOT / "disabled.json"


def load_disabled() -> list[str]:
    if not DISABLED_FILE.is_file():
        return []
    try:
        data = json.loads(DISABLED_FILE.read_text(encoding="utf-8"))
        return [str(x) for x in data] if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_disabled(items: list[str]) -> None:
    PDCA_ROOT.mkdir(parents=True, exist_ok=True)
    DISABLED_FILE.write_text(json.dumps(sorted(set(items)), indent=2))


def is_disabled(cwd: str) -> bool:
    return cwd in load_disabled()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=["on", "off", "status"])
    ap.add_argument("--cwd", default=os.getcwd())
    args = ap.parse_args()

    cwd = args.cwd
    items = load_disabled()

    if args.action == "off":
        if cwd not in items:
            items.append(cwd)
            save_disabled(items)
        print(f"[pdca] OFF for {cwd}")
        print(f"       disabled list: {DISABLED_FILE}")
    elif args.action == "on":
        if cwd in items:
            items = [x for x in items if x != cwd]
            save_disabled(items)
        print(f"[pdca] ON for {cwd}")
        print("       (plan-gate now active; write .pdca/current_plan.md status=active to allow Edit/Write)")
    else:  # status
        state = "OFF (disabled)" if cwd in items else "ON (active)"
        print(f"[pdca] {state} for {cwd}")
        if items:
            print("       all disabled cwds:")
            for x in items:
                print(f"         - {x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
