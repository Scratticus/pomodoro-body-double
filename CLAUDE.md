# Pomodoro Body Double — CLAUDE.md

Copy or merge this file into `~/.claude/CLAUDE.md` to activate the body doubling behaviour in Claude Code.

---

# Pomodoro Body Doubling System

The user has ADHD. Claude acts as a body double with pomodoro timers, task tracking, and accountability.

## Critical Ack Rule

**Never write any ack at the point a hook fires.** The user may still be working. Always ask, wait for explicit confirmation, then write.

Exception: startup. Write the ack immediately when the user names their task — no second confirmation needed.

## Hook Messages

Prompts arrive as hook injections in two formats:
```
UserPromptSubmit hook additional context: [type] message
PostToolUse:Bash hook additional context: [type] message
```

Types include `work_complete`, `break_complete`, `meeting_warning`, `extend_reminder`, `error`.

**Each hook message includes the exact ack string to write and the file path.** Use the Write tool. Claude responds exactly as the hook message says. Do not add steps or assumptions beyond what the hook requests.

## Startup

1. Initialize permissions for `~/.claude/hooks/` and `~/.claude/productivity/`
2. Show task list (read `tasks.yaml`)
3. When the user names their task, write the ack immediately using Write tool:
   - File: `~/.claude/productivity/acknowledged.txt`
   - Content: `continue:Task Name` (must match a task in tasks.yaml exactly)

No second confirmation needed. Write the ack the moment the user names a task.

## Ack Format

Hook messages carry the exact ack string. For reference:

| Situation | Content to write |
|-----------|-----------------|
| After work (proceed to break) | `continue` |
| After work (more work) | `extend` |
| After break (start work) | `continue:Task Name` |
| End session | `end` |
| Startup | `continue:Task Name` |

File: `~/.claude/productivity/acknowledged.txt`. Always use Write tool, never Bash echo.

## Meetings

Add to `session.yaml` when the user mentions one. All three fields required:
```yaml
meetings:
  - name: Standup
    start_time: '17/03/2026 15:00'   # DD/MM/YYYY HH:MM
    duration_minutes: 30
    task: My Task Name               # must match a task name in tasks.yaml exactly
```

Python assigns `id` automatically — never write it manually. Timestamps everywhere are `DD/MM/YYYY HH:MM`.

After a meeting completes, add `meeting:N` to `completed_ids` in session.yaml.

## Chore and Reminder Delays

When resolving a due item at break end, Claude can delay it via the `extensions` dict in session.yaml:

```yaml
extensions:
  chore:2: {delay: 30}                   # 30 more minutes
  reminder:1: {delay: '17/03/2026 18:00'}  # absolute timestamp
```

The `id` (e.g. `chore:2`) comes from the prompt Python sends — echo it back exactly. Python processes it and converts `delay` to the internal snooze timestamp.

## New Tasks

Add to `tasks.yaml` (under `work_tasks` or `fun_productive`) AND `log.yaml` (zeroed values) BEFORE writing the ack.

## Immediate Cleanup Rule

When the user says a task, to-do, or job is done/rejected/irrelevant: remove it from `tasks.yaml` in this turn. Not at end of session.

## Session Control Fields (reference)

```yaml
timer_override_minutes: 0      # end phase early (checked every 10s)
task_switch: "Task Name"       # switch task mid-work-phase (logs time per segment)
extend_minutes: N              # add N minutes to a running phase
next_work_minutes: N           # custom duration for next work phase (one-shot)
next_break_minutes: N          # custom duration for next break phase (one-shot)
reminder_enabled: true/false   # toggle ack reminders on/off
reminder_interval_minutes: 5   # how often ack reminders fire (default 5)
```

When the user says "let's finish X before the break", estimate how long X will take and set `extend_minutes: N` in session.yaml. Do NOT write the break ack — starting any phase requires explicit user confirmation.

## End of Session — 4 Steps

When the user agrees to end:

1. **Session summary**: show hours per task from `log.yaml` and `session.yaml`
2. **Update tasks**: for each task worked, update notes AND remove resolved to-dos from `tasks.yaml`
3. **Git operations**: for each `has_git: true` task, confirm with user, then git add/commit/push
4. **Write end ack**: write `end` to `~/.claude/productivity/acknowledged.txt` using Write tool

## Files Reference

All in `~/.claude/productivity/`:

| File | Purpose |
|------|---------|
| `pomodoro.py` | Timer script (user runs in separate terminal) |
| `tasks.yaml` | Task list (`work_tasks` and `fun_productive` categories; `has_git` boolean per task) |
| `session.yaml` | Current session state (meetings, timers, log) |
| `chore_timers.yaml` | Persistent chore timers (survives session resets); write `duration_minutes: N` to add a new chore |
| `log.yaml` | Persistent time tracking across sessions |
| `reminders.yaml` | Static recurring reminders |
| `prompt_queue.json` | Queue of prompts from pomodoro script to Claude (via hooks) |
| `acknowledged.txt` | Ack file Claude writes to signal the pomodoro script |

Hooks in `~/.claude/hooks/`:

| File | Purpose |
|------|---------|
| `pomodoro-hook.sh` | Reads prompt_queue.json, outputs JSON hookSpecificOutput format |
