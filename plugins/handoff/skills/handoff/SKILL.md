---
name: handoff
description: Use at a natural breaking point to write a handoff note so the session after /clear resumes exactly where this one stopped, in any repo, without the workspace plugin. Not for workspace projects, which use /workspace:handoff
argument-hint: "[focus for the next session]"
user-invocable: true
disable-model-invocation: true
allowed-tools: Bash, Read, Write, AskUserQuestion
---

# Hand Off a Session

Write a note that lets a fresh session pick up this work cold, then arm it
so the next `/clear` loads it automatically. The repo's CLAUDE.md already
loads in every session; the note carries only what CLAUDE.md does not:
this session's state, decisions, and next step.

## Steps

### Step 1: Locate the Note

Run via Bash:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/handoff.py" path
```

Parse the JSON:

- **`status: "error"`** — show `message` and stop.
- **`workspace_detected: true`** and a workspace project is loaded in this
  conversation — tell the user `/workspace:handoff` keeps their project docs
  in sync and ask (AskUserQuestion) whether to use it instead or continue
  here. Stop if they pick the workspace one.
- **`exists: true`** — a handoff is already armed for this directory. It is
  overwritten in Step 4; say so in the report.

Keep `path` for Step 4.

### Step 2: Capture the Git State

Run via Bash:

```bash
git branch --show-current; git status --short | head -30; git log --oneline -5; git log --oneline @{upstream}..HEAD 2>/dev/null
```

Skip this step outside a git repo. Uncommitted and unpushed work is the
detail the next session most often gets wrong, so record it exactly.

### Step 3: Compose the Note

Write from this conversation, not from re-reading files. If `$ARGUMENTS`
names a focus, make it the next task unless the conversation clearly
contradicts it; say so if it does.

Use exactly this structure, and keep it under 60 lines:

```markdown
# Handoff: <short task label>

**Goal:** <one or two sentences: what we are trying to achieve and why>

## State
- Branch `<branch>`; <uncommitted files / unpushed commits, or "clean">
- <what is done, one line each, the facts the next session would otherwise re-derive>

## Decisions
- <decision> — <why; include rejected alternatives worth not retrying>

## Dead ends
- <what was tried and failed, and the evidence>

## Next task
<the single next action, concrete enough to start without asking>

## Read first
- `<repo-relative path>` — <why it matters for the next task>

## Open questions
- <anything waiting on the user or an external answer>
```

Omit any section that would be empty, except **Goal**, **State** and
**Next task**. List under **Read first** only files the next task needs,
at most five; never CLAUDE.md, which loads by itself.

### Step 4: Write and Arm

Write the note to `path` from Step 1 with the Write tool. Writing it arms
it: the hook keys freshness off the file's modification time.

### Step 5: Offer Durable Learnings

If the session surfaced something every future session in this repo
should know (a build quirk, a convention, a misleading test), list it
for the user as a proposed CLAUDE.md addition. **Do not edit CLAUDE.md
yourself:** it is checked in and shared, and a handoff is personal and
temporary.

### Step 6: Report

Tell the user, filling in the values:

> Handoff armed for `<project_dir>`. Press `/clear` and the next session
> resumes at `<next task>`. It expires after `<ttl_minutes>` minutes and
> fires once. The note is at `<path>`; edit it before clearing if
> anything is off.

## Examples

```text
/handoff:handoff
/handoff:handoff rerun the failing e2e with the new fixture
```

To disarm without clearing:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/handoff.py" clear
```

## Notes

- **Read-write.** Writes one file under `~/.claude/handoffs/`. Never
  writes inside the repository, never edits CLAUDE.md, never commits.
- **Keyed by launch directory.** Each git worktree gets its own note. A
  note armed in one directory does not fire in another.
- **Only `/clear` consumes it.** Quitting and relaunching does not. After
  it fires, or expires, the note moves to `<key>.consumed.md` beside it,
  so it can still be pasted by hand.
