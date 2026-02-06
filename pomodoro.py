#!/usr/bin/env python3
"""
Pomodoro state machine for body doubling with Claude.
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
WORK_MINUTES = 25
BREAK_MINUTES = 5
SUGGEST_END_AFTER_HOURS = 9  # suggest ending after this many hours worked
SUGGEST_END_AT_HOUR = 17.5  # suggest ending at this hour (24h clock, e.g. 17.5 = 5:30 PM)
POLL_INTERVAL = 1  # seconds between checking for ack

SESSION_FILE = os.path.expanduser("~/.claude/productivity/session.yaml")
LOG_FILE = os.path.expanduser("~/.claude/productivity/log.yaml")
TASKS_FILE = os.path.expanduser("~/.claude/productivity/tasks.yaml")
REMINDERS_FILE = os.path.expanduser("~/.claude/productivity/reminders.yaml")
PENDING_PROMPT_FILE = os.path.expanduser("~/.claude/productivity/pending_prompt.txt")
ACK_FILE = os.path.expanduser("~/.claude/productivity/acknowledged.txt")

# === PROMPTS (for Claude to act on) ===
WORK_COMPLETE_PROMPT = "Work session complete. Remind the user to drink water, stand up and stretch, and check on household chores."

BREAK_COMPLETE_PROMPT = "Break complete. Offer the user a choice: continue their previous work session if any, or try a different task."

END_SESSION_PROMPT = "The user has been working for several hours. Gently suggest they might want to end the session for today. Ask if they'd like to wrap up, summarise what was accomplished, and save progress."


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

    Returns 'work', 'fun', or None if not found.
    """
    tasks = load_tasks()
    for task in tasks.get('work_tasks', []):
        if task['name'] == task_name:
            return 'work'
    for task in tasks.get('fun_productive', []):
        if task['name'] == task_name:
            return 'fun'
    return None


def parse_ack(content):
    """Parse ack content.

    Formats:
      'continue:task_name' - start next work phase with this task (used after breaks)
      'continue'           - proceed to break (used after work, keeps current task)
      'end'                - end session

    Task type is looked up from tasks.yaml. For new tasks, Claude must
    add the task to tasks.yaml BEFORE writing the ack.
    """
    if content == "end":
        return {"action": "end"}

    if content == "continue":
        return {"action": "continue"}

    parts = content.split(":", 1)
    if len(parts) != 2 or not parts[1].strip():
        print(f"  Error: malformed ack '{content}'. Prompting Claude to fix.")
        write_pending_prompt(
            f"Malformed ack received: '{content}'. Expected one of: 'continue:Task Name', "
            f"'continue', or 'end'. Check the format and re-write the ack file.")
        return None

    action = parts[0]
    task_name = parts[1]
    task_type = lookup_task_type(task_name)

    if task_type is None:
        tasks = load_tasks()
        work_names = [t['name'] for t in tasks.get('work_tasks', [])]
        fun_names = [t['name'] for t in tasks.get('fun_productive', [])]
        existing = ', '.join(work_names + fun_names)
        print(f"  Error: '{task_name}' not in tasks.yaml. Prompting Claude to fix.")
        write_pending_prompt(
            f"Task '{task_name}' is not in tasks.yaml. Existing tasks: [{existing}]. "
            f"Check if this is a typo or name mismatch. If it's a genuinely new task, "
            f"add it to tasks.yaml under the correct category. Confirm with the user, then re-write the ack file.")
        return None

    log = load_log()
    if task_name not in log['projects']:
        existing = ', '.join(log['projects'].keys())
        print(f"  Error: '{task_name}' not in log.yaml. Prompting Claude to fix.")
        write_pending_prompt(
            f"Task '{task_name}' is not in log.yaml. Existing projects: [{existing}]. "
            f"Check if this is a typo or name mismatch. If it's a genuinely new task, "
            f"add it to log.yaml with zeroed values. Confirm with the user, then re-write the ack file.")
        return None

    return {"action": action, "task_name": task_name, "task_type": task_type}


def wait_for_ack():
    """Block until acknowledgment file appears, parse content, then clear it.

    Returns parsed dict. Updates session task only when a task name is provided.
    """
    print("  Waiting for check-in...")
    while True:
        if os.path.exists(ACK_FILE) and os.path.getsize(ACK_FILE) > 0:
            with open(ACK_FILE, 'r') as f:
                content = f.read().strip()
            os.remove(ACK_FILE)
            parsed = parse_ack(content)

            if parsed is None:
                # parse_ack wrote a prompt asking Claude to fix and re-ack
                print("  Waiting for corrected ack...")
                continue

            if "task_name" in parsed:
                session = load_session()
                session["current_task"] = parsed["task_name"]
                session["current_task_type"] = parsed["task_type"]
                if parsed["task_name"] not in session["session_log"]:
                    session["session_log"][parsed["task_name"]] = {"hours": 0, "sessions": 0}
                save_session(session)
                print(f"  Acknowledged: {parsed['action']} - {parsed['task_name']} ({parsed['task_type']})")
            else:
                print(f"  Acknowledged: {parsed['action']}")

            return parsed
        time.sleep(POLL_INTERVAL)



def flush_session_log():
    """Merge session_log into main log.yaml at end of session."""
    session = load_session()
    log = load_log()

    for task_name, data in session['session_log'].items():
        project = log['projects'][task_name]
        project['total_sessions'] += data['sessions']
        project['total_hours'] = round(project['total_hours'] + data['hours'], 2)

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
        'chore_timers': [],
        'completed_items': [],
        'session_log': {},
    }
    save_session(session)


def hours_elapsed(start_time_str):
    if not start_time_str:
        return 0
    start = datetime.fromisoformat(start_time_str)
    return (datetime.now() - start).total_seconds() / 3600


def load_reminders():
    if not os.path.exists(REMINDERS_FILE):
        return []
    with open(REMINDERS_FILE, 'r') as f:
        data = yaml.safe_load(f)
    return data.get('static_reminders', [])


def check_due_items(session):
    """Check for due chores and reminders. Returns list of due item names.

    Sources:
    - Chore timers from session.yaml (dynamic, set by Claude during session)
    - Static reminders from reminders.yaml (recurring schedule)

    Filters out items already in completed_items. Read-only — no saves.
    """
    completed = session.get('completed_items', [])
    now = datetime.now()
    due = []

    # Chore timers
    for chore in session.get('chore_timers', []):
        if chore['name'] in completed:
            continue
        if now >= datetime.fromisoformat(chore['end_time']):
            due.append(chore['name'])

    # Static reminders
    today_day = now.strftime('%a').lower()[:3]
    current_time = now.strftime('%H:%M')
    for reminder in load_reminders():
        if reminder['name'] in completed:
            continue
        days = reminder.get('days', 'daily')
        if days != 'daily' and today_day not in days:
            continue
        if current_time >= reminder['time']:
            due.append(reminder['name'])

    return due


def due_items_text(due_items):
    """Build a prompt snippet for due items (chores and reminders)."""
    if not due_items:
        return ""
    names = ", ".join(due_items)
    return f"\n\nDue items: {names}. Remind the user and ask if they've handled these."


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

    # Update session counters and session_log in one save
    if is_fun_task:
        session['fun_sessions_completed'] += 1
    else:
        session['work_sessions_completed'] += 1
    session['session_log'][task_name]['hours'] = round(
        session['session_log'][task_name]['hours'] + WORK_MINUTES / 60, 2)
    session['session_log'][task_name]['sessions'] += 1
    save_session(session)

    # Chore and reminder checks are read-only - no saves
    prompt = WORK_COMPLETE_PROMPT
    prompt += due_items_text(check_due_items(session))

    if should_suggest_end(session):
        elapsed = hours_elapsed(session.get('start_time'))
        now = datetime.now().strftime('%H:%M')
        prompt += f"\n\n{END_SESSION_PROMPT}\nSession duration so far: {elapsed:.1f} hours. Current time: {now}."

    write_pending_prompt(prompt)
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
    now = datetime.now()
    current_hour = now.hour + now.minute / 60
    if current_hour >= end_at_hour:
        return True
    return False


def break_phase():
    """Run break timer, write prompt, wait for ack. Returns ack content."""
    print("BREAK phase started")
    countdown(BREAK_MINUTES, "BREAK")
    notify("Pomodoro", "Break complete!")

    session = load_session()

    # Combine break complete prompt with any due items into a single prompt
    due = check_due_items(session)
    prompt = BREAK_COMPLETE_PROMPT + due_items_text(due)
    write_pending_prompt(prompt)
    print("BREAK phase complete - prompt written")

    return wait_for_ack()


def main():
    # Check for notify-send
    if not shutil.which('notify-send'):
        print("Error: notify-send not found.")
        print("Install libnotify (e.g., 'pacman -S libnotify' on Arch)")
        return

    # Process ack file left by Claude at startup (sets initial task)
    with open(ACK_FILE, 'r') as f:
        content = f.read().strip()
    os.remove(ACK_FILE)
    parsed = parse_ack(content)
    session = load_session()
    session["current_task"] = parsed["task_name"]
    session["current_task_type"] = parsed["task_type"]
    if parsed["task_name"] not in session["session_log"]:
        session["session_log"][parsed["task_name"]] = {"hours": 0, "sessions": 0}
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

    print("Pomodoro started")
    print(f"Task: {session.get('current_task')}")
    print(f"Type: {session.get('current_task_type', 'work')}")
    print("---")

    def end_session():
        session = load_session()
        elapsed = hours_elapsed(session.get('start_time'))
        print(f"\nSession ended.")
        print(f"Duration: {elapsed:.1f} hours")
        print(f"Work sessions: {session['work_sessions_completed']}")
        print(f"Fun sessions: {session['fun_sessions_completed']}")
        flush_session_log()
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
