# User Environment

<!-- Claude: update this section on first run. See First-Run Setup below. -->
- **OS**: (not set)
- **Shell**: (not set)
- **Installed**: false

# Pomodoro Body Doubling System

User has ADHD. This system helps maintain sustainable productivity through pomodoro timing with Claude as a body double.

## Installation Guide

**Claude: check the `Installed` field above. If it says `false`, walk the user through installation before anything else.**

When a new user opens Claude Code in the repo directory, guide them through setup:

1. **Check dependencies**:
   ```bash
   python3 --version
   pip show pyyaml || pip3 show pyyaml
   which notify-send
   ```
   - If Python 3 is missing, help them install it for their OS
   - If PyYAML is missing: `pip install pyyaml` (or `pip3 install pyyaml`)
   - If `notify-send` is missing:
     - Linux (Arch): `sudo pacman -S libnotify`
     - Linux (Debian/Ubuntu): `sudo apt install libnotify-bin`
     - Linux (Fedora): `sudo dnf install libnotify`
     - macOS: `notify-send` is not available. Warn the user that notifications won't work out of the box. Suggest `brew install terminal-notifier` and offer to adapt the `notify()` function in `pomodoro.py` to use it.

2. **Run the installer**:
   ```bash
   ./install.sh
   ```
   This copies files to `~/.claude/` and sets up hooks. Walk the user through any warnings it prints (e.g. existing settings.json, existing CLAUDE.md).

3. **If the installer reported a CLAUDE.md conflict** (user already has `~/.claude/CLAUDE.md`):
   - The pomodoro CLAUDE.md was saved to `~/.claude/CLAUDE.pomodoro.md`
   - Help the user merge the pomodoro instructions into their existing CLAUDE.md
   - The entire content of this file (from "# User Environment" onwards) needs to be in their active CLAUDE.md

4. **Detect environment** and update the User Environment section at the top of the **installed** CLAUDE.md (at `~/.claude/CLAUDE.md`, not the repo copy):
   ```bash
   uname -s  # Linux, Darwin, etc.
   echo $SHELL
   ```
   Ask the user to confirm or correct the detected values.

5. **Set up reminders** — Edit `~/.claude/productivity/reminders.yaml` with the user. Ask them:
   - Do you have a regular lunch time?
   - Any recurring commitments (workout, meetings, medication, etc.)?
   - What days and times for each?

6. **Set up first tasks** — Edit `~/.claude/productivity/tasks.yaml`. Ask the user:
   - What are you working on right now? (goes under `work_tasks`)
   - Any side projects or fun productive things? (goes under `fun_productive`)

7. **Verify the hook** — Ask the user to restart Claude Code. On restart, they should see a SessionStart hook message. If they do, installation is complete.

8. **Mark as installed** — Update the `Installed` field at the top of the installed CLAUDE.md to `true`. This section won't run again.

## First-Run Setup

On the **first SessionStart** after installation, if the OS/Shell fields above say "(not set)", run through this quick init:

1. Detect the user's OS and shell and update the fields at the top of this file.
2. If on macOS, check that notifications are working.
3. This only runs once — after the fields are filled in, skip this section on future startups.

## Responding to Pomodoro Hooks

When a pomodoro timer completes, you'll see a hook injection like:
```
UserPromptSubmit hook success: [message about work/break complete]
```

**When you see this, follow this flow:**

1. **Acknowledge the transition** - deliver the reminder naturally (water, stretch, chores for breaks; focus prompt for work)
2. **Ask to continue** - end with: "Ready to start the next cycle?"
3. **Wait for user confirmation** - confirm which task they want to work on next
4. **When user confirms**, write to the ack file. The signal depends on which phase just ended:

   **After a work session** (proceeding to break):
   ```bash
   echo "continue" > ~/.claude/productivity/acknowledged.txt  # start break, keep current task
   echo "end" > ~/.claude/productivity/acknowledged.txt       # end session
   ```

   **After a break** (proceeding to work):
   ```bash
   echo "continue:Task Name" > ~/.claude/productivity/acknowledged.txt  # start work on this task
   echo "end" > ~/.claude/productivity/acknowledged.txt                 # end session
   ```
   - The task name MUST match a task in `tasks.yaml` exactly (under `work_tasks` or `fun_productive`)
   - The pomodoro script looks up the task type (work/fun) from tasks.yaml automatically
   - **New tasks**: If the user wants to work on a task that doesn't exist yet:
     1. Add it to `tasks.yaml` (under the correct category with `status: in_progress`, `to_dos: []`, `notes:`)
     2. Add it to `log.yaml` under `projects:` with zeroed values:
        ```yaml
        Task Name:
          total_hours: 0
          total_sessions: 0
        ```
     3. THEN write the `continue:Task Name` ack. Both files must have the task before the ack is written.

The pomodoro script waits for this ack file before proceeding. Don't write it until the user confirms they're ready.

## Files Reference

All in `~/.claude/productivity/`:
- `tasks.yaml` - task list (work_tasks and fun_productive categories)
- `session.yaml` - current session state
- `log.yaml` - persistent time tracking
- `reminders.yaml` - recurring reminders (lunch, workout, etc.)
- `pomodoro.py` - timer (user runs in separate terminal)

## Starting a Session

User runs `python3 ~/.claude/productivity/pomodoro.py` in another terminal. The timer handles timing; Claude handles the human interaction at transitions.

## Session Startup Protocol

**When you see a SessionStart hook message**, run these commands separately (for granular permission control):

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
3. Request read/write for `session.yaml`:
   ```bash
   cat ~/.claude/productivity/session.yaml
   ```
4. **Start-of-day checks** - Prompt the user with:
   - Have you got water? Go grab some if not.
   - Any chores that need starting in the morning? (laundry, dishwasher, etc.)
   - Read `tasks.yaml` and show them their current task list so they can pick what to work on.
   - **Session schedule**: Check the current time and ask the user what time they'd like to wrap up today. Use common sense - if it's already afternoon, a 9-hour session isn't realistic. Default to 5:30 PM (`suggest_end_at_hour: 17.5`) and 9 hours max (`suggest_end_after_hours: 9`) but let the user override. Edit `session.yaml` directly with the Edit tool to set these values.
   - **Git pull**: If the user has project repos, offer to `git pull` to get the latest. Ask before pulling - skip if the user declines or the repo doesn't have a remote.
5. **When the user picks a task**, write the ack file and tell them to start the timer:
   ```bash
   echo "continue:Task Name" > ~/.claude/productivity/acknowledged.txt
   ```
   The pomodoro script reads this on startup to set the initial task. Session state (`session.yaml`) is automatically reset at the end of each session, so no manual cleanup is needed.

## Deferring End-Session Suggestions

When the end-session prompt fires and the user wants to keep working:
- Suggest a healthy extension based on how long they've been going (e.g. 1-2 more hours if under 6h, just 1 more cycle if over 8h)
- Update `session.yaml` to defer: increase `suggest_end_after_hours` and/or `suggest_end_at_hour` to the agreed time
- The pomodoro script checks both thresholds at each work session end - whichever triggers first fires the suggestion

## Chores and Reminders

Chores and reminders use a unified flow. The pomodoro script checks both at each transition and injects due items into the prompt together.

**Chore timers** are set dynamically by Claude when the user mentions a chore (e.g. "just put a wash on"):
```yaml
chore_timers:
  - name: Washing machine
    end_time: '2026-02-05T15:30:00'
```
- Ask the user how long it takes and calculate the end time from now

**Static reminders** are defined in `reminders.yaml` (e.g. lunch at 2 PM daily, workout at 5:30 PM Mon/Wed/Fri).

**Flow at transitions:**
- **End of work session**: Mention due items as a reminder (informational — user is about to take a break)
- **End of break session**: The script writes a single prompt (break complete + any due items) and waits for one ack. If there are due items, Claude must resolve them with the user **before** writing the ack:
     - **Confirm done** → add item name to `completed_items` list in `session.yaml`
     - **Ask to delay** (chores only) → update the chore's `end_time` in `session.yaml`
     - **Decline/defer** (reminders only) → leave it, it will fire again at the next transition
  - Do NOT write the ack until all due items are resolved or acknowledged by the user.
- Completed items won't fire again for the rest of the session

## End of Session Protocol

When the user agrees to end the session, run through these steps before writing the `end` ack:

1. **Session summary** - Read `log.yaml` and `session.yaml`. Summarise what was worked on today, how many sessions per task, and total time.
2. **Update task notes** - For each task worked on today, ask the user if they want to update notes or to-dos in `tasks.yaml`. Edit the file with any updates.
3. **Git operations** - For each project worked on that has a git repo, ask the user then run:
   - `git add` and `git commit` for any changes
   - `git push` to remote
   - Or skip entirely if they decline
4. **Outstanding items** - Check for unfinished chores and reminders separately:
   - **Chore timers**: Check `session.yaml` for any `chore_timers` not in `completed_items`. These have specific `end_time` values — remind the user and suggest they set an alarm for the due time.
   - **Reminders**: Check `reminders.yaml` for any due today that aren't in `completed_items`. These are things the user still hasn't done — remind them before they step away.
5. **Write the ack** - Only after all wrap-up is done:
   ```bash
   echo "end" > ~/.claude/productivity/acknowledged.txt
   ```
