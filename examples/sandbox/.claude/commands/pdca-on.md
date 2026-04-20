---
description: 在当前 cwd 启用 PDCA plan-gate(从 disabled list 移除)
allowed-tools: Bash
---

启用当前 cwd 的 PDCA plan-gate。

调用 Bash:`python3 ~/.claude/skills/pdca/scripts/toggle.py on`

把 stdout 原样转给用户。如果用户没有 active plan,提醒一句:"现在 plan-gate 已开,要写 `.pdca/current_plan.md` 并把 status 设为 active 才能 Edit/Write。"
