# Pomodoro Body Double for OpenCode

An ADHD-friendly productivity system that uses OpenCode as a body double with pomodoro timing.

## Quick Start

```bash
# 1. Install dependencies
pip install pyyaml
# Linux desktop notifications:
#   Arch: sudo pacman -S libnotify
#   Debian/Ubuntu: sudo apt install libnotify-bin
#   Fedora: sudo dnf install libnotify

# 2. Install the system
./install-opencode.sh

# 3. Restart OpenCode to load the plugin

# 4. Start the timer in a separate terminal
python3 ~/.opencode/productivity/pomodoro.py
```

## How It Works

1. **Timer runs independently** (`~/.opencode/productivity/pomodoro.py`)
   - 25-minute work / 5-minute break cycles
   - Desktop notifications at phase transitions
   - Async meeting monitor (warnings at 60/30/15/5 min)

2. **OpenCode plugin** (`~/.opencode/plugins/pomodoro.ts`)
   - Hooks into `prompt.submitted` and `tool.used` events
   - Reads `prompt_queue.json` and injects context
   - Handles session startup protocol

3. **Custom instructions** (`AGENTS.md`)
   - Tells OpenCode how to manage transitions
   - Chore/reminder resolution
   - Task switching and time logging

## Files

| File | Purpose |
|------|---------|
| `pomodoro.py` | Timer state machine (auto-detects OpenCode vs Claude paths) |
| `.opencode/plugins/pomodoro.ts` | OpenCode plugin for prompt injection |
| `AGENTS.md` | Custom instructions for OpenCode |
| `opencode.json` | Project-level plugin configuration |
| `install-opencode.sh` | One-command installer |

## Data Files (created in `~/.opencode/productivity/`)

- `tasks.yaml` — Task list (work_tasks, fun_productive)
- `session.yaml` — Current session state (resets between sessions)
- `log.yaml` — Persistent time tracking per project
- `reminders.yaml` — Recurring reminders (lunch, workout, etc.)
- `prompt_queue.json` — Prompt queue (transient)
- `acknowledged.txt` — Ack signal (transient)

## Customization

### Edit reminders
```bash
~/.opencode/productivity/reminders.yaml
```

Example:
```yaml
static_reminders:
  - name: Lunch
    time: "14:00"
    days: daily
  - name: Workout
    time: "17:30"
    days: [mon, wed, fri]
```

### Edit task timers
Edit constants at the top of `~/.opencode/productivity/pomodoro.py`:
```python
WORK_MINUTES = 25
BREAK_MINUTES = 5
```

Or use one-shot overrides in `session.yaml`:
```yaml
next_work_minutes: 15
next_break_minutes: 10
```

## Troubleshooting

### Plugin not loading?
Make sure OpenCode can access the plugin directory:
```bash
cd ~/.opencode/plugins && npm install @opencode-ai/plugin
```

### No notifications?
Check that `notify-send` is installed and working:
```bash
notify-send "Test" "Hello"
```

On macOS, install terminal-notifier and edit `notify()` in pomodoro.py.

### Timer not detecting OpenCode?
The timer auto-detects based on:
1. `~/.opencode` directory existing
2. `OPENCODE_CLI` environment variable

You can force OpenCode mode by creating `~/.opencode` before running install.

## License

MIT

## Credits

Adapted from the original Pomodoro Body Double for Claude Code.
