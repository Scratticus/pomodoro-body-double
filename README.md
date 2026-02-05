# Pomodoro Body Double

An ADHD-friendly productivity system that uses [Claude Code](https://github.com/anthropics/claude-code) as a body double with pomodoro timing.

> **Note**: This is a showcase/example of how one developer uses Claude Code for ADHD productivity support. It's not an out-of-the-box tool - you'll likely want to adapt it to your own workflow. The code and patterns here are meant to inspire your own implementation.

## What It Does

- Runs a pomodoro timer with a visual countdown in a separate terminal
- At each work/break transition, injects a prompt into your Claude Code session via hooks
- Claude reminds you to take breaks, hydrate, stretch, and checks if you're ready to continue
- Tracks which task you're working on and logs time per project
- Desktop notifications (with sound) when phases complete
- You stay in control - the timer waits for your confirmation before proceeding
- Gently suggests wrapping up after extended sessions

## How It Works

The system has three parts:

1. **`pomodoro.py`** - A timer state machine that runs work/break cycles. At each transition it writes a prompt file and waits for acknowledgment.
2. **Hook script** - A Claude Code hook that injects the pending prompt when you next message Claude.
3. **`CLAUDE.md`** - Instructions that tell Claude how to handle transitions, manage tasks, and interact with the ack file.

The key interaction loop:
1. Timer completes a phase, writes prompt, sends desktop notification
2. User messages Claude, hook injects the prompt
3. Claude delivers the reminder and asks what task to work on next
4. User confirms, Claude writes `continue:Task Name` to the ack file
5. Timer picks up the ack, updates session, starts next phase

Tasks are tracked in `tasks.yaml` with categories (work/fun) and per-task to-do lists. Time is logged per project in `log.yaml`.

## Why

For people with ADHD who oscillate between hyper-productive burnout and unproductive stress. The goal is sustainable, enjoyable productivity with gentle external structure and a sense of working alongside someone.

## Requirements

- [Claude Code](https://github.com/anthropics/claude-code)
- Python 3 with PyYAML (`pip install pyyaml`)
- `notify-send` for desktop notifications (`libnotify` package)

## Installation

```bash
git clone <repo> ~/pomodoro-body-double
cd ~/pomodoro-body-double
./install.sh
```

The installer will:
1. Copy the hook script to `~/.claude/hooks/`
2. Create the data directory at `~/.claude/productivity/`
3. Initialize `session.yaml`, `log.yaml`, and `tasks.yaml`
4. Configure the Claude Code hook in settings

## Usage

1. Copy `CLAUDE.md` to your project or `~/.claude/` so Claude knows the system
2. Start Claude Code - on first run it will help you set up your tasks
3. Pick a task, then start the timer in a separate terminal:
   ```bash
   python3 pomodoro.py
   ```
4. Work as normal. When a phase ends you'll hear a notification and Claude will check in at your next message.

## Configuration

Set environment variables before running:

```bash
export POMODORO_WORK_MINUTES=25    # default: 25
export POMODORO_BREAK_MINUTES=5    # default: 5
export POMODORO_END_HOURS=4        # suggest wrap-up after this many hours
python3 pomodoro.py
```

## Files

- `pomodoro.py` - The timer state machine with countdown display
- `hooks/pomodoro-hook.sh` - Claude Code hook script
- `CLAUDE.md` - Instructions for Claude (copy to your project or `~/.claude/`)
- `install.sh` - Installation script

## Data Storage

Session data lives in `~/.claude/productivity/`:
- `tasks.yaml` - Task list with work/fun categories and per-task to-do lists
- `session.yaml` - Current session state (resets automatically between sessions)
- `log.yaml` - Persistent time tracking per project per day
- `pending_prompt.txt` - Prompt waiting to be injected (transient)
- `acknowledged.txt` - Acknowledgment signal (transient)

## License

MIT
