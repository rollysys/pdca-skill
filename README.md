# pdca-skill

**Hook-enforced PDCA workflow for Claude Code.**

A Claude Code skill that uses the hook system to force the agent through the four phases of a **Plan-Do-Check-Action** cycle: write a SMART plan before touching code; complete at least one subagent pass before mutating code in the main thread; finish the work under that plan; have an **independent reviewer** audit the session; fold the lessons back into memory.

Read-only discipline: the skill installs into a target project's `.claude/` directory. It does not need to touch your global `~/.claude/settings.json`.

## Why

LLM agents drift without structure. "Can you just…" requests balloon into off-scope changes; the agent forgets to test; post-hoc self-audit turns into back-patting. PDCA is a known good discipline for iterative work — this skill makes it **structural** instead of aspirational.

- **Plan-gate**: a `PreToolUse` hook denies `Edit` / `Write` / `MultiEdit` / `NotebookEdit`, and also blocks mutating `Bash`, unless the current project has `.pdca/current_plan.md` with `status: active`. No plan → no code changes. Read-only inspection and test commands still pass.
- **Subagent-gate**: even with an active plan, main-thread code mutation stays blocked until at least one subagent has completed in the current session. This is enforced by `SubagentStop` + `PreToolUse`, not just instructions in prompt text.
- **Stop-gate**: if a plan is active and the session still has no completed subagent, Claude is not allowed to silently stop the turn. `Stop` blocks the stop and forces delegation first.
- **Done confirmation**: when a plan is active, `SessionStart` injects a behavior rule telling the agent to **ask the user** "work done? `/pdca-done` ?" before silently ending the turn.
- **Independent reviewer**: `/pdca-done` runs an out-of-process **Claude** reviewer against the session transcript under a five-dimension prompt (efficiency / cost / method / experience / lessons). Because the reviewer isn't the worker, it has the independence to say "no valuable lesson here" — the failure mode where a coerced self-review produces flattering noise is avoided.
- **Closed loop**: the next `SessionStart` in the same cwd injects the most recent review summaries into context, so the lesson actually lands in the next Plan.

## Install

Default install target is the **current project**. Clone the repo anywhere, then run the installer from the project you want to protect:

```bash
git clone https://github.com/rollysys/pdca-skill /tmp/pdca-skill
cd /path/to/your/project
python3 /tmp/pdca-skill/scripts/install_to_project.py
```

This writes:

- `.claude/settings.json`
- `.claude/skills/pdca/`
- `.claude/commands/pdca-{done,on,off}.md`

The generated hook commands all use **project-local paths** like `.claude/skills/pdca/hooks/pre_tool_use.py`.

### Manual layout

If you prefer to copy files yourself, the target structure is:

```text
<project>/
├── .claude/
│   ├── settings.json
│   ├── commands/
│   │   ├── pdca-done.md
│   │   ├── pdca-on.md
│   │   └── pdca-off.md
│   └── skills/
│       └── pdca/
│           ├── SKILL.md
│           ├── hooks/
│           ├── scripts/
│           ├── commands/
│           └── plan_template.md
```

See [`templates/project_settings.json`](templates/project_settings.json) for the canonical hook config.

### Try it without risk

There's a ready-made sandbox inside the repo:

```bash
cp -r /tmp/pdca-skill/examples/sandbox ~/pdca-sandbox
python3 /tmp/pdca-skill/scripts/install_to_project.py --project-dir ~/pdca-sandbox
cd ~/pdca-sandbox
claude
```

The hooks only fire when Claude's cwd is inside that dir. Your global config isn't touched. See [`examples/sandbox/README.md`](examples/sandbox/README.md) for the four-scenario walkthrough.

## Commands

- `/pdca-on` — enable plan-gate in this cwd (cancels any prior `/pdca-off`)
- `/pdca-off` — disable plan-gate in this cwd (adds the path to `~/.pdca/disabled.json`)
- `/pdca-done` — mark the current plan done, fire a Claude reviewer in the foreground, write the review to `~/.pdca/reviews/`

These are ordinary slash-command `.md` files. The installer copies them into the target project's `.claude/commands/`.

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

Copy [`plan_template.md`](plan_template.md) as a starting point. Mutation is allowed only when the plan is `active` and at least one subagent has completed in the current session.

## Reviewer

`/pdca-done` runs [`scripts/start_review.py`](scripts/start_review.py), which:

1. reads `.pdca/current_plan.md`
2. reads the current session metadata exported by `SessionStart` and resolves the exact transcript for this session
3. slims the transcript (drops tool-result bodies, keeps user/assistant text + `tool_use` headers)
4. validates that the plan has no unchecked steps and has a filled `## 验收记录` section
5. calls `claude --print --bare` with the review prompt as system prompt and the slim transcript on stdin
6. writes the review to `~/.pdca/reviews/<encoded-cwd>__<plan-slug>__<sid>.md`
7. sets plan `status: done`

Requires `claude` on `PATH`. The reviewer prompt is in [`scripts/review_prompt.md`](scripts/review_prompt.md) — five dimensions, a hard-line SELF-CHECK step, a one-line FINAL verdict. Runs foreground with a 300-second timeout by default.

## State on disk

```
~/.pdca/
├── sessions/
│   ├── by_cwd/<encoded-cwd>.json      # latest session pointer for a cwd
│   └── by_session/<session-id>.json   # exact session pointer used by /pdca-done
├── subagents/by_session/<session-id>.json
├── reviews/<encoded-cwd>__<slug>__<sid>.md
└── disabled.json                      # list of cwds where plan-gate is off
```

Nothing else is written. `rm -rf ~/.pdca/` fully wipes state.

## Where Lessons Live

Raw review outputs are stored in `~/.pdca/reviews/<encoded-cwd>__<slug>__<sid>.md`.
`SessionStart` parses those review files, extracts `## MEMORY CANDIDATES` and the final verdict, deduplicates them, and injects the result back into the next session as `PDCA — carried lessons`.
There is no separate memory database today; the review markdown files are the source of truth.

## Design choices

- **`Bash` is gated conservatively before plan activation**: read-only inspection and common test commands pass, but mutating shell commands are denied until the plan is active. This closes the trivial `cat > file` bypass while keeping exploration usable.
- **Main-thread mutation requires a completed subagent**: the workflow now encodes the delegation rule structurally. You can still read, grep, test, and spawn subagents freely, but actual mutation in the main thread remains blocked until a subagent has finished in the current session.
- **Stopping also requires prior delegation**: with an active plan, the main thread cannot quietly stop before at least one subagent has completed. This prevents the agent from bypassing the delegation rule by ending early.
- **Writing the plan itself always passes**: otherwise bootstrap deadlocks. `.pdca/current_plan.md` is whitelisted explicitly in the PreToolUse hook.
- **Reviewer is out-of-process**: a coerced self-review is low-value. A separate Claude print-mode process can legitimately decide "nothing worth remembering" and the review remains credible.
- **Sync foreground reviewer**: 30-60s Claude review runs are acceptable; running in the background loses the error surface if the reviewer fails.
- **Chat / questions unaffected**: no `Edit`/`Write` → no gate triggered. You can freely converse, grep, read, explore.

## License

MIT — see [`LICENSE`](LICENSE).
