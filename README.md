# Pomodoro Body Double

An ADHD-friendly productivity system that uses [Claude Code](https://github.com/anthropics/claude-code) as a body double with pomodoro timing.

> **Note**: This is a showcase of how one developer uses Claude Code for ADHD productivity support. It is not a polished out-of-the-box tool. The code and patterns are meant to be adapted to your own workflow.

## The Problem

If you have ADHD, you already know. You can hyperfocus for eight hours and forget to eat, or stare at a screen for two hours and accomplish nothing. Traditional pomodoro timers help with the timing but not the hardest part: having someone there to keep you accountable, gently pull you back when you drift, and remember the things you have asked them to remind you about.

## What This Does

A Python timer runs in a separate terminal, cycling between work and break phases. At each transition Claude checks in and helps you decide what to do next.

- Work and break cycles with configurable durations (25 / 5 minutes by default)
- Chore timers and recurring reminders that surface at transitions
- Meeting awareness with advance warnings and timing adjustments
- Task tracking across work and fun categories with per-task time logging
- Mid-phase flexibility: end early, switch tasks, override durations
- End-of-session wrap-up with summary, notes, and git operations
- Gentle session limits, deferrable when you want to keep going

Multiple reminders, chores, and meeting warnings can fire at the same transition. Claude prioritises them, treating some as blockers that need resolving before the next work phase and others as passive mentions.

## Platform

Built and tested on **Linux** (Arch / CachyOS). Should work on any Linux distro with `notify-send`. macOS would need a swap to `osascript` or `terminal-notifier`. Windows is not currently tested.

## Requirements

- [Claude Code](https://github.com/anthropics/claude-code) — required
- Python 3.11+ with PyYAML
- `notify-send` (libnotify) for desktop notifications
- Git (only if you want end-of-session git operations)

Install dependencies (Arch example):
```bash
sudo pacman -S python python-pyyaml libnotify
```

Debian / Ubuntu:
```bash
sudo apt install python3 python3-yaml libnotify-bin
```

## Architecture

Three top-level concerns, three locations.

| Folder | Role | Tracked? |
|---|---|---|
| `<repo>/` | Code, install templates, examples — the impersonal shareable repo | yes |
| `~/.claude/productivity/` | Runtime data: yaml state, prompt queue, ack file | no (private) |
| `~/.claude/hooks/` | Hook scripts that wire pomodoro into Claude Code | no (private) |

The code itself is split between a pomodoro core and per-agent adapters:

```
pomodoro-open/
├── pomodoro_core.py    all timer / state / ack logic, agent-agnostic
├── adapter_claude.py   formats prompts for Claude Code's hook system
├── adapter_opencode.py contract-conformant stub for OpenCode (plugin TODO)
├── ARCHITECTURE.md     core/adapter contract, ack vocab, hook event mapping
└── CHANGELOG.md        notable bug fixes and behaviour changes
```

The launcher (`pomodoro.py`) is a thin wrapper that resolves `pomodoro-open/` next to itself and runs the Claude adapter against `~/.claude/productivity/` by default.

## Installation

### Quick install

```bash
git clone https://github.com/Scratticus/pomodoro-body-double.git
cd pomodoro-body-double
./install.sh
```

The installer copies the launcher and `pomodoro-open/` into `~/.claude/productivity/`, drops the hook script into `~/.claude/hooks/`, and configures hooks in `~/.claude/settings.json` (or warns if you already have one). Data files (`session.yaml`, `tasks.yaml`, `log.yaml`, `chore_timers.yaml`, `reminders.yaml`) are created from defaults only if they do not exist — your data is never overwritten.

### CLAUDE.md handling

If `~/.claude/CLAUDE.md` already exists, the installer pauses and asks how to handle it.

1. **Install package to an alternate directory** (default). Copies the package — including a reference `CLAUDE.md` — into a directory you choose. Nothing in `~/.claude/` is touched. Use this to inspect the package and merge content from the bundled `CLAUDE.md` into your existing one. Re-run the installer with option 2 when you are ready to activate.
2. **Overwrite `~/.claude/CLAUDE.md`** and proceed with a normal install.

If no `~/.claude/CLAUDE.md` exists, the installer just drops the file in.

### After installation

1. Restart Claude Code so the hooks load.
2. Start the timer in a separate terminal:
   ```bash
   python3 ~/.claude/productivity/pomodoro.py
   ```
3. Send any message (e.g. `hello`). The `SessionStart` hook reports whether pomodoro is running; the queued startup prompt then surfaces on your first message and Claude runs the start-of-day routine (hydration, chores, meetings, task selection).
4. Work normally. Each phase ends with a desktop notification and a queued prompt that Claude picks up on your next message.

If you skip step 2, the SessionStart hook will tell Claude that pomodoro is not running and offer to start it for you.

### Manual install (without `install.sh`)

```bash
mkdir -p ~/.claude/hooks ~/.claude/productivity
cp pomodoro.py ~/.claude/productivity/
cp -r pomodoro-open ~/.claude/productivity/
cp hooks/pomodoro-hook.sh hooks/session-start.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/pomodoro-hook.sh ~/.claude/hooks/session-start.sh
cp CLAUDE.md ~/.claude/CLAUDE.md  # or merge into your existing file
cp chore_timers.yaml.example ~/.claude/productivity/chore_timers.yaml
cp reminders.yaml.example ~/.claude/productivity/reminders.yaml
echo '[]' > ~/.claude/productivity/prompt_queue.json
touch ~/.claude/productivity/acknowledged.txt
```

Then add the hook configuration from `settings.json` to your `~/.claude/settings.json`.

## Usage

### Ack vocabulary

Claude writes one of the following to `~/.claude/productivity/acknowledged.txt` to drive the timer:

| Token | Meaning |
|---|---|
| `work:Task Name` | Start work on a task. Must match a name in `tasks.yaml` exactly. Also used to switch tasks mid-phase. |
| `break` | Start a break (after `suggest_break`). |
| `extend` | Keep working — adds 10 minutes by default, or `session.extend_minutes` if set. |
| `end` | End the session. |

### Mid-phase controls (Claude edits `session.yaml`)

```yaml
timer_override_minutes: 0      # end the current phase immediately
task_switch: "New Task"        # switch task without ending the timer
next_work_minutes: N           # one-shot custom work duration
next_break_minutes: N          # one-shot custom break duration
extend_minutes: N              # custom extension on the next 'extend' ack
```

### Customising reminders

Edit `~/.claude/productivity/reminders.yaml`:

```yaml
static_reminders:
  - name: Lunch
    time: "13:00"
    days: daily
  - name: Workout
    time: "17:30"
    days: [mon, wed, fri]
```

`id` is auto-assigned on first load. `skip_if_sick` and `end_date` fields are also recognised.

### Customising default durations

Edit the constants in `pomodoro-open/pomodoro_core.py` (`create_config`):

```python
'WORK_MINUTES': 25,
'BREAK_MINUTES': 5,
'EXTEND_MINUTES': 10,
```

### Backups before testing changes

If you want to pull a PR or experiment with the code, snapshot your live data first:

```bash
scripts/backup-data.sh
```

This writes a timestamped copy of `~/.claude/productivity/*.yaml` to `~/.claude/productivity-backups/<timestamp>/`. Restore is `cp` from that folder.

### Ending a session

Claude runs the end-of-session protocol when you confirm. Summary of hours per task, task notes / to-do updates, optional git commit and push for repos you worked on, and a final outstanding-items check.

## How it works

### The interaction loop

1. `pomodoro.py` starts in its own terminal. On startup it queues a `session_start` prompt.
2. Claude Code's `SessionStart` hook surfaces the prompt the next time you send a message. Claude runs the start-of-day routine and writes `work:Task Name` to `acknowledged.txt`.
3. Pomodoro reads the ack, starts the work phase, and counts down silently.
4. At phase end, pomodoro queues `suggest_break` (or `suggest_work`) and sends a desktop notification.
5. The next `UserPromptSubmit` or `PostToolUse` hook surfaces the queued prompt. Claude asks how to proceed.
6. You confirm, Claude writes the ack, the next phase begins.

If the timer expires without an ack, pomodoro auto-extends by `EXTEND_MINUTES` and re-queues the suggestion. Notifications keep firing.

### Multiple items at a transition

Chores, reminders, and meeting warnings can all fire at the same boundary. Claude treats them as a list. At work end they are mentioned passively. At break end they are blockers — each must be resolved (done, delayed, or deferred) before the next work phase begins.

### Time tracking

Time is measured ack-to-ack, not by raw timer countdown. When Claude writes a `work:Task` ack, the clock starts on that task. When the next ack lands, the interval is logged. This means tracked time reflects confirmed work, not just elapsed clock time. `session.yaml` has the running daily total per task; `log.yaml` accumulates across sessions.

### Adapters

`pomodoro_core.py` knows nothing about Claude Code. All agent-specific behaviour (hook event mapping, placeholder substitution, prompt formatting) lives in an adapter. Adding support for another agent means writing a new `adapter_<agent>.py` that conforms to the contract documented in `pomodoro-open/ARCHITECTURE.md`.

## Files

### Repository

- `pomodoro.py` — from-clone launcher (also installed to `~/.claude/productivity/`)
- `pomodoro-open/` — core logic and adapters
- `hooks/pomodoro-hook.sh` — queue-driven hook for `UserPromptSubmit` / `PostToolUse`
- `hooks/session-start.sh` — `SessionStart` hook; reports whether pomodoro is running
- `CLAUDE.md` — install template for `~/.claude/CLAUDE.md`
- `pyproject.toml` / `uv.lock` — dependency declarations
- `chore_timers.yaml.example`, `reminders.yaml.example` — config templates
- `settings.json` — example Claude Code hook configuration
- `install.sh` — installer
- `scripts/backup-data.sh` — yaml snapshot helper
- `CREDITS.md` — open-source dependency tracking
- `LICENSE` — GPL-3.0

### Runtime data (`~/.claude/productivity/`)

- `pomodoro.py`, `pomodoro-open/` — installed copy of the launcher and core
- `tasks.yaml` — your task list with work / fun categories
- `session.yaml` — current session state (resets at session start)
- `chore_timers.yaml` — active chore countdowns
- `log.yaml` — cross-session per-project totals
- `reminders.yaml` — recurring reminder schedule
- `prompt_queue.json` — hook-delivery queue (transient)
- `acknowledged.txt` — ack signal (transient)

## Roadmap

No dates, just things in progress or planned:

- Cross-platform installer — Linux / macOS / Windows
- Calendar integration to pull meetings automatically
- Priority tracking to surface tasks that have not been worked on enough

## Why

For people with ADHD who oscillate between hyperfocused burnout and unproductive stress. The goal is sustainable, enjoyable productivity with gentle external structure and the sense of working alongside someone who remembers what you have asked them to.

## License

GPL-3.0. See [LICENSE](LICENSE) for details.
