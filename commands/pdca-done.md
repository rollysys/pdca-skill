---
description: 触发 PDCA Check 阶段 - 校验 plan 完成度后,用 claude 独立审计当前 session
allowed-tools: Bash, Read
---

请触发 PDCA Check:

1. **先 Read** `.pdca/current_plan.md`,确认任务确实做完了。如果 SMART 的 M (Measurable) 标准没全部达到、step 还有未勾的、或 `## 验收记录` 还没补,**先告诉用户、等用户确认**再继续。
2. **不要自己改 plan 文件**。脚本会处理。
3. 调用 Bash:`python3 .claude/skills/pdca/scripts/start_review.py --session-id "$PDCA_SESSION_ID" --transcript-path "$PDCA_TRANSCRIPT_PATH"`
   - 这两个环境变量由 `SessionStart` hook 注入,用于绑定**当前** session,避免同 cwd 多窗口串审
   - 脚本会:校验 plan 完成度、过滤当前 session transcript、用 `claude --print --bare` 跑五维 review、写到 `~/.pdca/reviews/<encoded_cwd>__<slug>__<sid>.md`、标 plan done
   - 默认前台同步运行,timeout 300s
4. 把 review 文件路径报给用户,**不要自己读 review 内容**(太长且会污染当前 session 上下文,review 在下次 SessionStart 自动注入)。
5. 如果 claude 报错或不在 PATH,把 stderr 原样转给用户,**不要自己代跑**。
