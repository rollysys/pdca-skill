---
description: 在当前 cwd 关闭 PDCA plan-gate(加入 disabled list)
allowed-tools: Bash
---

关闭当前 cwd 的 PDCA plan-gate(临时聊天/调试/紧急修补时用)。

调用 Bash:`python3 ~/.claude/skills/pdca/scripts/toggle.py off`

把 stdout 原样转给用户。提醒:"PDCA 已关,Edit/Write 直接放行。`/pdca-on` 重启。"
