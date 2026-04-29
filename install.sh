#!/bin/bash
set -e

# === Pomodoro Body Double Installer ===
#
# Three-folder model:
#   - Code (this repo)            — single source for everything users install
#   - ~/.claude/productivity/     — runtime data (yaml, queue, ack), private to user
#   - ~/.claude/hooks/            — Claude Code hook scripts
#
# This installer copies code into the runtime locations so the package is
# self-contained after install (re-run to update). It will not overwrite an
# existing CLAUDE.md without explicit consent.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
HOOKS_DIR="$CLAUDE_DIR/hooks"
DATA_DIR="$CLAUDE_DIR/productivity"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"
CLAUDE_MD="$CLAUDE_DIR/CLAUDE.md"

echo "=== Pomodoro Body Double Installer ==="
echo

# --- CLAUDE.md decision ---
# If a CLAUDE.md already exists, ask the user how to handle it. Two options:
#   1. Install the whole package (including a reference CLAUDE.md) to an alternate
#      directory. Nothing in ~/.claude/ is touched. Use this if you want to
#      inspect the package and merge CLAUDE.md content into your existing one
#      at your leisure. Re-run with overwrite when ready.
#   2. Overwrite the existing CLAUDE.md and install normally.

ALT_DIR=""

if [ -f "$CLAUDE_MD" ]; then
    echo "An existing CLAUDE.md was found at $CLAUDE_MD."
    echo
    echo "  [1] Install package to an alternate directory (does not touch your"
    echo "      existing CLAUDE.md, hooks, or data). Use this to merge content"
    echo "      manually before activating."
    echo "  [2] Overwrite CLAUDE.md and install normally."
    echo
    read -r -p "Choose 1 or 2 (default 1): " CHOICE
    CHOICE="${CHOICE:-1}"

    case "$CHOICE" in
        1)
            read -r -p "Alternate install directory [$HOME/.claude/pomodoro-install]: " ALT_DIR
            ALT_DIR="${ALT_DIR:-$HOME/.claude/pomodoro-install}"
            echo
            echo "Installing reference copy to $ALT_DIR (no live files will be touched)..."
            mkdir -p "$ALT_DIR/pomodoro-open" "$ALT_DIR/hooks"
            cp "$SCRIPT_DIR/pomodoro.py" "$ALT_DIR/"
            cp -r "$SCRIPT_DIR/pomodoro-open/." "$ALT_DIR/pomodoro-open/"
            cp "$SCRIPT_DIR/hooks/pomodoro-hook.sh" "$ALT_DIR/hooks/"
            cp "$SCRIPT_DIR/hooks/session-start.sh" "$ALT_DIR/hooks/"
            cp "$SCRIPT_DIR/CLAUDE.md" "$ALT_DIR/CLAUDE.md"
            cp "$SCRIPT_DIR/chore_timers.yaml.example" "$ALT_DIR/"
            cp "$SCRIPT_DIR/reminders.yaml.example" "$ALT_DIR/"
            cp "$SCRIPT_DIR/settings.json" "$ALT_DIR/settings.json.example"
            echo
            echo "Reference install complete at $ALT_DIR."
            echo
            echo "Next steps:"
            echo "  - Read $ALT_DIR/CLAUDE.md and merge what you want into $CLAUDE_MD"
            echo "  - Re-run install.sh and choose [2] to activate the package"
            echo "  - Or copy things across manually if you prefer"
            exit 0
            ;;
        2)
            echo "Will overwrite $CLAUDE_MD."
            ;;
        *)
            echo "Invalid choice. Aborting."
            exit 1
            ;;
    esac
fi

# --- Standard install path ---

echo
echo "Creating directories..."
mkdir -p "$HOOKS_DIR"
mkdir -p "$DATA_DIR"
mkdir -p "$DATA_DIR/pomodoro-open"

echo "Installing hook scripts..."
cp "$SCRIPT_DIR/hooks/pomodoro-hook.sh" "$HOOKS_DIR/"
cp "$SCRIPT_DIR/hooks/session-start.sh" "$HOOKS_DIR/"
chmod +x "$HOOKS_DIR/pomodoro-hook.sh" "$HOOKS_DIR/session-start.sh"

echo "Installing pomodoro launcher and core..."
cp "$SCRIPT_DIR/pomodoro.py" "$DATA_DIR/"
cp -r "$SCRIPT_DIR/pomodoro-open/." "$DATA_DIR/pomodoro-open/"

echo "Installing CLAUDE.md..."
cp "$SCRIPT_DIR/CLAUDE.md" "$CLAUDE_MD"

# Initialise data files only if absent — never clobber existing user state.

if [ ! -f "$DATA_DIR/session.yaml" ]; then
    echo "Creating session.yaml..."
    cat > "$DATA_DIR/session.yaml" << 'EOF'
completed_ids: []
current_task: null
current_task_type: null
extend_minutes: null
extensions: {}
fun_sessions_completed: 0
last_ack_time: null
meeting_reminders: []
meetings: []
next_break_minutes: null
next_work_minutes: null
pending_resolution: []
session_log: {}
start_time: null
suggest_end_after_hours: 9
suggest_end_at_hour: 17.5
task_switch: null
timer_override_minutes: null
work_sessions_completed: 0
EOF
fi

if [ ! -f "$DATA_DIR/chore_timers.yaml" ]; then
    echo "Creating chore_timers.yaml from example..."
    cp "$SCRIPT_DIR/chore_timers.yaml.example" "$DATA_DIR/chore_timers.yaml"
fi

if [ ! -f "$DATA_DIR/log.yaml" ]; then
    echo "Creating log.yaml..."
    echo "projects: {}" > "$DATA_DIR/log.yaml"
fi

if [ ! -f "$DATA_DIR/tasks.yaml" ]; then
    echo "Creating tasks.yaml..."
    cat > "$DATA_DIR/tasks.yaml" << 'EOF'
# Productivity tasks for body doubling with Claude.
# Claude can help you populate this on the first session.

work_tasks: []
fun_productive: []
EOF
fi

if [ ! -f "$DATA_DIR/reminders.yaml" ]; then
    echo "Creating reminders.yaml from example..."
    cp "$SCRIPT_DIR/reminders.yaml.example" "$DATA_DIR/reminders.yaml"
    echo "  Edit $DATA_DIR/reminders.yaml to set your own reminders."
fi

# Transient files — safe to clobber.
echo '[]' > "$DATA_DIR/prompt_queue.json"
touch "$DATA_DIR/acknowledged.txt"

# --- Hook configuration in settings.json ---

echo
echo "Configuring Claude Code hooks..."
if [ -f "$SETTINGS_FILE" ]; then
    if grep -q "pomodoro-hook.sh" "$SETTINGS_FILE"; then
        echo "  Hook already configured in settings.json."
    else
        echo "  WARNING: $SETTINGS_FILE exists but the pomodoro hook is not configured."
        echo "  Add the contents of $SCRIPT_DIR/settings.json to your settings.json hooks block."
    fi
else
    cp "$SCRIPT_DIR/settings.json" "$SETTINGS_FILE"
    echo "  Created $SETTINGS_FILE with default hook configuration."
fi

# --- Done. Print user manual. ---

cat << 'EOF'

=== Installation Complete ===

Dependencies (install if missing):
  - Python 3 with PyYAML:  pip install pyyaml
  - Desktop notifications: pacman -S libnotify  /  apt install libnotify-bin

------------------------------------------------------------
USER MANUAL
------------------------------------------------------------

1. Restart Claude Code so the hooks load.
2. Send any message (e.g. "hello") to trigger the SessionStart hook.
   Claude will walk you through hydration, chores, meetings, task selection.
3. Start the timer in a separate terminal:
     python3 ~/.claude/productivity/pomodoro.py
   The timer runs independently of Claude Code. Each phase ends with a desktop
   notification and a queued prompt that Claude picks up on your next message.

Ack vocabulary (what Claude writes to acknowledged.txt on your behalf):
  work:Task Name   start work on a task (must match tasks.yaml exactly)
  break            start a break
  extend           keep working — adds 10 min by default,
                   or session.extend_minutes if set
  end              end the session

Mid-phase controls (Claude edits session.yaml):
  task_switch: "New Task"      switch task without breaking the timer
  timer_override_minutes: 0    end current phase immediately
  next_work_minutes: N         one-shot custom work duration
  next_break_minutes: N        one-shot custom break duration

Files (all in ~/.claude/productivity/):
  pomodoro.py        thin wrapper — calls pomodoro-open/adapter_claude.py
  pomodoro-open/     core logic + adapters
  tasks.yaml         your task list
  session.yaml       current session state (resets at start)
  chore_timers.yaml  active chore countdowns
  reminders.yaml     recurring reminders
  log.yaml           cross-session totals
  prompt_queue.json  hook-delivery queue (transient)
  acknowledged.txt   ack signal (transient)

Backup before testing changes:
  bash <repo>/scripts/backup-data.sh
  Snapshots all yaml in ~/.claude/productivity/ to a timestamped folder.

Updating:
  cd <clone> && git pull && ./install.sh
  Re-running install.sh refreshes pomodoro-open/, the launcher, hooks, and
  CLAUDE.md. Your data files are left untouched.

EOF
