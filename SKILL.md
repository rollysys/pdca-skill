---
name: pdca
description: 用 hook 强制 PDCA 工作流。无 active plan 就拦 Edit/Write,plan done 后用 codex 独立 review,review 摘要在下次 SessionStart 注入。当用户说"启用 pdca"、"按 PDCA 干"、"开 plan-gate"时触发。
---

# pdca — Plan-gate + 独立 Check

## 设计

工作必经四步:
- **Plan**: 写 `.pdca/current_plan.md` (cwd 内), frontmatter `status: active` + SMART 五维
- **Do**: Edit/Write 才放行;期间遵守 git unstaged-fear 等纪律
- **Check**: 用户敲 `/pdca-done` → mark plan done → 起一个 **codex 独立 reviewer** 对 session 做五维评(效率/成本/方法/经验/教训)
- **Action**: reviewer 输出落 `~/.pdca/reviews/<sid>_<plan_slug>.md`,**下次** SessionStart hook 把最近 5 条注入

为什么 reviewer 用 codex 而不是当前 claude 自审:被强迫的自审 = 屎(参见 youremember v1)。独立视角才有"判断该不该留"的余地。

## 文件

```
~/.claude/skills/pdca/
├── SKILL.md                    # 本文件
├── plan_template.md            # .pdca/current_plan.md 的模板
├── hooks/
│   ├── pre_tool_use.py         # 拦 Edit/Write,允许写 plan 自身,disabled list 短路
│   └── session_start.py        # 写 session 指针 + 注 active-plan banner + 注 reviews
├── commands/
│   ├── pdca-done.md            # /pdca-done — 触发独立 review
│   ├── pdca-on.md              # /pdca-on  — 启用 plan-gate (本 cwd)
│   └── pdca-off.md             # /pdca-off — 关闭 plan-gate (本 cwd)
└── scripts/
    ├── start_review.py         # 标 plan done + 跑 codex
    ├── review_prompt.md        # codex 五维 prompt
    └── toggle.py               # on/off/status — 维护 disabled list
```

外部状态(全局):
- `~/.pdca/reviews/<encoded_cwd>__<slug>__<sid>.md` — 历史 review
- `~/.pdca/sessions/<encoded_cwd>.json` — 每个 cwd 的"当前 session 指针"(SessionStart 写,reviewer 读)
- `~/.pdca/disabled.json` — 临时禁用 PDCA 的 cwd 列表

## 启用方式

**不动 `~/.claude/settings.json`**(不要污染全局)。要在某个项目里启用 PDCA,在该项目根创建 `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "python3 /Users/x/.claude/skills/pdca/hooks/pre_tool_use.py"}]}
    ],
    "SessionStart": [
      {"hooks": [{"type": "command", "command": "python3 /Users/x/.claude/skills/pdca/hooks/session_start.py"}]}
    ]
  }
}
```

参考实例:`~/pdca-sandbox/.claude/settings.json`。

## 动态控制

- `/pdca-on` — 启用本 cwd 的 plan-gate(若需要可再开 active plan)
- `/pdca-off` — 暂时关闭本 cwd 的 plan-gate(临时改 / 紧急修补 / 聊天调试时用)
- `/pdca-done` — agent 在 plan 完成时**先问用户确认**,得到 yes 再 invoke,触发 codex review

底层 toggle:`python3 ~/.claude/skills/pdca/scripts/toggle.py {on|off|status}`

注:动态 on/off 不修改 `.claude/settings.json`,只改 `~/.pdca/disabled.json`,所以 git 工作区不会被搅动。

## Active-plan banner (agent 行为约束)

当 plan 是 active 状态时,SessionStart hook 会向 agent 注入一段行为指令:
"工作完成时,**不要静悄悄结束**,先 ask 用户'要 /pdca-done 吗?',得到 y 再触发"。
这样把"主动 check 完成度"做成 agent 默认习惯,而不依赖用户每次想起来。

## 设计取舍

- **只拦 Edit/Write,不拦 Bash**: Bash 太宽(git status/ls/test 都过它),拦了体验崩。Plan-gate 锁的是"代码变更",不是"探索"。
- **写 plan 自身永远放行**: 否则 bootstrap 死锁。`.pdca/current_plan.md` 的 file_path 命中就直接 allow。
- **Plan 必须 status=active 才放行**: `draft` 表示用户还在打磨,`done` 表示已交付。两者都不该再动代码。
- **Reviewer 同步前台**: codex 跑 ~30-60s,`start_review.py` 前台运行(用户能立即看到错误),review 落盘后下次 SessionStart 才被注入。
- **聊天/查询不受影响**: 不触发 Edit/Write 的 prompt(读代码、问问题)完全不被 hook 拦。
- **disabled list 是 cwd 维度,不是全局**: 每个项目独立 on/off,互不影响。
