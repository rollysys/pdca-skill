# pdca sandbox — isolated testing

一个**独立的项目目录**,用来试 PDCA skill,**零污染全局配置**。

## 为什么安全

Claude Code 的 `.claude/settings.json` 是 **project-scoped**:放在某个项目根目录的 `.claude/settings.json` 里的 hook **只在 `claude` 启动时的 cwd 落在这个项目内时生效**。

- 你的全局 `~/.claude/settings.json` —— **一字不动**
- hooks 不会在别的项目里激活
- 想卸载:`cd .. && rm -rf <sandbox-dir>`,再无痕迹(除了 `~/.pdca/` 下的 reviews/缓存,你可以 `rm -rf ~/.pdca/` 一并清除)

## 前置

先装 pdca skill 到默认路径 `~/.claude/skills/pdca/`:

```bash
git clone https://github.com/rollysys/pdca-skill ~/.claude/skills/pdca
```

sandbox 里的 `.claude/settings.json` 里 hook 命令用了 `~/.claude/skills/pdca/hooks/...`,bash 会展开 `~` 成你的 HOME,所以只要 skill 装在默认路径就能跑。

## 用法

```bash
# 1. copy sandbox 到一个你放得下的独立目录
cp -r ~/.claude/skills/pdca/examples/sandbox ~/pdca-sandbox

# 2. 进去启动 claude
cd ~/pdca-sandbox
claude
```

SessionStart hook 会在每次启动时跑一次(写 session pointer + 注 reviews)。PreToolUse hook 只在你 `cd` 进这个目录时触发。

## 四个验收场景

### A. 无 plan → Edit/Write 被拦

对 Claude 说"创建 hello.txt 写 hi",Claude 试 Write 时被 hook deny,返回 reason 引导你写 plan。

### B. plan active → Edit/Write 通过

1. 先让 Claude 写 `.pdca/current_plan.md`(plan 自身永远放行,bootstrap 不死锁)
2. 把 frontmatter `status: draft` 改成 `status: active`
3. 再让 Claude 改其他文件,放行

### C. `/pdca-done` → 触发 codex review

```
/pdca-done
```

Claude 调 `python3 ~/.claude/skills/pdca/scripts/start_review.py`,标 plan done,起 codex 五维 review,落到 `~/.pdca/reviews/-Users-<you>-pdca-sandbox__<slug>__<sid>.md`。

### D. 下次 SessionStart 注入 review

退出 Claude 再启动 `claude`,SessionStart hook 会把最近 5 条本 cwd 的 review 注入到新 session 的上下文。

## 离线单元测试(可选)

不启动 Claude,用 `test_hooks.py` 直接喂 canned hook input JSON 验证:

```bash
python3 test_hooks.py
# 期望: 14/14 passed
```

覆盖:plan-gate 五种状态 + SessionStart 注入 + toggle on/off + active-plan banner。

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
