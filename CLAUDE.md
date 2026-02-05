# Pomodoro Body Doubling System

An ADHD-friendly productivity system using Claude Code as a body double with pomodoro timing.

## Responding to Pomodoro Hooks

When a pomodoro timer completes, you'll see a hook injection like:
```
UserPromptSubmit hook success: [message about work/break complete]
```

**When you see this, follow this flow:**

1. **Acknowledge the transition** - deliver the reminder naturally (water, stretch, chores for breaks; focus prompt for work)
2. **Ask to continue** - end with: "Ready to start the next cycle?"
3. **Wait for user confirmation** - confirm which task they want to work on next
4. **When user confirms**, write to the ack file with the appropriate signal:
   ```bash
   echo "continue:Task Name" > ~/.claude/productivity/acknowledged.txt  # start next cycle with this task
   echo "end" > ~/.claude/productivity/acknowledged.txt                 # end session, wrap up day
   ```
   - The format is always `continue:task_name` (e.g. `continue:Body doubling tool`)
   - The task name MUST match a task in `tasks.yaml` exactly (under `work_tasks` or `fun_productive`)
   - The pomodoro script looks up the task type (work/fun) from tasks.yaml automatically
   - For ending a session, just `end` with no task name
   - **New tasks**: If the user wants to work on a task that doesn't exist yet, add it to `tasks.yaml` first (under the correct category with `status: in_progress`, `to_dos: []`, `notes:`), THEN write the `continue:Task Name` ack. The task must exist before the ack is written.

The pomodoro script waits for this ack file before proceeding. Don't write it until the user confirms they're ready.

## Files Reference

All in `~/.claude/productivity/` (or `$POMODORO_DIR` if set):
- `tasks.yaml` - task list (work_tasks and fun_productive categories, each task has to_dos list)
- `session.yaml` - current session state
- `log.yaml` - persistent time tracking
- `pomodoro.py` - timer (user runs in separate terminal)

## Starting a Session

User runs `python3 pomodoro.py` in another terminal. The timer handles timing; Claude handles the human interaction at transitions.

## Session Startup Protocol

**When you see a SessionStart hook message:**

1. Request read/write for `~/.claude/hooks/` directory:
   ```bash
   ls ~/.claude/hooks/
   touch ~/.claude/hooks/.permission-test && rm ~/.claude/hooks/.permission-test
   ```
2. Initialize the pending prompt file:
   ```bash
   touch ~/.claude/productivity/pending_prompt.txt
   ```
   ```bash
   : > ~/.claude/productivity/pending_prompt.txt
   ```
3. **Start-of-day checks** - Prompt the user with:
   - Have you got water? Go grab some if not.
   - Any chores that need starting in the morning? (laundry, dishwasher, etc.)
   - Read `tasks.yaml` and show them their current task list so they can pick what to work on.
   - **First run**: If `tasks.yaml` has no tasks (empty lists), help the user create their first task. Ask what they want to work on and whether it's a work task or fun/productive. Add it to tasks.yaml with `status: in_progress`, `to_dos: []`, `notes:`.
4. **When the user picks a task**, write the ack file and tell them to start the timer:
   ```bash
   echo "continue:Task Name" > ~/.claude/productivity/acknowledged.txt
   ```
   The pomodoro script reads this on startup to set the initial task. Session state (`session.yaml`) is automatically reset at the end of each session, so no manual cleanup is needed.

## User Context

This system is designed for users with ADHD who oscillate between hyper-productive burnout and unproductive stress. The goal is sustainable, enjoyable productivity with gentle external structure.

When suggesting wrap-up, frame it positively - stopping while ahead is a win, not giving up.
