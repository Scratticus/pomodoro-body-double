# Pomodoro Body Double

An ADHD-friendly productivity system that uses [Claude Code](https://github.com/anthropics/claude-code) as a body double with pomodoro timing.

> **Note**: This is a showcase/example of how one developer uses Claude Code for ADHD productivity support. It's not an out-of-the-box tool - you'll likely want to adapt it to your own workflow. The code and patterns here are meant to inspire your own implementation.

## What It Does

- Runs a 25/5 pomodoro timer with a visual countdown in a separate terminal
- At each work/break transition, injects a prompt into your Claude Code session via hooks
- Claude reminds you to take breaks, hydrate, stretch, and handle chores
- Tracks which task you're working on and logs time per project
- Desktop notifications (with sound) when phases complete
- Chore timers and recurring reminders (e.g. lunch, workout) with blocker logic
- You stay in control - the timer waits for your confirmation before proceeding
- Gently suggests wrapping up after configurable hours or clock time

## How It Works

The system has three parts:

1. **`pomodoro.py`** - A timer state machine that runs work/break cycles. At each transition it writes a prompt file and waits for acknowledgment.
2. **Hook script** - A Claude Code `UserPromptSubmit` hook that injects the pending prompt when you next message Claude.
3. **`CLAUDE.md`** - Instructions that tell Claude how to handle transitions, manage tasks, resolve chore/reminder blockers, and interact with the ack file.

### The Interaction Loop

1. Timer completes a phase, writes a prompt to `pending_prompt.txt`, sends a desktop notification
2. User messages Claude (about anything), the hook injects the prompt
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
- At the end of a **break**, due items are **blockers** - Claude won't start the next work phase until each is resolved (done, delayed, or deferred).

### End-of-Session

When you wrap up, Claude runs through:
1. Session summary (tasks worked on, time per task)
2. Task notes update (to-dos, status)
3. Git operations (commit/push if desired)
4. Outstanding chore/reminder check

## Platform

Built and tested on **Linux** (Arch/CachyOS) with **Bash**. Should work on any Linux distro. macOS may need adjustments to the notification command (`notify-send` is Linux-specific — on macOS you'd swap it for `osascript` or `terminal-notifier`). Not tested on Windows/WSL.

## Requirements

- [Claude Code](https://github.com/anthropics/claude-code)
- Python 3 with PyYAML (`pip install pyyaml`)
- `notify-send` for desktop notifications:
  - Arch: `pacman -S libnotify`
  - Debian/Ubuntu: `apt install libnotify-bin`
  - Fedora: `dnf install libnotify`
  - macOS: not supported natively — see Platform note above

## Installation

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
5. Configure the Claude Code hooks in `~/.claude/settings.json` (or print manual instructions if settings already exist)

### Manual Hook Setup

If you already have a `settings.json`, add these hooks:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "echo 'SESSION START: Run startup protocol - request read/write for ~/.claude/hooks/ directory, clear ~/.claude/productivity/pending_prompt.txt, and echo to ~/.claude/productivity/acknowledged.txt to establish permissions.'"
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
    ]
  }
}
```

The `SessionStart` hook triggers Claude's startup protocol (hydration check, task selection, schedule planning). The `UserPromptSubmit` hook injects pomodoro prompts into your conversation.

## Usage

1. Start Claude Code - on first run it will greet you with the startup protocol and help set up tasks
2. Pick a task and agree on a schedule
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

## Files

### Repository
- `pomodoro.py` - The timer state machine with countdown display
- `hooks/pomodoro-hook.sh` - Claude Code hook script
- `CLAUDE.md` - Instructions for Claude (installed to `~/.claude/`)
- `reminders.yaml.example` - Example reminders configuration
- `install.sh` - Installation script

### Data (created at `~/.claude/productivity/`)
- `tasks.yaml` - Task list with work/fun categories and per-task to-do lists
- `session.yaml` - Current session state (resets automatically between sessions)
- `log.yaml` - Persistent time tracking per project
- `reminders.yaml` - Recurring reminder schedule
- `pending_prompt.txt` - Prompt waiting to be injected (transient)
- `acknowledged.txt` - Acknowledgment signal (transient)

## Why

For people with ADHD who oscillate between hyper-productive burnout and unproductive stress. The goal is sustainable, enjoyable productivity with gentle external structure and a sense of working alongside someone.

## License

MIT
