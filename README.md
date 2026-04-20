# pdca-skill

**Hook-enforced PDCA workflow for Claude Code.**

A Claude Code skill that uses the hook system to force the agent through the four phases of a **Plan-Do-Check-Action** cycle: write a SMART plan before touching code; finish the work under that plan; have an **independent reviewer** audit the session; fold the lessons back into memory.

Read-only discipline: the skill never modifies your global `~/.claude/settings.json`. You opt in per project.

## Why

LLM agents drift without structure. "Can you just…" requests balloon into off-scope changes; the agent forgets to test; post-hoc self-audit turns into back-patting. PDCA is a known good discipline for iterative work — this skill makes it **structural** instead of aspirational.

- **Plan-gate**: a `PreToolUse` hook denies `Edit` / `Write` / `MultiEdit` / `NotebookEdit` unless the current project has `.pdca/current_plan.md` with `status: active`. No plan → no code changes. Reading, grep, bash are unaffected.
- **Done confirmation**: when a plan is active, `SessionStart` injects a behavior rule telling the agent to **ask the user** "work done? `/pdca-done` ?" before silently ending the turn.
- **Independent reviewer**: `/pdca-done` runs an out-of-process **codex** reviewer against the session transcript under a five-dimension prompt (efficiency / cost / method / experience / lessons). Because the reviewer isn't the worker, it has the independence to say "no valuable lesson here" — the failure mode where a coerced self-review produces flattering noise is avoided.
- **Closed loop**: the next `SessionStart` in the same cwd injects the most recent review summaries into context, so the lesson actually lands in the next Plan.

## Install

```bash
git clone https://github.com/rollysys/pdca-skill ~/.claude/skills/pdca
```

That's it — Claude Code discovers any `SKILL.md` in `~/.claude/skills/<name>/` automatically. The skill itself is now installed.

### Enable in a project

**The skill does nothing until you enable it in a specific project.** Drop a `.claude/settings.json` at that project's root:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/skills/pdca/hooks/pre_tool_use.py"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/skills/pdca/hooks/session_start.py"
          }
        ]
      }
    ]
  }
}
```

See [`examples/sandbox/.claude/settings.json`](examples/sandbox/.claude/settings.json) for the canonical example.

### Try it without risk

There's a ready-made sandbox inside the repo:

```bash
cp -r ~/.claude/skills/pdca/examples/sandbox ~/pdca-sandbox
cd ~/pdca-sandbox
claude
```

The hooks only fire when Claude's cwd is inside that dir. Your global config isn't touched. See [`examples/sandbox/README.md`](examples/sandbox/README.md) for the four-scenario walkthrough.

## Commands

- `/pdca-on` — enable plan-gate in this cwd (cancels any prior `/pdca-off`)
- `/pdca-off` — disable plan-gate in this cwd (adds the path to `~/.pdca/disabled.json`)
- `/pdca-done` — mark the current plan done, fire a codex reviewer in the foreground, write the review to `~/.pdca/reviews/`

These are ordinary slash-command `.md` files. Copy them into `~/.claude/commands/` to make them global, or leave them in a project's `.claude/commands/` for per-project use.

## Plan file

`.pdca/current_plan.md` in the project root. Frontmatter + body:

```markdown
---
status: active          # draft | active | done
plan_slug: short-id
started_at: 2026-04-20T01:00:00Z
---

# Plan: <one-line goal>

## SMART
- S (Specific): ...
- M (Measurable): what command shows you're done?
- A (Achievable): ...
- R (Relevant): ...
- T (Time-bound): ...

## Steps
- [ ] step 1
- [ ] step 2
```

Copy [`plan_template.md`](plan_template.md) as a starting point. The plan-gate only checks `status`; everything else is for you.

## Reviewer

`/pdca-done` runs [`scripts/start_review.py`](scripts/start_review.py), which:

1. reads `.pdca/current_plan.md`
2. looks up the current Claude Code transcript via `~/.pdca/sessions/<encoded-cwd>.json` (written by the `SessionStart` hook on boot)
3. slims the transcript (drops tool-result bodies, keeps user/assistant text + `tool_use` headers)
4. calls `codex exec <prompt>` with the slim transcript on stdin
5. writes the review to `~/.pdca/reviews/<encoded-cwd>__<plan-slug>__<sid>.md`
6. sets plan `status: done`

Requires [`codex`](https://github.com/openai/codex) on `PATH`. The reviewer prompt is in [`scripts/review_prompt.md`](scripts/review_prompt.md) — five dimensions, a hard-line SELF-CHECK step, a one-line FINAL verdict. Runs foreground with a 300-second timeout by default.

## State on disk

```
~/.pdca/
├── sessions/<encoded-cwd>.json    # per-cwd current session pointer
├── reviews/<encoded-cwd>__<slug>__<sid>.md
└── disabled.json                  # list of cwds where plan-gate is off
```

Nothing else is written. `rm -rf ~/.pdca/` fully wipes state.

## Design choices

- **Only `Edit`/`Write` gated, not `Bash`**: `Bash` is too broad — gating it breaks `git status`, `ls`, test runners. The gate is on code mutation, not exploration.
- **Writing the plan itself always passes**: otherwise bootstrap deadlocks. `.pdca/current_plan.md` is whitelisted explicitly in the PreToolUse hook.
- **Reviewer is out-of-process**: a coerced self-review is low-value. A separate agent (codex here) can legitimately decide "nothing worth remembering" and the review remains credible.
- **Sync foreground reviewer**: 30-60s codex runs are acceptable; running in the background loses the error surface if codex fails.
- **Chat / questions unaffected**: no `Edit`/`Write` → no gate triggered. You can freely converse, grep, read, explore.

## License

MIT — see [`LICENSE`](LICENSE).
