#!/usr/bin/env python3
"""Install PDCA into a target project's .claude directory.

Default target is the current working directory.
"""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_NAME = "pdca"


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--project-dir",
        default=os.getcwd(),
        help="Target project root (default: current working directory)",
    )
    args = ap.parse_args()

    project_dir = Path(args.project_dir).resolve()
    claude_dir = project_dir / ".claude"
    commands_dir = claude_dir / "commands"
    skill_dir = claude_dir / "skills" / SKILL_NAME

    claude_dir.mkdir(parents=True, exist_ok=True)
    commands_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "skills").mkdir(parents=True, exist_ok=True)

    copy_tree(REPO_ROOT, skill_dir)

    for name in ("pdca-done.md", "pdca-on.md", "pdca-off.md"):
        shutil.copy2(REPO_ROOT / "commands" / name, commands_dir / name)

    settings_src = REPO_ROOT / "templates" / "project_settings.json"
    shutil.copy2(settings_src, claude_dir / "settings.json")

    print(f"[pdca] installed into {project_dir}")
    print(f"[pdca] skill     -> {skill_dir}")
    print(f"[pdca] commands  -> {commands_dir}")
    print(f"[pdca] settings  -> {claude_dir / 'settings.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
