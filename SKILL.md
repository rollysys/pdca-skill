---
name: pdca
description: 用 hook 强制 PDCA 工作流。无 active plan 就拦 Edit/Write 和 mutating Bash；即便 plan active,主线程也必须先完成至少一次 subagent 才能改代码或结束回合；plan done 前做完成度校验,然后用 claude 独立 review,提炼 lessons 在下次 SessionStart 注入。当用户说"启用 pdca"、"按 PDCA 干"、"开 plan-gate"时触发。
---

# pdca — Plan-gate + 独立 Check

## 设计

工作必经四步:
- **Plan**: 写 `.pdca/current_plan.md` (cwd 内), frontmatter `status: active` + SMART 五维 + `## 验收记录`
- **Do**: Edit/Write 和 mutating Bash 只有 active plan 才放行;而且主线程必须先完成至少一次 subagent 才能动代码
- **Check**: 用户敲 `/pdca-done` → mark plan done → 起一个 **claude 独立 reviewer** 对 session 做五维评(效率/成本/方法/经验/教训)
- **Action**: reviewer 输出落 `~/.pdca/reviews/<sid>_<plan_slug>.md`,**下次** SessionStart hook 只注入提炼后的 lessons

为什么 reviewer 用独立 claude 进程而不是当前 session 自审:被强迫的自审 = 屎(参见 youremember v1)。独立视角才有"判断该不该留"的余地。

## 文件

```
<project>/.claude/
├── settings.json               # 注册 hooks
├── commands/
│   ├── pdca-done.md            # /pdca-done — 触发独立 review
│   ├── pdca-on.md              # /pdca-on  — 启用 plan-gate
│   └── pdca-off.md             # /pdca-off — 关闭 plan-gate
└── skills/pdca/
    ├── SKILL.md                # 本文件
    ├── plan_template.md        # .pdca/current_plan.md 的模板
    ├── hooks/
    │   ├── pre_tool_use.py     # 拦 code mutation; active plan 下还要求已完成 subagent
    │   ├── session_start.py    # 写 session 指针 + 初始化 subagent state + 注 active-plan banner
    │   ├── stop.py             # active plan 但还没 subagent 时阻止主线程直接收工
    │   └── subagent_stop.py    # 记录当前 session 已完成过 subagent
    └── scripts/
        ├── install_to_project.py
        ├── start_review.py
        ├── review_prompt.md
        └── toggle.py
```

外部状态(全局):
- `~/.pdca/reviews/<encoded_cwd>__<slug>__<sid>.md` — 历史 review
- `~/.pdca/sessions/by_cwd/<encoded_cwd>.json` — 每个 cwd 的最新 session 指针
- `~/.pdca/sessions/by_session/<session_id>.json` — 当前 session 的精确指针(`/pdca-done` 读)
- `~/.pdca/subagents/by_session/<session_id>.json` — 当前 session 是否已有完成的 subagent
- `~/.pdca/disabled.json` — 临时禁用 PDCA 的 cwd 列表

## 启用方式

默认安装到**当前项目目录**。在目标项目里执行:

```bash
python3 /path/to/pdca-skill/scripts/install_to_project.py
```

它会把 `settings.json`、`commands/`、`skills/pdca/` 一次性写进 `<project>/.claude/`。
生成后的 hook 命令都使用项目内路径,例如:

```json
{"type": "command", "command": "python3 .claude/skills/pdca/hooks/pre_tool_use.py"}
```

参考实例:`examples/sandbox/.claude/settings.json` 和 `templates/project_settings.json`。

## 动态控制

- `/pdca-on` — 启用本 cwd 的 plan-gate(若需要可再开 active plan)
- `/pdca-off` — 暂时关闭本 cwd 的 plan-gate(临时改 / 紧急修补 / 聊天调试时用)
- `/pdca-done` — agent 在 plan 完成时**先问用户确认**,得到 yes 再 invoke,触发 claude review

底层 toggle:`python3 .claude/skills/pdca/scripts/toggle.py {on|off|status}`

注:动态 on/off 不修改 `.claude/settings.json`,只改 `~/.pdca/disabled.json`,所以 git 工作区不会被搅动。

## Active-plan banner (agent 行为约束)

当 plan 是 active 状态时,SessionStart hook 会向 agent 注入一段行为指令:
"主线程改代码前,先跑一次 subagent;工作完成时,**不要静悄悄结束**,先 ask 用户'要 /pdca-done 吗?',得到 y 再触发"。
这样把"主动 check 完成度"做成 agent 默认习惯,而不依赖用户每次想起来。

## 设计取舍

- **Bash 也纳入 gate,但只在 plan 未 active 时保守放行读/测类命令**: 这样能堵上 `echo hi > file` 这种绕过,又不至于把 `git status` / `rg` / `pytest` 一起封死。
- **主线程改代码前必须先完成 subagent**: 这是结构性 gate,不是 prompt 约定。主线程能读/搜/测/起 subagent,但不能先直接改。
- **主线程也不能在没 subagent 时直接 stop**: 否则 delegation 规则会被“读一圈然后结束”绕过。active plan + no subagent → `Stop` 直接拦。
- **写 plan 自身永远放行**: 否则 bootstrap 死锁。`.pdca/current_plan.md` 的 file_path 命中就直接 allow。
- **Plan 必须 status=active 才放行**: `draft` 表示用户还在打磨,`done` 表示已交付。两者都不该再动代码。
- **Reviewer 同步前台**: claude reviewer 跑 ~30-60s,`start_review.py` 前台运行(用户能立即看到错误),review 落盘后下次 SessionStart 才被注入。
- **聊天/查询不受影响**: 不触发 Edit/Write 的 prompt(读代码、问问题)完全不被 hook 拦。
- **disabled list 是 cwd 维度,不是全局**: 每个项目独立 on/off,互不影响。
