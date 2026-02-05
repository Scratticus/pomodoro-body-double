#!/usr/bin/env python3
"""
Pomodoro state machine for body doubling with Claude Code.
Waits for acknowledgment before proceeding to next phase.
"""

import os
import shutil
import subprocess
import time
from datetime import datetime
import yaml


def notify(title, message):
    """Send a desktop notification with sound."""
    print(f"  [Sending notification: {title} - {message}]")
    result = subprocess.run([
        'notify-send',
        '-h', 'string:sound-name:message-new-instant',
        title, message
    ], capture_output=True)
    if result.returncode != 0:
        print(f"  [Notification failed: {result.stderr.decode()}]")


# === CONFIGURATION ===
WORK_MINUTES = float(os.environ.get('POMODORO_WORK_MINUTES', 25))
BREAK_MINUTES = float(os.environ.get('POMODORO_BREAK_MINUTES', 5))
SUGGEST_END_AFTER_HOURS = float(os.environ.get('POMODORO_END_HOURS', 9))
SUGGEST_END_AT_HOUR = int(os.environ.get('POMODORO_END_AT_HOUR', 17))  # 24h clock, e.g. 17 = 5 PM
POLL_INTERVAL = 1  # seconds between checking for ack

# === PATHS ===
DATA_DIR = os.environ.get('POMODORO_DIR', os.path.expanduser('~/.claude/productivity'))
SESSION_FILE = os.path.join(DATA_DIR, 'session.yaml')
LOG_FILE = os.path.join(DATA_DIR, 'log.yaml')
TASKS_FILE = os.path.join(DATA_DIR, 'tasks.yaml')
PENDING_PROMPT_FILE = os.path.join(DATA_DIR, 'pending_prompt.txt')
ACK_FILE = os.path.join(DATA_DIR, 'acknowledged.txt')

# === PROMPTS (for Claude to act on) ===
WORK_COMPLETE_PROMPT = "Work session complete. Remind the user to drink water, stand up and stretch, and check on household chores."

BREAK_COMPLETE_PROMPT = "Break complete. Offer the user a choice: continue their previous work session if any, or try a different task."

END_SESSION_PROMPT = "The user has been working for several hours. Gently suggest they might want to end the session for today. Ask if they'd like to wrap up, summarise what was accomplished, and save progress."


def ensure_data_dir():
    """Create data directory and initial files if needed."""
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, 'w') as f:
            yaml.dump({
                'work_sessions_completed': 0,
                'fun_sessions_completed': 0,
                'current_task': None,
                'current_task_type': None,
                'start_time': None
            }, f)

    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w') as f:
            yaml.dump({'projects': {}}, f)

    if not os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, 'w') as f:
            yaml.dump({
                'work_tasks': [],
                'fun_productive': []
            }, f)


def load_session():
    with open(SESSION_FILE, 'r') as f:
        return yaml.safe_load(f)


def save_session(session):
    with open(SESSION_FILE, 'w') as f:
        yaml.dump(session, f)

    os.environ['POMODORO_WORK_SESSIONS'] = str(session['work_sessions_completed'])
    os.environ['POMODORO_FUN_SESSIONS'] = str(session['fun_sessions_completed'])
    os.environ['POMODORO_CURRENT_TASK'] = str(session['current_task'] or '')
    os.environ['POMODORO_TASK_TYPE'] = str(session['current_task_type'] or '')
    os.environ['POMODORO_START_TIME'] = str(session.get('start_time') or '')


def load_log():
    with open(LOG_FILE, 'r') as f:
        return yaml.safe_load(f) or {'projects': {}}


def save_log(log):
    with open(LOG_FILE, 'w') as f:
        yaml.dump(log, f, default_flow_style=False)


def write_pending_prompt(prompt):
    with open(PENDING_PROMPT_FILE, 'w') as f:
        f.write(prompt)


def load_tasks():
    with open(TASKS_FILE, 'r') as f:
        return yaml.safe_load(f)


def lookup_task_type(task_name):
    """Look up whether a task is 'work' or 'fun' from tasks.yaml.

    Returns 'work' or 'fun'. Raises ValueError if task not found.
    """
    tasks = load_tasks()
    for task in tasks.get('work_tasks', []):
        if task['name'] == task_name:
            return 'work'
    for task in tasks.get('fun_productive', []):
        if task['name'] == task_name:
            return 'fun'
    raise ValueError(f"Task '{task_name}' not found in tasks.yaml")


def parse_ack(content):
    """Parse ack content. Format is always 'continue:task_name' or 'end'.

    Task type is looked up from tasks.yaml. For new tasks, Claude must
    add the task to tasks.yaml BEFORE writing the ack.
    Returns dict with keys: action, task_name, task_type.
    """
    if content == "end":
        return {"action": "end"}

    parts = content.split(":", 1)
    if len(parts) != 2 or not parts[1].strip():
        raise ValueError(f"Malformed ack: expected 'action:task_name', got '{content}'")

    action = parts[0]
    task_name = parts[1]
    task_type = lookup_task_type(task_name)

    return {"action": action, "task_name": task_name, "task_type": task_type}


def wait_for_ack():
    """Block until acknowledgment file appears, parse content, then clear it.

    Returns parsed dict with action, task_name, and task_type.
    Updates session with the current task info.
    """
    print("  Waiting for check-in...")
    while True:
        if os.path.exists(ACK_FILE) and os.path.getsize(ACK_FILE) > 0:
            with open(ACK_FILE, 'r') as f:
                content = f.read().strip()
            os.remove(ACK_FILE)
            parsed = parse_ack(content)
            print(f"  Acknowledged: {parsed}")

            if parsed["action"] != "end":
                session = load_session()
                session["current_task"] = parsed["task_name"]
                session["current_task_type"] = parsed["task_type"]
                save_session(session)
                print(f"  Task set to: {parsed['task_name']} ({parsed['task_type']})")

            return parsed
        time.sleep(POLL_INTERVAL)


def log_session(task_name, sessions=1):
    if not task_name:
        return

    log = load_log()
    today = datetime.now().strftime('%Y-%m-%d')
    minutes = sessions * WORK_MINUTES

    if task_name not in log['projects']:
        log['projects'][task_name] = {
            'total_sessions': 0,
            'total_minutes': 0,
            'history': []
        }

    project = log['projects'][task_name]
    project['total_sessions'] += sessions
    project['total_minutes'] += minutes

    today_entry = None
    for entry in project['history']:
        if entry['date'] == today:
            today_entry = entry
            break

    if today_entry:
        today_entry['sessions'] += sessions
        today_entry['minutes'] += minutes
    else:
        project['history'].append({
            'date': today,
            'sessions': sessions,
            'minutes': minutes
        })

    save_log(log)


def reset_session():
    session = {
        'work_sessions_completed': 0,
        'fun_sessions_completed': 0,
        'current_task': None,
        'current_task_type': None,
        'start_time': None,
        'suggest_end_after_hours': SUGGEST_END_AFTER_HOURS,
        'suggest_end_at_hour': SUGGEST_END_AT_HOUR,
    }
    save_session(session)


def hours_elapsed(start_time_str):
    if not start_time_str:
        return 0
    start = datetime.fromisoformat(start_time_str)
    return (datetime.now() - start).total_seconds() / 3600


def countdown(minutes, label):
    """Display a countdown timer on a single line."""
    total_seconds = int(minutes * 60)
    for remaining in range(total_seconds, 0, -1):
        mins, secs = divmod(remaining, 60)
        print(f"\r  {label} {mins:02d}:{secs:02d}", end="", flush=True)
        time.sleep(1)
    print(f"\r  {label} 00:00    ")


def work_phase(is_fun_task=False):
    """Run work timer, write prompt, wait for ack. Returns ack content."""
    print("WORK phase started")
    countdown(WORK_MINUTES, "WORK")
    notify("Pomodoro", "Work session complete!")

    session = load_session()
    task_name = session.get('current_task')

    if is_fun_task:
        session['fun_sessions_completed'] += 1
    else:
        session['work_sessions_completed'] += 1
    save_session(session)

    log_session(task_name)
    write_pending_prompt(WORK_COMPLETE_PROMPT)
    print("WORK phase complete - prompt written")

    return wait_for_ack()


def should_suggest_end(session):
    """Check if we should suggest ending, based on hours worked or clock time.

    Both thresholds are stored in session.yaml and can be deferred by Claude.
    """
    elapsed = hours_elapsed(session.get('start_time'))
    max_hours = session.get('suggest_end_after_hours', SUGGEST_END_AFTER_HOURS)
    end_at_hour = session.get('suggest_end_at_hour', SUGGEST_END_AT_HOUR)

    if elapsed >= max_hours:
        return True
    if datetime.now().hour >= end_at_hour:
        return True
    return False


def break_phase():
    """Run break timer, write prompt, wait for ack. Returns ack content."""
    print("BREAK phase started")
    countdown(BREAK_MINUTES, "BREAK")
    notify("Pomodoro", "Break complete!")

    session = load_session()

    if should_suggest_end(session):
        elapsed = hours_elapsed(session.get('start_time'))
        now = datetime.now().strftime('%H:%M')
        prompt = BREAK_COMPLETE_PROMPT + f"\n\n{END_SESSION_PROMPT}\nSession duration so far: {elapsed:.1f} hours. Current time: {now}."
    else:
        prompt = BREAK_COMPLETE_PROMPT

    write_pending_prompt(prompt)
    print("BREAK phase complete - prompt written")

    return wait_for_ack()


def main():
    # Check for notify-send
    if not shutil.which('notify-send'):
        print("Error: notify-send not found.")
        print("Install libnotify (e.g., 'pacman -S libnotify' on Arch, 'apt install libnotify-bin' on Debian/Ubuntu)")
        return

    ensure_data_dir()

    # Process ack file left by Claude at startup (sets initial task)
    with open(ACK_FILE, 'r') as f:
        content = f.read().strip()
    os.remove(ACK_FILE)
    parsed = parse_ack(content)
    session = load_session()
    session["current_task"] = parsed["task_name"]
    session["current_task_type"] = parsed["task_type"]
    save_session(session)
    print(f"  Initial task: {parsed['task_name']} ({parsed['task_type']})")

    session = load_session()

    if not session.get('start_time'):
        session['start_time'] = datetime.now().isoformat()
    if 'suggest_end_after_hours' not in session:
        session['suggest_end_after_hours'] = SUGGEST_END_AFTER_HOURS
    if 'suggest_end_at_hour' not in session:
        session['suggest_end_at_hour'] = SUGGEST_END_AT_HOUR
    save_session(session)

    print("=== Pomodoro Body Double ===")
    print(f"Task: {session.get('current_task')}")
    print(f"Type: {session.get('current_task_type', 'work')}")
    print(f"Work: {WORK_MINUTES} min | Break: {BREAK_MINUTES} min")
    print("---")

    def end_session():
        session = load_session()
        elapsed = hours_elapsed(session.get('start_time'))
        print(f"\n=== Session Complete ===")
        print(f"Duration: {elapsed:.1f} hours")
        print(f"Work sessions: {session['work_sessions_completed']}")
        print(f"Fun sessions: {session['fun_sessions_completed']}")
        reset_session()

    try:
        while True:
            is_fun_task = load_session().get('current_task_type') == 'fun'
            ack = work_phase(is_fun_task)
            if ack["action"] == "end":
                end_session()
                break

            ack = break_phase()
            if ack["action"] == "end":
                end_session()
                break
    except KeyboardInterrupt:
        end_session()


if __name__ == "__main__":
    main()
