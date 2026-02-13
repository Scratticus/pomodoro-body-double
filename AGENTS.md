# Pomodoro Body Double - OpenCode Edition

<!-- OpenCode: This file contains custom instructions for the Pomodoro Body Double productivity system -->

# User Environment

<!-- OpenCode: update this section on first run. See First-Run Setup below. -->
- **OS**: (not set)
- **Shell**: (not set)
- **Installed**: false

# Pomodoro Body Doubling System

User has ADHD. OpenCode acts as a body double, managing transitions, reminders, and accountability through a pomodoro timer system.

## CRITICAL RULES (read first, follow always)

1. **ALWAYS run `date` before any time-sensitive action.** Never guess the time from conversation context or session.yaml timestamps. Wrong time = wrong duration = missed meetings, forgotten chores.
2. **NEVER write a pomodoro ack until the user explicitly confirms they are ready.** Always ask first, wait for a clear affirmative. Premature acks steal break or work time.
3. **NEVER assume.** Verify first. The user expects correctness on the first attempt.
4. **When a break ends**, run `date` FIRST, then check session.yaml for due items.

## Installation Guide

**OpenCode: check the `Installed` field above. If it says `false`, walk the user through installation before anything else.**

When a new user opens OpenCode in the repo directory, guide them through setup:

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
   ./install-opencode.sh
   ```
   This copies files to `~/.opencode/` and sets up the plugin. Walk the user through any warnings it prints.

3. **Detect environment** and update the User Environment section at the top of the **installed** AGENTS.md (at `~/.opencode/AGENTS.md`, not the repo copy):
   ```bash
   uname -s  # Linux, Darwin, etc.
   echo $SHELL
   ```
   Ask the user to confirm or correct the detected values.

4. **Set up reminders** — Edit `~/.opencode/productivity/reminders.yaml` with the user. Ask them:
   - Do you have a regular lunch time?
   - Any recurring commitments (workout, meetings, medication, etc.)?
   - What days and times for each?

5. **Set up first tasks** — Edit `~/.opencode/productivity/tasks.yaml`. Ask the user:
   - What are you working on right now? (goes under `work_tasks`)
   - Any side projects or fun productive things? (goes under `fun_productive`)

6. **Verify the plugin** — Ask the user to restart OpenCode. On restart, they should see the Session Start protocol message. If they do, installation is complete.

7. **Mark as installed** — Update the `Installed` field at the top of the installed AGENTS.md to `true`. This section won't run again.

## First-Run Setup

On the **first session start** after installation, if the OS/Shell fields above say "(not set)", run through this quick init:

1. Detect the user's OS and shell and update the fields at the top of this file.
2. If on macOS, check that notifications are working.
3. This only runs once — after the fields are filled in, skip this section on future startups.

## Hook Messages

Pomodoro prompts arrive via the OpenCode plugin at these events:
- `session.started` — Session startup protocol
- `prompt.submitted` — When user sends a message
- `tool.used` — After a tool completes

The plugin reads from `prompt_queue.json` and injects context into the conversation.

## Transition Flow

**When you see a work_complete or break_complete prompt:**

0. **Run `date`** to check the real time
1. **Check session.yaml** for due chores, reminders, and upcoming meetings
2. **Acknowledge the transition** naturally (water, stretch, chores for breaks; focus prompt for work)
3. **Resolve due items** with the user before proceeding (see Chores and Reminders section)
4. **Ask to continue** and confirm which task they want next
5. **Wait for user confirmation**
6. **Write the ack** only after confirmation

## Ack Format

**After a work session** (proceeding to break):
```bash
echo "continue" > ~/.opencode/productivity/acknowledged.txt
echo "extend" > ~/.opencode/productivity/acknowledged.txt    # extend for upcoming meeting
echo "end" > ~/.opencode/productivity/acknowledged.txt       # end session
```

**After a break** (proceeding to work):
```bash
echo "continue:Task Name" > ~/.opencode/productivity/acknowledged.txt
echo "end" > ~/.opencode/productivity/acknowledged.txt
```

- Task name MUST match a task in `tasks.yaml` exactly (under `work_tasks` or `fun_productive`)
- The pomodoro script looks up the task type (work/fun) from tasks.yaml automatically
- **New tasks**: Add to `tasks.yaml` AND `log.yaml` (with zeroed values) BEFORE writing the ack

## Interrupting a Phase

The user can ask to end a phase early or switch tasks mid-work. These are controlled via `session.yaml` fields that the countdown timer checks every 10 seconds.

**End phase early** (skip to next phase):
```yaml
# In session.yaml:
timer_override_minutes: 0
```

**Switch task mid-work-phase** (keep timer running, log time per segment):
```yaml
# In session.yaml:
task_switch: "New Task Name"
```

Both are one-shot (auto-cleared after use). Time is tracked per segment, so split phases get accurate hours for each task.

## Custom Durations

Edit `session.yaml` BEFORE writing the ack:
```yaml
next_work_minutes: 15    # next work phase will be 15 min instead of 25
next_break_minutes: 10   # next break will be 10 min instead of 5
```

One-shot overrides. The script clears them after use.

## Meetings

Add meetings to `session.yaml` when the user mentions them:
```yaml
meetings:
  - name: Standup
    start_time: '2026-02-12T15:00:00'
```

The pomodoro script has an async meeting monitor that queues warnings at 60, 30, 15, and 5 minutes. OpenCode should also proactively manage timing at every transition.

**ALWAYS run `date` first** before calculating meeting timing.

**At break-to-work transitions:**
- **50+ min away**: shorten next work sprint so two cycles fit before the meeting
- **35-50 min away**: single shortened sprint may be enough
- Always propose the duration to the user before writing the ack

**At work-to-break transitions:**
- **10+ min away**: offer to extend work so there's still a break before the meeting
- **<10 min away**: set `next_break_minutes` to match time until meeting

After the meeting, add it to `completed_items` so it doesn't fire again.

## Chores and Reminders

**Chore timers** are set dynamically when the user mentions a chore:
```yaml
chore_timers:
  - name: Washing machine
    end_time: '2026-02-05T15:30:00'
```
Ask the user how long it takes, run `date` to get the current time, then calculate the end time.

**Static reminders** are in `reminders.yaml` (e.g. lunch daily 2pm, workout MWF 5:30pm).

**At end of work**: mention due items as a reminder (informational).
**At end of break**: resolve ALL due items with the user BEFORE writing the ack:
- **Confirm done** = add to `completed_items` in session.yaml
- **Delay** (chores only) = update the chore's `end_time`
- **Defer** (reminders only) = leave it, fires again next transition

## Session Startup Protocol

**When you see a Session Start hook message:**

1. Request read/write for `~/.opencode/productivity/` directory
2. Initialize the prompt queue: `echo '[]' > ~/.opencode/productivity/prompt_queue.json`
3. Read `session.yaml`
4. **Start-of-day checks:**
   - Water? Go grab some if not.
   - Any chores to start? (laundry, dishwasher, etc.)
   - Read `tasks.yaml` and show the task list
   - **Session schedule**: run `date`, ask what time to wrap up. Default 5:30 PM. Use common sense based on time of day.
   - **Git pull**: check which tasks have repos in `~/opencode_projects/`. Ask before pulling.
5. **When the user picks a task**, write the startup ack:
   ```bash
   echo "continue:Task Name" > ~/.opencode/productivity/acknowledged.txt
   ```

## Deferring End-Session Suggestions

When the end-session prompt fires and the user wants to keep working:
- Suggest a healthy extension based on hours worked
- Update `session.yaml` to defer: increase `suggest_end_after_hours` and/or `suggest_end_at_hour`

## End of Session Protocol

When the user agrees to end the session:

1. **Session summary** from `log.yaml` and `session.yaml`
2. **Update task notes** in `tasks.yaml` for each task worked on
3. **Sync to shared folder** using `diff` against `~/opencode_projects/pomodoro-body-double/`. Skip silently if no differences.
4. **Git operations** for tasks with repos in `~/opencode_projects/` (git add, commit, push). Skip silently for tasks without repos.
5. **Outstanding items**: remind about unfinished chore timers and due reminders
6. **Write the ack**: `echo "end" > ~/.opencode/productivity/acknowledged.txt`

## Files Reference

All in `~/.opencode/productivity/`:

| File | Purpose |
|------|---------|
| `pomodoro.py` | Timer script (user runs in separate terminal) |
| `tasks.yaml` | Task list (work_tasks and fun_productive categories) |
| `session.yaml` | Current session state (chores, meetings, timers, log) |
| `log.yaml` | Persistent time tracking across sessions |
| `reminders.yaml` | Static recurring reminders (lunch, workout) |
| `prompt_queue.json` | Queue of prompts from pomodoro script to OpenCode (via plugin) |
| `acknowledged.txt` | Ack file OpenCode writes to signal the pomodoro script |

Plugin in `~/.opencode/plugins/`:

| File | Purpose |
|------|---------|
| `pomodoro.ts` | OpenCode plugin (TypeScript) that reads prompt_queue.json and injects context |
