# pdca sandbox — isolated testing

一个**独立的项目目录**,用来试 PDCA skill,**零污染全局配置**。

## 为什么安全

Claude Code 的 `.claude/settings.json` 是 **project-scoped**:放在某个项目根目录的 `.claude/settings.json` 里的 hook **只在 `claude` 启动时的 cwd 落在这个项目内时生效**。

- 你的全局 `~/.claude/settings.json` —— **一字不动**
- hooks 不会在别的项目里激活
- 想卸载:`cd .. && rm -rf <sandbox-dir>`,再无痕迹(除了 `~/.pdca/` 下的 reviews/缓存,你可以 `rm -rf ~/.pdca/` 一并清除)

## 前置

先把 pdca 安装到 sandbox 项目的 `.claude/`:

```bash
git clone https://github.com/rollysys/pdca-skill /tmp/pdca-skill
cp -r /tmp/pdca-skill/examples/sandbox ~/pdca-sandbox
python3 /tmp/pdca-skill/scripts/install_to_project.py --project-dir ~/pdca-sandbox
```

## 用法

```bash
# 进去启动 claude
cd ~/pdca-sandbox
claude
```

SessionStart hook 会在每次启动时跑一次(写 session pointer + 注 reviews)。PreToolUse hook 只在你 `cd` 进这个目录时触发。

## 四个验收场景

### A. 无 plan → Edit/Write / mutating Bash 被拦

对 Claude 说"创建 hello.txt 写 hi"或让它跑 `echo hi > hello.txt`,都会被 hook deny,返回 reason 引导你写 plan。

### B. plan active 但还没 subagent → 主线程改代码和直接收工都被拦

1. 先让 Claude 写 `.pdca/current_plan.md`
2. 把 frontmatter `status: draft` 改成 `status: active`
3. 此时如果直接让 Claude 改文件,会被 deny
4. 如果它试图直接结束当前回合,`Stop` 也会拦住,提示先完成至少一次 subagent

### C. plan active + 完成一次 subagent → Edit/Write / Bash 通过

1. 先让 Claude 写 `.pdca/current_plan.md`(plan 自身永远放行,bootstrap 不死锁)
2. 把 frontmatter `status: draft` 改成 `status: active`
3. 先让 Claude 起一个 subagent(如 Explore/Plan/custom)并等它完成
4. 在 `## 验收记录` 里预留要填的验证命令/结果
5. 再让 Claude 改其他文件或跑 mutating Bash,放行

### D. `/pdca-done` → 触发 claude review

```
/pdca-done
```

Claude 调 `python3 .claude/skills/pdca/scripts/start_review.py --session-id "$PDCA_SESSION_ID" --transcript-path "$PDCA_TRANSCRIPT_PATH"`,先校验 step 与 `## 验收记录`,再标 plan done,起 claude 五维 review,落到 `~/.pdca/reviews/-Users-<you>-pdca-sandbox__<slug>__<sid>.md`。

### E. 下次 SessionStart 注入 review

退出 Claude 再启动 `claude`,SessionStart hook 会把最近 review 里提炼出的 lessons 注入到新 session 的上下文。

## 离线单元测试(可选)

不启动 Claude,用 `test_hooks.py` 直接喂 canned hook input JSON 验证:

```bash
python3 test_hooks.py
# 期望: 14/14 passed
```

覆盖:plan-gate 五种状态 + subagent gating + Stop gating + Bash gating + SessionStart 注入/env 导出 + toggle on/off + active-plan banner。

## 文件

- `.claude/settings.json` — 隔离 hooks 配置(只在本 dir 生效)
- `.claude/commands/pdca-{done,on,off}.md` — slash command 定义,在本 dir 内可用
- `test_hooks.py` — 离线 hook 模拟测试

## 动态切换

进到 sandbox 之后:

```
/pdca-off    # 关闭本 cwd 的 plan-gate(加到 ~/.pdca/disabled.json)
/pdca-on     # 重新启用
/pdca-done   # plan 做完触发 review(agent 应当先问你 y/n 再调)
```
