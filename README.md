# Pomodoro Body Double

An ADHD-friendly productivity system that uses [Claude Code](https://github.com/anthropics/claude-code) as a body double with pomodoro timing.

> **Note**: This is a showcase/example of how one developer uses Claude Code for ADHD productivity support. It's not an out-of-the-box tool, you'll likely want to adapt it to your own workflow. The code and patterns here are meant to inspire your own implementation.

## The Problem

If you have ADHD, you already know. You can hyperfocus for eight hours and forget to eat, or you can stare at a screen for two hours and accomplish nothing. Traditional pomodoro timers help with the timing, but they don't help with the hardest part: having someone there to keep you accountable, gently pull you back when you drift, and remember the things you've asked them to remind you about.

## What This Does

This system turns Claude Code into a body double that sits alongside you while you work. A Python timer runs in a separate terminal, cycling between work and break phases. At each transition, Claude checks in and helps you decide what to do next.

- **Work/break cycles** with configurable durations (25/5 minutes by default, adjustable per phase)
- **Chore timers and recurring reminders** that surface at transitions so nothing gets forgotten
- **Meeting awareness** with advance warnings and automatic timing adjustments
- **Task tracking** across work and fun/productive categories with per-task time logging so you can see where your hours actually go
- **Mid-phase flexibility** to end early, switch tasks, or override the timer at any point
- **End-of-session wrap-up** with summary, task notes, git operations, and outstanding items
- **Gentle session limits** that suggest wrapping up, deferrable if you want to keep going

Multiple reminders, chores, and meeting warnings can fire at the same transition. Claude prioritises them, treating some as blockers that need resolving before the next work phase and others as passive mentions.

## Platform

The pomodoro system is built and tested on **Linux** (Arch/CachyOS). It should work on any Linux distro. macOS needs a swap of `notify-send` for `osascript` or `terminal-notifier`. Windows is not currently tested.

The voice interface (in development on `dev/voice-interface`) is being built cross-platform from the start — Linux, macOS, and Windows — with platform-specific code behind abstraction layers.

## Requirements

- [Claude Code](https://github.com/anthropics/claude-code) — required, no substitute
- [uv](https://docs.astral.sh/uv/) — Python package manager (installed automatically by `install.sh`)
- `notify-send` for desktop notifications:
  - Arch: `pacman -S libnotify`
  - Debian/Ubuntu: `apt install libnotify-bin`
  - Fedora: `dnf install libnotify`
  - macOS: not currently supported (voice interface will add `osascript` support)
- Git authenticated in your terminal (if you want end-of-session git operations)

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
git clone https://github.com/Scratticus/pomodoro-body-double.git
cd pomodoro-body-double
./install.sh
```

The installer will:
1. Install [uv](https://docs.astral.sh/uv/) to `~/.local/bin` if not already present
2. Run `uv sync` to create the Python virtual environment and install dependencies
3. Copy the hook script to `~/.claude/hooks/`
4. Copy `pomodoro.py` to `~/.claude/productivity/`
5. Install `CLAUDE.md` to `~/.claude/` (or save as `CLAUDE.pomodoro.md` if one already exists)
6. Create data files (`session.yaml`, `log.yaml`, `tasks.yaml`, `reminders.yaml`, `chore_timers.yaml`) if they don't exist
7. Initialise the prompt queue (`prompt_queue.json`)
8. Configure the Claude Code hooks in `~/.claude/settings.json` (or print manual instructions if settings already exist)

### After Installation

1. **If you already had a `CLAUDE.md`**, the installer saved the pomodoro version as `~/.claude/CLAUDE.pomodoro.md`. You need to merge its contents into your existing `~/.claude/CLAUDE.md`. The easiest way is to open Claude Code and ask it to merge them for you.

2. **If you already had a `settings.json`**, see the Manual Hook Setup section below to add the hooks yourself.

3. **Restart Claude Code.** The `SessionStart` hook fires automatically on launch, but Claude won't act on it until you send your first message. Just say hello or good morning and Claude will run the startup protocol, walking you through:
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

6. Restart Claude Code and send a message to trigger the startup protocol

## Usage

### Starting a Session

When you open Claude Code, a `SessionStart` hook fires and injects a startup message into the conversation. Send any message (even just "hello") to kick things off. Claude will ask you to grant file access to the hooks and productivity directories it needs, then walk you through the start of day routine:

- Hydration check
- Any chores to start (laundry, dishwasher, etc.) with timers
- Logging any meetings or one-off reminders for the day
- Reviewing your task list and picking what to work on

Once you've chosen a task, start the timer in a separate terminal:

```bash
python3 ~/.claude/productivity/pomodoro.py
```

### Working

Work as normal with Claude. The timer runs independently and doesn't interrupt you mid-flow. When a phase ends you'll get a desktop notification and Claude checks in the next time you interact with it.

At the end of a **work phase**, Claude mentions any due reminders or chores passively and suggests a break. At the end of a **break phase**, any due items become blockers that need resolving (confirmed done, delayed, or deferred) before the next work session starts. This keeps things honest without being disruptive during focused work.

If you finish a task early, just tell Claude. It will log the time for that task, switch you to whatever you want to work on next, and both tasks get accurate time tracking for the session.

### Customising Timers

Work and break durations default to 25 and 5 minutes. You can change the defaults by editing the constants at the top of `pomodoro.py`:

```python
WORK_MINUTES = 25
BREAK_MINUTES = 5
```

You can also ask Claude to set a custom duration for the next phase at any transition, or interrupt the current phase early. These are one-shot overrides managed through `session.yaml`.

### Customising Reminders

Edit `~/.claude/productivity/reminders.yaml`:

```yaml
static_reminders:
  - name: Lunch
    time: "14:00"
    days: daily

  - name: Workout
    time: "17:00"
    days: [mon, wed, fri]
```

### Ending a Session

When you're done for the day (or when the gentle session limit fires), Claude runs through an end of session protocol: session summary with time per task, updating task notes and to-dos, git commit and push for any repos you worked on, and a final check for outstanding chores or reminders.

## How It Works

### Architecture

The system has three parts:

1. **`pomodoro.py`** - A timer state machine running in a separate terminal. It manages work/break cycles, displays a visual countdown, monitors meeting times, and handles task switching. At each transition it writes a prompt to `prompt_queue.json` and waits for Claude to acknowledge by writing to `acknowledged.txt`.

2. **Hook script** - Claude Code supports hooks that run shell commands on specific events. This system uses two hook events to inject pomodoro prompts into the conversation:
   - **`UserPromptSubmit`** fires every time you send a message. The hook script checks `prompt_queue.json` and, if there's a queued prompt, injects it as additional context alongside your message using JSON `hookSpecificOutput` format.
   - **`PostToolUse`** fires every time Claude runs a tool (bash commands, file reads, etc.). This means prompts can surface even during long stretches of autonomous work where you haven't typed anything.

   A third hook, **`SessionStart`**, fires when Claude Code launches and injects the startup message that triggers the start of day routine.

3. **`CLAUDE.md`** - The instruction file that tells Claude how to behave. It defines the transition flow, ack format, task management, chore/reminder logic, meeting timing calculations, and the start/end of session protocols.

### The Interaction Loop

1. **Initialisation**: User opens Claude Code, sends a first message. The `SessionStart` hook injects the startup prompt. Claude requests file permissions, runs the start of day checks, and writes the first ack to start the timer.
2. **Work phase**: Timer counts down. User works with Claude normally. No interruptions.
3. **Transition**: Timer completes, queues a prompt to `prompt_queue.json`, sends a desktop notification. The next `UserPromptSubmit` or `PostToolUse` hook picks up the queued prompt and injects it into the conversation.
4. **Check-in**: Claude acknowledges the transition, mentions any due reminders or chores, and asks what to do next.
5. **Confirmation**: User confirms the next task (or finishes early, switches task, adjusts timing). Claude writes the ack to `acknowledged.txt`.
6. **Next phase**: Timer picks up the ack, updates session state, starts the next phase. Back to step 2.

### Multiple Items at a Transition

Several things can be due at the same transition: chore timers, recurring reminders, and meeting warnings. Claude handles them all as a list, prioritising by urgency. At the end of a work phase these are mentioned passively. At the end of a break they're blockers. Each item is resolved individually (done, delayed, deferred) before the next work phase begins.

### Task Switching and Early Completion

You can tell Claude you're done with a task early or want to switch to something else mid-phase. The timer keeps running but the session log records time per segment, so both tasks get accurate hours. You can also ask Claude to end the current phase immediately or set a custom duration for the next one.

### Time Tracking

Time is measured from ack to ack. When you confirm a task and Claude writes the acknowledgment, the timer starts. When the next transition fires and you confirm again, that interval is logged against the task you were working on. This means tracked time reflects actual confirmed work, not just timer countdowns.

`session.yaml` tracks hours and session counts per task for the current day. `log.yaml` accumulates totals across sessions, so you can see how much time you've put into each project over days and weeks. If you switch tasks mid-phase, the time is split proportionally and each task gets its own accurate segment. At the end of a session, Claude reads both files to give you a summary of what you worked on and for how long.

## Files

### Repository
- `pomodoro.py` - The timer state machine with countdown display, async meeting monitor, and task switching
- `hooks/pomodoro-hook.sh` - Claude Code hook script (JSON hookSpecificOutput format)
- `CLAUDE.md` - Instructions for Claude (installed to `~/.claude/`)
- `pyproject.toml` - Python dependencies managed by uv
- `uv.lock` - Pinned lockfile for reproducible installs
- `CREDITS.md` - Open source dependency tracking with license info
- `reminders.yaml.example` - Example reminders configuration
- `chore_timers.yaml.example` - Example chore timers configuration
- `install.sh` - Installation script
- `settings.json` - Example Claude Code hook configuration

### Voice Interface (in development — `dev/voice-interface` branch)
- `claude_voice/` - Python package for voice I/O, NiceGUI frontend, and Claude bridge
  - `config.py` - All paths and constants
  - `tts_output.py` - Piper TTS with streaming sentence chunking

### Data (created at `~/.claude/productivity/`)
- `tasks.yaml` - Task list with work/fun categories and per-task to-do lists
- `session.yaml` - Current session state (resets automatically between sessions)
- `chore_timers.yaml` - Persistent chore timers (survives session resets)
- `log.yaml` - Persistent time tracking per project
- `reminders.yaml` - Recurring reminder schedule
- `prompt_queue.json` - Prompt queue for hook injection (transient)
- `acknowledged.txt` - Acknowledgment signal (transient)

## Roadmap

No dates, just things in progress or planned:

- **Voice interface** (in progress on `dev/voice-interface`) — speak to Claude, hear responses via Piper TTS, NiceGUI window replaces the terminal with a glanceable timer and output display
- **Cross-platform installer** — `scripts/install.sh` (Linux/macOS) and `scripts/install.bat` (Windows) replacing the current single `install.sh`
- **Calendar integration** to pull meetings automatically instead of adding them manually
- **Priority tracking** to surface tasks that haven't had enough attention and nudge toward balanced progress

## Why

For people with ADHD who oscillate between hyperfocused burnout and unproductive stress. The goal is sustainable, enjoyable productivity with gentle external structure and a sense of working alongside someone who remembers what you've asked it to.

## License

GPL-3.0. See [LICENSE](LICENSE) for details.
