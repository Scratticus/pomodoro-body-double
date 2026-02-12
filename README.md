# Pomodoro Body Double

An ADHD-friendly productivity system that uses [Claude Code](https://github.com/anthropics/claude-code) as a body double with pomodoro timing.

> **Note**: This is a showcase/example of how one developer uses Claude Code for ADHD productivity support. It's not an out-of-the-box tool, you'll likely want to adapt it to your own workflow. The code and patterns here are meant to inspire your own implementation.

## The Problem

If you have ADHD, you already know. You can hyperfocus for eight hours and forget to eat, or you can stare at a screen for two hours and accomplish nothing. You forget the laundry in the machine. You miss meetings because you lost track of time. You know you should take breaks but you either skip them entirely or never come back from them.

Traditional pomodoro timers help with the timing, but they don't help with the hardest part. Having someone there to keep you accountable, remind you about the things you'll forget, and gently pull you back when you drift.

## What This Does

This system turns Claude Code into a body double that sits alongside you while you work. It manages your time, remembers things you'll forget, and keeps you moving without being annoying about it.

### Structured work/break cycles
25 minute work sessions, 5 minute breaks. The timer runs in a separate terminal with a visual countdown. When a phase ends, you get a desktop notification with sound, and Claude checks in at your next message. No interruptions mid-flow.

### Transition reminders that actually help
At the end of every work session, Claude reminds you to drink water, stand up, and stretch. Simple, but surprisingly effective when someone actually says it to you rather than a notification you dismiss.

### Chore and errand tracking
Tell Claude "I just put a wash on, 40 minutes" and it sets a timer. When the laundry is done, it reminds you at the next transition. No more laundry sitting in the machine for three hours because you forgot. Works for anything with a timer.

### Recurring reminders
Set up daily or weekly reminders in a simple YAML file. Lunch at 2pm every day. Workout at 5:30pm on Monday, Wednesday, Friday. Medication reminders. Whatever you need. They show up at transitions so they don't break your focus, but they don't get lost either.

### Meeting awareness
Add meetings to your session and the system monitors them. It warns you at 60, 30, 15, and 5 minutes out. At transitions near a meeting, Claude proactively adjusts timing so you get a proper break before the meeting starts rather than working right up to the last second and arriving flustered.

### Task tracking with time logging
Keep a list of tasks (work and fun/productive categories). Claude handles switching between them at each transition. Time is logged per task per session and across sessions, so you can see where your hours actually go.

### Mid-phase flexibility
Need to end a work session early? Switch tasks without stopping the timer? Custom duration for the next sprint because you've got a meeting in 20 minutes? All supported. The system adapts to your day rather than forcing you into rigid blocks.

### End-of-session wrap-up
When you're done for the day, Claude walks you through: session summary, updating task notes, git commits for any code you worked on, and a check for outstanding chores or reminders. Nothing falls through the cracks.

### Gentle session limits
Set a target end time or maximum hours. When you hit the threshold, Claude gently suggests wrapping up. You can defer it, but it keeps asking. Prevents the "I'll just do one more thing" that turns into three extra hours.

## How It Works

The system has three parts:

1. **`pomodoro.py`** - A timer state machine that runs work/break cycles. At each transition it queues a prompt and waits for acknowledgment.
2. **Hook script** - Claude Code hooks (`UserPromptSubmit` and `PostToolUse`) that inject queued prompts into your conversation. Uses JSON `hookSpecificOutput` format so prompts surface reliably during active work, not just when you type.
3. **`CLAUDE.md`** - Instructions that tell Claude how to handle transitions, manage tasks, resolve chore/reminder blockers, and interact with the ack file.

### The Interaction Loop

1. Timer completes a phase, queues a prompt to `prompt_queue.json`, sends a desktop notification
2. User messages Claude (about anything) or Claude uses a tool, the hook injects the prompt
3. Claude delivers the reminder and asks what task to work on next
4. User confirms, Claude writes `continue:Task Name` to `acknowledged.txt`
5. Timer picks up the ack, updates session state, starts next phase

### Task Categories

Tasks live in `tasks.yaml` under two categories:
- **`work_tasks`** - Main productive work
- **`fun_productive`** - Side projects, creative work, learning

Claude handles switching between tasks at each transition. Time is logged per task.

### Chores and Reminders

- **Chore timers**: Set dynamically during a session (e.g. "put a wash on, 40 minutes"). Claude adds them to `session.yaml` with an `end_time`. When due, they appear as reminders at transitions.
- **Static reminders**: Defined in `reminders.yaml` with day-of-week schedules (e.g. lunch daily at 2 PM, workout Mon/Wed/Fri at 5:30 PM).
- At the end of a **work session**, due items are mentioned informally (you're about to take a break anyway).
- At the end of a **break**, due items are **blockers**. Claude won't start the next work phase until each is resolved (done, delayed, or deferred).

### End-of-Session

When you wrap up, Claude runs through:
1. Session summary (tasks worked on, time per task)
2. Task notes update (to-dos, status)
3. Git operations (commit/push if desired)
4. Outstanding chore/reminder check

## Platform

Built and tested on **Linux** (Arch/CachyOS) with **Bash**. Should work on any Linux distro. macOS may need adjustments to the notification command (`notify-send` is Linux-specific, on macOS you'd swap it for `osascript` or `terminal-notifier`). Not tested on Windows/WSL.

## Requirements

- [Claude Code](https://github.com/anthropics/claude-code)
- Python 3 with PyYAML (`pip install pyyaml`)
- `notify-send` for desktop notifications:
  - Arch: `pacman -S libnotify`
  - Debian/Ubuntu: `apt install libnotify-bin`
  - Fedora: `dnf install libnotify`
  - macOS: not supported natively, see Platform note above

## Installation

### Prerequisites

Before installing, make sure you have:

1. **[Claude Code](https://github.com/anthropics/claude-code)** installed and working
2. **Python 3** with PyYAML:
   ```bash
   python3 --version          # check Python is installed
   pip install pyyaml         # install PyYAML if missing
   ```
3. **Desktop notifications** (optional but recommended):
   ```bash
   # Arch Linux
   sudo pacman -S libnotify

   # Debian/Ubuntu
   sudo apt install libnotify-bin

   # Fedora
   sudo dnf install libnotify

   # macOS: not natively supported, see Platform note above
   ```

### Quick Install

```bash
git clone https://github.com/YOUR_USER/pomodoro-body-double.git ~/pomodoro-body-double
cd ~/pomodoro-body-double
./install.sh
```

The installer will:
1. Copy the hook script to `~/.claude/hooks/`
2. Copy `pomodoro.py` to `~/.claude/productivity/`
3. Install `CLAUDE.md` to `~/.claude/` (or save as `CLAUDE.pomodoro.md` if one already exists)
4. Create data files (`session.yaml`, `log.yaml`, `tasks.yaml`, `reminders.yaml`) if they don't exist
5. Initialise the prompt queue (`prompt_queue.json`)
6. Configure the Claude Code hooks in `~/.claude/settings.json` (or print manual instructions if settings already exist)

### After Installation

1. **If you already had a `CLAUDE.md`**, the installer saved the pomodoro version as `~/.claude/CLAUDE.pomodoro.md`. You need to merge its contents into your existing `~/.claude/CLAUDE.md`. The easiest way is to open Claude Code and ask it to merge them for you.

2. **If you already had a `settings.json`**, see the Manual Hook Setup section below to add the hooks yourself.

3. **Restart Claude Code.** On startup, you should see a `SessionStart` hook message. Claude will greet you with the startup protocol and walk you through:
   - Setting up your first tasks
   - Configuring reminders (lunch, workout, medication, etc.)
   - Choosing a session schedule

4. **Start the timer** in a separate terminal:
   ```bash
   python3 ~/.claude/productivity/pomodoro.py
   ```

5. **Work normally in Claude Code.** The timer runs independently. When a phase ends, you'll get a desktop notification and Claude will check in the next time you interact with it.

### Manual Hook Setup

If you already have a `settings.json` and the installer couldn't configure hooks automatically, add the following to your `~/.claude/settings.json`. You need all three hooks:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "echo 'SESSION START: Run startup protocol - request read/write for ~/.claude/hooks/ directory, clear ~/.claude/productivity/prompt_queue.json, and echo to ~/.claude/productivity/acknowledged.txt to establish permissions.'"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/pomodoro-hook.sh",
            "timeout": 5
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/pomodoro-hook.sh",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

- **SessionStart** triggers Claude's startup protocol (hydration check, task selection, schedule planning)
- **UserPromptSubmit** injects pomodoro prompts when you send a message
- **PostToolUse** injects prompts while Claude is actively working (so you don't miss transitions during long tool operations)

### Manual Installation (without install.sh)

If you prefer to set things up yourself:

1. Create the directories:
   ```bash
   mkdir -p ~/.claude/hooks ~/.claude/productivity
   ```

2. Copy the files:
   ```bash
   cp pomodoro.py ~/.claude/productivity/
   cp hooks/pomodoro-hook.sh ~/.claude/hooks/
   chmod +x ~/.claude/hooks/pomodoro-hook.sh
   cp CLAUDE.md ~/.claude/CLAUDE.md  # or merge into existing
   cp reminders.yaml.example ~/.claude/productivity/reminders.yaml
   ```

3. Initialise data files:
   ```bash
   echo '[]' > ~/.claude/productivity/prompt_queue.json
   touch ~/.claude/productivity/acknowledged.txt
   ```

4. Add the hooks to `~/.claude/settings.json` (see Manual Hook Setup above)

5. Edit `~/.claude/productivity/reminders.yaml` with your personal reminders

6. Restart Claude Code and follow the startup protocol

## Usage

1. Start Claude Code. On first run it will greet you with the startup protocol and help set up tasks.
2. Pick a task and agree on a schedule.
3. Start the timer in a separate terminal:
   ```bash
   python3 ~/.claude/productivity/pomodoro.py
   ```
4. Work as normal. When a phase ends you'll hear a notification and Claude will check in at your next message.

### Customising Reminders

Edit `~/.claude/productivity/reminders.yaml`:

```yaml
static_reminders:
  - name: Lunch
    time: "14:00"
    days: daily

  - name: Workout
    time: "17:30"
    days: [mon, wed, fri]
```

### Customising Timers

Edit the constants at the top of `~/.claude/productivity/pomodoro.py`:

```python
WORK_MINUTES = 25
BREAK_MINUTES = 5
```

Or ask Claude to set a custom duration for the next phase (one-shot override via `session.yaml`).

## Files

### Repository
- `pomodoro.py` - The timer state machine with countdown display, async meeting monitor, and task switching
- `hooks/pomodoro-hook.sh` - Claude Code hook script (JSON hookSpecificOutput format)
- `CLAUDE.md` - Instructions for Claude (installed to `~/.claude/`)
- `reminders.yaml.example` - Example reminders configuration
- `install.sh` - Installation script
- `settings.json` - Example Claude Code hook configuration

### Data (created at `~/.claude/productivity/`)
- `tasks.yaml` - Task list with work/fun categories and per-task to-do lists
- `session.yaml` - Current session state (resets automatically between sessions)
- `log.yaml` - Persistent time tracking per project
- `reminders.yaml` - Recurring reminder schedule
- `prompt_queue.json` - Prompt queue for hook injection (transient)
- `acknowledged.txt` - Acknowledgment signal (transient)

## Why

For people with ADHD who oscillate between hyperfocused burnout and unproductive stress. The goal is sustainable, enjoyable productivity with gentle external structure and a sense of working alongside someone who remembers the things you forget.

## License

MIT
