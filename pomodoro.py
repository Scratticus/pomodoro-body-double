#!/usr/bin/env python3
"""
Pomodoro state machine for body doubling with Claude.
Queues prompts for Claude to act on. Waits for ack before proceeding.
Meeting monitor runs as an independent async task.
"""

import asyncio
import fcntl
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta
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
SUGGEST_END_AFTER_HOURS = 9
SUGGEST_END_AT_HOUR = 17.5
POLL_INTERVAL = 1

SESSION_FILE = os.path.expanduser("~/.claude/productivity/session.yaml")
LOG_FILE = os.path.expanduser("~/.claude/productivity/log.yaml")
TASKS_FILE = os.path.expanduser("~/.claude/productivity/tasks.yaml")
REMINDERS_FILE = os.path.expanduser("~/.claude/productivity/reminders.yaml")
CHORE_TIMERS_FILE = os.path.expanduser("~/.claude/productivity/chore_timers.yaml")
QUEUE_FILE = os.path.expanduser("~/.claude/productivity/prompt_queue.json")
ACK_FILE = os.path.expanduser("~/.claude/productivity/acknowledged.txt")

# === PROMPTS (for Claude to act on) ===
WORK_COMPLETE_PROMPT_TEMPLATE = (
    "Work phase complete. {elapsed:.0f} min worked on {task}. "
    "Remind the user to drink water, stand up and stretch. "
    "Write one of: 'continue' (start break), 'extend' (more work), 'end' (end session) "
    "to ~/.claude/productivity/acknowledged.txt using Write tool."
)

BREAK_COMPLETE_PROMPT = (
    "Break complete. "
    "Write 'continue:Task Name' or 'end' to ~/.claude/productivity/acknowledged.txt using Write tool. "
    "Task name must exactly match a task in tasks.yaml."
)

END_SESSION_PROMPT_TEMPLATE = (
    "Session duration: {elapsed:.1f} hours. Current time: {now}. "
    "Ask if the user wants to end the session or keep working. "
    "To end: write 'end' to ~/.claude/productivity/acknowledged.txt using Write tool."
)


# === QUEUE FUNCTIONS ===

def load_queue():
    """Load the prompt queue from disk."""
    if not os.path.exists(QUEUE_FILE):
        return []
    with open(QUEUE_FILE, 'r') as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def save_queue(queue):
    """Atomic write of the queue to disk."""
    tmp = QUEUE_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(queue, f, indent=2)
    os.rename(tmp, QUEUE_FILE)


def queue_prompt(prompt_type, prompt_text):
    """Append a prompt to the queue."""
    queue = load_queue()
    next_id = max((e['id'] for e in queue), default=0) + 1
    queue.append({
        'id': next_id,
        'timestamp': datetime.now().isoformat(),
        'type': prompt_type,
        'prompt': prompt_text,
        'delivered': False,
    })
    save_queue(queue)
    print(f"  Queued: [{prompt_type}]")


def has_undelivered(prompt_type):
    """Check if there's already an undelivered prompt of this type."""
    queue = load_queue()
    return any(e['type'] == prompt_type and not e['delivered'] for e in queue)


def clear_queue():
    """Clear all entries. Called at session reset."""
    save_queue([])


# === SESSION/LOG FUNCTIONS ===

def load_session():
    with open(SESSION_FILE, 'r') as f:
        return yaml.safe_load(f)


def save_session(session):
    tmp = SESSION_FILE + '.tmp'
    with open(tmp, 'w') as f:
        yaml.dump(session, f)
    os.rename(tmp, SESSION_FILE)


def load_log():
    with open(LOG_FILE, 'r') as f:
        return yaml.safe_load(f) or {'projects': {}}


def save_log(log):
    with open(LOG_FILE, 'w') as f:
        yaml.dump(log, f, default_flow_style=False)


def load_tasks():
    with open(TASKS_FILE, 'r') as f:
        return yaml.safe_load(f)


def normalize_name(name):
    """Normalize a task name for fuzzy matching: lowercase, collapse separators."""
    return re.sub(r'[\s\-\u2013\u2014_]+', '', name.lower())


def find_task(task_name):
    """Find canonical task name and type, normalizing case and separators.

    Treats spaces, hyphens, en-dashes, em-dashes, and underscores as equivalent.
    Returns (canonical_name, task_type) or (None, None) if not found.
    """
    tasks = load_tasks()
    norm = normalize_name(task_name)
    for task in tasks.get('work_tasks', []):
        if normalize_name(task['name']) == norm:
            return task['name'], 'work'
    for task in tasks.get('fun_productive', []):
        if normalize_name(task['name']) == norm:
            return task['name'], 'fun'
    return None, None


def lookup_task_type(task_name):
    """Look up whether a task is 'work' or 'fun' from tasks.yaml."""
    _, task_type = find_task(task_name)
    return task_type


# === ACK FUNCTIONS ===

def parse_ack(content):
    """Parse ack content.

    Formats:
      'continue:task_name' - start next work phase with this task (used after breaks)
      'continue'           - proceed to break (used after work, keeps current task)
      'extend'             - extend current phase type: work extends work, break extends break.
                             Duration read from next_work_minutes / next_break_minutes (default 25/5).
      'end'                - end session
    """
    if content == "end":
        return {"action": "end"}
    if content == "continue":
        return {"action": "continue"}
    if content == "extend":
        return {"action": "extend"}

    parts = content.split(":", 1)
    if len(parts) != 2 or not parts[1].strip():
        print(f"  Error: malformed ack '{content}'.")
        queue_prompt('error',
            f"Malformed ack received: '{content}'. Expected one of: 'continue:Task Name', "
            f"'continue', or 'end'. Check the format and re-write the ack file.")
        return None

    raw_name = parts[1]
    task_name, task_type = find_task(raw_name)

    if task_type is None:
        tasks = load_tasks()
        work_names = [t['name'] for t in tasks.get('work_tasks', [])]
        fun_names = [t['name'] for t in tasks.get('fun_productive', [])]
        existing = ', '.join(work_names + fun_names)
        print(f"  Error: '{raw_name}' not in tasks.yaml.")
        queue_prompt('error',
            f"Task '{raw_name}' is not in tasks.yaml. Existing tasks: [{existing}]. "
            f"Check if this is a typo or name mismatch. If it's a genuinely new task, "
            f"add it to tasks.yaml under the correct category. Confirm with the user, "
            f"then re-write the ack file.")
        return None

    log = load_log()
    if task_name not in log['projects']:
        existing = ', '.join(log['projects'].keys())
        print(f"  Error: '{task_name}' not in log.yaml.")
        queue_prompt('error',
            f"Task '{task_name}' is not in log.yaml. Existing projects: [{existing}]. "
            f"Check if this is a typo or name mismatch. If it's a genuinely new task, "
            f"add it to log.yaml with zeroed values. Confirm with the user, "
            f"then re-write the ack file.")
        return None

    return {"action": parts[0], "task_name": task_name, "task_type": task_type}


REMINDER_INTERVAL_DEFAULT = 300  # Default: re-send notification every 5 minutes


async def wait_for_ack():
    """Block until ack file appears, parse content, then clear it."""
    print("  Waiting for check-in...")
    last_reminder_time = asyncio.get_event_loop().time()
    reminder_count = 0
    extend_prompted = False
    while True:
        now = asyncio.get_event_loop().time()
        session = load_session()
        reminder_enabled = session.get('reminder_enabled', True)
        reminder_interval = session.get('reminder_interval_minutes', REMINDER_INTERVAL_DEFAULT / 60) * 60
        if reminder_enabled and now - last_reminder_time >= reminder_interval:
            notify("Pomodoro", "Still waiting for you!")
            last_reminder_time = now
            reminder_count += 1
            if reminder_count >= 2 and not extend_prompted:
                extend_prompted = True
                session = load_session()
                if not session.get('extend_minutes'):
                    session['extend_minutes'] = 10
                    save_session(session)
                queue_prompt('extend_reminder',
                    "Ack was overdue — automatically extended by 10 minutes. "
                    "When ready, write 'continue' (break), 'extend' (more work), or 'end' "
                    "to ~/.claude/productivity/acknowledged.txt using Write tool.")
                notify("Pomodoro", "Session overrun — auto-extended by 10 min")
        if os.path.exists(ACK_FILE) and os.path.getsize(ACK_FILE) > 0:
            with open(ACK_FILE, 'r') as f:
                content = f.read().strip()
            os.remove(ACK_FILE)
            parsed = parse_ack(content)

            if parsed is None:
                print("  Waiting for corrected ack...")
                continue

            session = load_session()
            session["last_ack_time"] = datetime.now().isoformat()
            session["extend_minutes"] = None  # clear any pending extend so it doesn't bleed into the next phase

            if "task_name" in parsed:
                session["current_task"] = parsed["task_name"]
                session["current_task_type"] = parsed["task_type"]
                if parsed["task_name"] not in session["session_log"]:
                    session["session_log"][parsed["task_name"]] = {"hours": 0, "sessions": 0}
                save_session(session)
                print(f"  Acknowledged: {parsed['action']} - {parsed['task_name']} ({parsed['task_type']})")
            else:
                save_session(session)
                print(f"  Acknowledged: {parsed['action']}")

            # P6: apply meeting-aware durations now that we know actual current time
            session = load_session()
            apply_meeting_aware_durations(session)

            return parsed
        await asyncio.sleep(POLL_INTERVAL)


# === HELPER FUNCTIONS ===

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
    # Remove completed chores from chore_timers.yaml before clearing session state.
    # Every chore:N in completed_ids has a matching entry in chore_timers.yaml — no check needed.
    session = load_session()
    completed_ids = session.get('completed_ids', [])
    completed_chore_ids = {int(x.split(':')[1]) for x in completed_ids if x.startswith('chore:')}
    if completed_chore_ids:
        timers = load_chore_timers()
        timers = [t for t in timers if t.get('id') not in completed_chore_ids]
        save_chore_timers(timers)

    session = {
        'work_sessions_completed': 0,
        'fun_sessions_completed': 0,
        'current_task': None,
        'current_task_type': None,
        'start_time': None,
        'suggest_end_after_hours': SUGGEST_END_AFTER_HOURS,
        'suggest_end_at_hour': SUGGEST_END_AT_HOUR,
        'meetings': [],
        'meeting_reminders': [],
        'completed_ids': [],
        'extensions': {},
        'pending_resolution': [],
        'session_log': {},
        'last_ack_time': None,
        'next_work_minutes': None,
        'next_break_minutes': None,
        'timer_override_minutes': None,
        'extend_minutes': None,
        'task_switch': None,
    }
    save_session(session)
    clear_queue()


def hours_elapsed(start_time_str):
    if not start_time_str:
        return 0
    start = datetime.fromisoformat(start_time_str)
    return (datetime.now() - start).total_seconds() / 3600


def check_unknown_fields(item, known_fields, source):
    """Queue a non-blocking correction prompt if item contains unexpected field names.

    Claude will silently rename mismatched keys and notify briefly.
    Only asks the user if the correct mapping is genuinely unclear.
    Returns True if item is clean, False if unexpected fields were found (item should be skipped).
    """
    unexpected = {k for k in item if k not in known_fields}
    if not unexpected:
        return True
    queue_prompt('error',
        f"Entry in {source} has unexpected fields: {sorted(unexpected)}. "
        f"Full entry: {dict(item)}. "
        f"Expected fields: {sorted(known_fields)}. "
        f"Rename any mismatched keys in {source} to match the expected format. "
        f"Notify briefly what was changed. Only ask the user if the correct mapping is genuinely unclear.")
    return False


def ensure_ids(items):
    """Assign integer IDs to any items missing one, and fix any duplicate IDs.

    Mutates items in-place. Returns True if any changes were made.
    Works for chores, reminders, and meetings — anything with an optional 'id' field.
    """
    used_ids = set()
    next_id = max((item['id'] for item in items if 'id' in item), default=0) + 1
    changed = False
    for item in items:
        if 'id' not in item or item['id'] in used_ids:
            item['id'] = next_id
            next_id += 1
            changed = True
        used_ids.add(item['id'])
    return changed


REMINDER_KNOWN_FIELDS = {'id', 'name', 'time', 'days', 'skip_if_sick'}


def load_reminders():
    if not os.path.exists(REMINDERS_FILE):
        return []
    with open(REMINDERS_FILE, 'r') as f:
        data = yaml.safe_load(f)
    reminders = data.get('static_reminders') or []
    if ensure_ids(reminders):
        save_reminders(reminders)
    return [r for r in reminders
            if check_unknown_fields(r, REMINDER_KNOWN_FIELDS, 'reminders.yaml')]


def save_reminders(reminders):
    """Write reminders back to reminders.yaml."""
    tmp = REMINDERS_FILE + '.tmp'
    with open(tmp, 'w') as f:
        yaml.dump({'static_reminders': reminders}, f, default_flow_style=False)
    os.rename(tmp, REMINDERS_FILE)


CHORE_KNOWN_FIELDS = {'id', 'name', 'end_time', 'duration_minutes'}


def load_chore_timers():
    """Load chore timers from persistent chore_timers.yaml.

    Assigns missing IDs and fixes duplicates automatically.
    If a chore has duration_minutes, converts to end_time now and saves.
    This lets Claude write duration_minutes without doing datetime arithmetic.
    Works for both initial set and delay: duration_minutes always overwrites end_time.
    Skips and flags any entries with unrecognized field names.
    """
    if not os.path.exists(CHORE_TIMERS_FILE):
        return []
    with open(CHORE_TIMERS_FILE, 'r') as f:
        data = yaml.safe_load(f) or {}
    timers = data.get('chore_timers') or []
    changed = ensure_ids(timers)
    valid = []
    for chore in timers:
        if not check_unknown_fields(chore, CHORE_KNOWN_FIELDS, 'chore_timers.yaml'):
            continue
        if 'duration_minutes' in chore:
            chore['end_time'] = (datetime.now() +
                timedelta(minutes=chore['duration_minutes'])).isoformat()
            del chore['duration_minutes']
            changed = True
        elif 'end_time' not in chore:
            queue_prompt('error',
                f"Chore '{chore.get('name', '?')}' (id={chore.get('id', '?')}) has no end_time or duration_minutes. "
                f"Ask the user how long it takes and write duration_minutes: N to the "
                f"chore entry in ~/.claude/productivity/chore_timers.yaml.")
            continue
        valid.append(chore)
    if changed:
        save_chore_timers(timers)
    return valid


def save_chore_timers(timers):
    """Write chore timers to persistent chore_timers.yaml."""
    tmp = CHORE_TIMERS_FILE + '.tmp'
    with open(tmp, 'w') as f:
        yaml.dump({'chore_timers': timers}, f, default_flow_style=False)
    os.rename(tmp, CHORE_TIMERS_FILE)


MEETING_KNOWN_FIELDS = {'id', 'name', 'start_time', 'duration_minutes', 'task'}


def build_meeting_reminders(meeting):
    """Return a list of meeting_reminder dicts for all warning thresholds.

    meeting_reminders are informational-only items, modelled after chores.
    id format: 'mtgrem:<meeting_int_id>:<threshold_minutes>'
    """
    try:
        start = parse_user_timestamp(meeting['start_time'])
    except (ValueError, KeyError):
        return []
    reminders = []
    for mins in MEETING_WARNING_THRESHOLDS:
        due_at = start - timedelta(minutes=mins)
        reminders.append({
            'id': f"mtgrem:{meeting['id']}:{mins}",
            'meeting_id': meeting['id'],
            'name': meeting['name'],
            'due_at': fmt_ts(due_at),
        })
    return reminders


def validate_meetings():
    """Assign IDs to meetings, validate required fields, and materialise meeting_reminders.

    Called at startup. Claude writes name, start_time (DD/MM/YYYY HH:MM),
    duration_minutes, and task — Python assigns the integer id.
    Also called implicitly when the meeting_monitor snapshot detects a new or changed meeting.
    """
    session = load_session()
    meetings = session.get('meetings', [])
    if not meetings:
        return
    changed = ensure_ids(meetings)
    existing_reminders = {r['id']: r for r in session.get('meeting_reminders', [])}
    for meeting in meetings:
        if not check_unknown_fields(meeting, MEETING_KNOWN_FIELDS, 'session.yaml (meetings)'):
            continue
        errors = []
        if 'start_time' not in meeting:
            errors.append("start_time (format: 'DD/MM/YYYY HH:MM')")
        if 'duration_minutes' not in meeting:
            errors.append("duration_minutes (integer)")
        if 'task' not in meeting:
            errors.append("task (must match a name in tasks.yaml)")
        if errors:
            queue_prompt('error',
                f"Meeting '{meeting.get('name', '?')}' (id={meeting['id']}) is missing: "
                f"{', '.join(errors)}. "
                f"Add the missing fields to the entry in ~/.claude/productivity/session.yaml.")
            continue
        # Regenerate reminders for this meeting (replaces any existing ones)
        for r in build_meeting_reminders(meeting):
            existing_reminders[r['id']] = r
        changed = True
    session['meetings'] = meetings
    session['meeting_reminders'] = list(existing_reminders.values())
    if changed:
        save_session(session)


def parse_user_timestamp(value):
    """Parse a user-facing timestamp string (DD/MM/YYYY HH:MM), falling back to ISO.

    Returns a datetime or raises ValueError if unparseable.
    """
    if isinstance(value, str):
        for fmt in ('%d/%m/%Y %H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f'):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    raise ValueError(f"Cannot parse timestamp: {value!r}")


def fmt_ts(dt):
    """Format a datetime as DD/MM/YYYY HH:MM for user-facing storage."""
    return dt.strftime('%d/%m/%Y %H:%M')


def process_extensions():
    """Process pending extension requests written by Claude to session.yaml.

    extensions is a dict keyed by prefixed id: {'chore:1': {'delay': 30}, 'reminder:3': {'until': '...'}}
    Claude writes {delay: N} (integer minutes) or {delay: 'DD/MM/YYYY HH:MM'} (absolute timestamp).
    Type is determined from the key prefix. Python converts delay to until:
    - chore: updates end_time in chore_timers.yaml; key removed from extensions.
    - reminder: key kept in extensions with {until: str} replacing {delay: ...}.
    Keys already containing 'until' are active snoozes — left untouched.
    Meetings never appear here — Claude updates start_time directly.
    Malformed or unknown entries queue an error prompt; they are discarded.
    """
    session = load_session()
    extensions = session.get('extensions', {})
    if not extensions:
        return
    chores = {c['id']: c for c in load_chore_timers()}
    reminder_ids = {r['id'] for r in load_reminders()}
    updated = {}
    chores_changed = False
    now = datetime.now()
    for item_id, attrs in extensions.items():
        if 'until' in attrs:
            updated[item_id] = attrs  # active snooze, leave it
            continue
        delay = attrs.get('delay')
        if delay is None:
            queue_prompt('error',
                f"Extension '{item_id}' in session.yaml has no 'delay' field. "
                f"Expected {{delay: <minutes or 'DD/MM/YYYY HH:MM'>}}. "
                f"Correct it in ~/.claude/productivity/session.yaml.")
            continue
        try:
            item_type, int_id_str = item_id.split(':', 1)
            int_id = int(int_id_str)
        except (ValueError, AttributeError):
            queue_prompt('error',
                f"Extension key '{item_id}' is not a valid prefixed id (e.g. 'chore:1'). "
                f"Correct it in ~/.claude/productivity/session.yaml.")
            continue
        if isinstance(delay, int):
            until_dt = now + timedelta(minutes=delay)
        else:
            try:
                until_dt = parse_user_timestamp(str(delay))
                if until_dt <= now:
                    queue_prompt('error',
                        f"Extension for {item_id} has a timestamp in the past: '{delay}'. "
                        f"Confirm the correct time with the user and rewrite the entry.")
                    continue
            except ValueError:
                queue_prompt('error',
                    f"Extension for {item_id} has an unrecognised delay format: '{delay}'. "
                    f"Use an integer (minutes) or 'DD/MM/YYYY HH:MM'.")
                continue
        until_str = fmt_ts(until_dt)
        if item_type == 'chore':
            if int_id in chores:
                chores[int_id]['end_time'] = until_str
                chores_changed = True
            else:
                queue_prompt('error',
                    f"Extension '{item_id}' not found in chore_timers.yaml.")
        elif item_type == 'reminder':
            if int_id in reminder_ids:
                updated[item_id] = {'until': until_str}
            else:
                queue_prompt('error',
                    f"Extension '{item_id}' not found in reminders.yaml.")
        else:
            queue_prompt('error',
                f"Unrecognised type in extension key '{item_id}'. "
                f"Expected 'chore:N' or 'reminder:N'.")
    if chores_changed:
        save_chore_timers(list(chores.values()))
    session['extensions'] = updated
    save_session(session)


def check_due_items(session):
    """Check for due chores and reminders. Returns list of {id, name, type} dicts.

    id is the prefixed string key (e.g. 'chore:1', 'reminder:3').
    extensions is a dict keyed by prefixed id; snooze entries have 'until' field.
    """
    completed_ids = set(session.get('completed_ids', []))
    extensions = session.get('extensions', {})
    now = datetime.now()
    due = []

    for chore in load_chore_timers():
        key = f"chore:{chore['id']}"
        if key in completed_ids:
            continue
        if now >= parse_user_timestamp(chore['end_time']):
            due.append({'id': key, 'name': chore['name'], 'type': 'chore'})

    today_day = now.strftime('%a').lower()[:3]
    for reminder in load_reminders():
        key = f"reminder:{reminder['id']}"
        if key in completed_ids:
            continue
        snooze = extensions.get(key, {})
        if 'until' in snooze:
            try:
                if now < parse_user_timestamp(snooze['until']):
                    continue
            except ValueError:
                pass
        days = reminder.get('days', 'daily')
        if days != 'daily' and today_day not in days:
            continue
        h, m = reminder['time'].split(':')
        due_at = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        if now >= due_at:
            due.append({'id': key, 'name': reminder['name'], 'type': 'reminder'})

    return due


def due_items_text(due_items, hard_blocker=True):
    """Build a prompt snippet for due items.

    hard_blocker=True (break end): blocks ack until resolved.
    hard_blocker=False (work end): informational mention only.
    """
    if not due_items:
        return ""
    lines = []
    for item in due_items:
        iid = item['id']
        name = item['name']
        if hard_blocker:
            lines.append(
                f"  - {item['type'].capitalize()} '{name}' (id={iid}): "
                f"HARD BLOCKER — do NOT write any ack or allow the session to proceed. "
                f"Ask the user to resolve this. "
                f"If done: add '{iid}' to completed_ids in ~/.claude/productivity/session.yaml. "
                f"If more time needed: add {iid}: {{delay: <minutes or 'DD/MM/YYYY HH:MM'>}} "
                f"under extensions in ~/.claude/productivity/session.yaml."
            )
        else:
            lines.append(
                f"  - {item['type'].capitalize()} '{name}' (id={iid}) is due. "
                f"Mention it to the user; it becomes a hard blocker at break end."
            )
    header = (
        "\n\nDue items — resolve before continuing:\n" if hard_blocker
        else "\n\nFYI — due items (non-blocking):\n"
    )
    return header + "\n".join(lines)


def check_upcoming_meeting(session):
    """Check if a meeting starts within 30 min. Returns (id, name, mins_away) or None."""
    now = datetime.now()
    completed_ids = set(session.get('completed_ids', []))
    for meeting in session.get('meetings', []):
        if 'id' not in meeting:
            continue
        if f"meeting:{meeting['id']}" in completed_ids:
            continue
        try:
            start = parse_user_timestamp(meeting['start_time'])
        except ValueError:
            continue
        mins_away = (start - now).total_seconds() / 60
        if 0 < mins_away <= 30:
            return meeting['id'], meeting['name'], mins_away
    return None


async def countdown(minutes, label):
    """Display a countdown timer on a single line.
    Checks session.yaml every 10 seconds for:
      - timer_override_minutes: adjusts remaining time (0 = end immediately)
      - task_switch: switch to a different task mid-phase (work phases only)
    Returns dict with 'elapsed_seconds' and 'task_switches' (list of
    {task_name, seconds_spent} for time tracking)."""
    remaining = int(minutes * 60)
    total_seconds = remaining
    check_interval = 10  # seconds between override checks
    seconds_since_check = 0
    task_switches = []  # track mid-phase task changes
    switch_started_at = 0  # seconds elapsed when current task started
    while remaining > 0:
        mins, secs = divmod(remaining, 60)
        print(f"\r  {label} {mins:02d}:{secs:02d}", end="", flush=True)
        await asyncio.sleep(1)
        remaining -= 1
        seconds_since_check += 1
        if seconds_since_check >= check_interval:
            seconds_since_check = 0
            try:
                session = load_session()
                # Check for timer override (0 = end early, other = jump to that remaining time)
                override = session.get('timer_override_minutes')
                if override is not None:
                    new_remaining = int(override * 60)
                    old_mins, old_secs = divmod(remaining, 60)
                    new_mins, new_secs = divmod(new_remaining, 60)
                    if new_remaining == 0:
                        print(f"\n  Phase ended early")
                        notify("Pomodoro", "Phase ended early")
                    else:
                        print(f"\n  Timer override: {old_mins:02d}:{old_secs:02d} -> {new_mins:02d}:{new_secs:02d}")
                        notify("Pomodoro", f"Timer adjusted to {int(override)} min")
                    remaining = new_remaining
                    session['timer_override_minutes'] = None
                    save_session(session)

                # Check for extend_minutes (add time to running phase)
                extend = session.get('extend_minutes')
                if extend is not None and extend > 0:
                    add_seconds = int(extend * 60)
                    remaining += add_seconds
                    total_seconds += add_seconds
                    print(f"\n  Phase extended by {int(extend)} min")
                    notify("Pomodoro", f"Phase extended by {int(extend)} min")
                    session['extend_minutes'] = None
                    save_session(session)

                # Check for task switch (work phases only)
                switch = session.get('task_switch')
                if switch is not None:
                    elapsed_on_current = (total_seconds - remaining) - switch_started_at
                    old_task = session.get('current_task', 'Unknown')
                    task_switches.append({
                        'task_name': old_task,
                        'seconds_spent': elapsed_on_current,
                    })
                    canonical_switch, new_task_type = find_task(switch)
                    if new_task_type:
                        session['current_task'] = canonical_switch
                        session['current_task_type'] = new_task_type
                        if canonical_switch not in session.get('session_log', {}):
                            session['session_log'][canonical_switch] = {"hours": 0, "sessions": 0}
                        print(f"\n  Switched: {old_task} -> {canonical_switch}")
                        notify("Pomodoro", f"Switched to {canonical_switch}")
                        label = f"WORK ({canonical_switch})"
                    else:
                        print(f"\n  Task switch failed: '{switch}' not in tasks.yaml")
                        queue_prompt('error',
                            f"Task switch failed: '{switch}' not in tasks.yaml. "
                            f"Check the name and try again.")
                    session['task_switch'] = None
                    switch_started_at = total_seconds - remaining
                    save_session(session)
            except Exception:
                pass  # don't crash the timer on a read error
    print(f"\r  {label} 00:00    ")
    # Record time for the final task segment
    elapsed_on_current = (total_seconds - remaining) - switch_started_at
    if elapsed_on_current > 0:
        session = load_session()
        task_switches.append({
            'task_name': session.get('current_task', 'Unknown'),
            'seconds_spent': elapsed_on_current,
        })
    return {
        'elapsed_seconds': total_seconds,
        'task_switches': task_switches,
    }


def should_suggest_end(session):
    """Check if we should suggest ending, based on hours worked or clock time."""
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


def apply_meeting_aware_durations(session):
    """Adjust next phase durations based on upcoming meetings.

    Called at ack time so calculation uses actual current time.
    Only sets durations if not already user-defined.
    """
    now = datetime.now()
    min_mins = float('inf')
    completed_ids = set(session.get('completed_ids', []))
    for meeting in session.get('meetings', []):
        if 'id' not in meeting:
            continue
        if f"meeting:{meeting['id']}" in completed_ids:
            continue
        try:
            start = parse_user_timestamp(meeting['start_time'])
        except ValueError:
            continue
        mins = (start - now).total_seconds() / 60
        if 0 < mins < min_mins:
            min_mins = mins

    if min_mins == float('inf'):
        return  # no upcoming meetings

    one_cycle = WORK_MINUTES + BREAK_MINUTES
    two_cycles = 2 * one_cycle

    if min_mins <= BREAK_MINUTES + 5:
        if not session.get('next_break_minutes'):
            session['next_break_minutes'] = max(1, int(min_mins))
    elif min_mins <= one_cycle:
        if not session.get('next_work_minutes'):
            session['next_work_minutes'] = max(5, int(min_mins - BREAK_MINUTES))
    elif min_mins <= two_cycles:
        if not session.get('next_work_minutes'):
            session['next_work_minutes'] = max(5, int((min_mins - BREAK_MINUTES) / 2))

    save_session(session)


def has_git_tasks(session_log):
    """Returns dict of {task_name: has_git} for all tasks in session_log."""
    tasks = load_tasks()
    all_tasks = tasks.get('work_tasks', []) + tasks.get('fun_productive', [])
    result = {}
    for t in all_tasks:
        if t['name'] in session_log:
            result[t['name']] = t.get('has_git', False)
    return result


# === MEETING MONITOR ===

MEETING_WARNING_THRESHOLDS = [60, 30, 15, 5]  # minutes before meeting


async def meeting_monitor():
    """Async task: checks meetings, meeting reminders, chores, and reminders every 30 seconds.

    Meetings: auto-starts next work phase via ack file when meeting time arrives.
    Meeting reminders: informational warnings at 60/30/15/5 min thresholds, tracked in session.
    Chores/reminders: mid-phase alerts queued to Claude. Single alerted set prevents duplicates.
    Snapshot-based change detection: calls validate_meetings() when meetings are added or edited.
    Snooze expiry: removes expired extension entries so items can re-alert.
    """
    alerted = set()        # prefixed IDs queued mid-session (prevents duplicate prompts)
    meeting_snapshot = {}  # {meeting_int_id: start_time_str} — change detection

    while True:
        try:
            session = load_session()
            now = datetime.now()
            completed_ids_set = set(session.get('completed_ids', []))

            # --- Snapshot-based change detection ---
            # Regenerates meeting_reminders when Claude adds or edits a meeting.
            current_meetings = session.get('meetings', [])
            current_ids = {m['id'] for m in current_meetings if 'id' in m}
            snapshot_changed = (set(meeting_snapshot.keys()) != current_ids) or any(
                meeting_snapshot.get(m['id']) != m.get('start_time')
                for m in current_meetings if 'id' in m
            )
            if snapshot_changed:
                validate_meetings()
                session = load_session()
                now = datetime.now()
                completed_ids_set = set(session.get('completed_ids', []))
            meeting_snapshot = {
                m['id']: m.get('start_time')
                for m in session.get('meetings', [])
                if 'id' in m
            }

            # --- Meeting reminders (informational, fire once via completed_ids) ---
            for mrem in session.get('meeting_reminders', []):
                rem_id = mrem['id']
                if rem_id in completed_ids_set or rem_id in alerted:
                    continue
                try:
                    due_at = parse_user_timestamp(mrem['due_at'])
                except ValueError:
                    continue
                if now >= due_at:
                    alerted.add(rem_id)
                    session2 = load_session()
                    session2.setdefault('completed_ids', []).append(rem_id)
                    save_session(session2)
                    completed_ids_set.add(rem_id)
                    queue_prompt('meeting_warning',
                        f"Meeting '{mrem['name']}' is coming up soon. "
                        f"Inform the user and help them wrap up if needed.")
                    notify("Pomodoro", f"Meeting '{mrem['name']}' soon!")
                    print(f"\n  Meeting reminder: '{mrem['name']}' (id={rem_id})")

            # --- Meetings (auto-start work phase when meeting time arrives) ---
            for meeting in session.get('meetings', []):
                if 'id' not in meeting:
                    continue
                key = f"meeting:{meeting['id']}"
                if key in completed_ids_set:
                    continue
                try:
                    start = parse_user_timestamp(meeting['start_time'])
                except ValueError:
                    continue
                mins_away = (start - now).total_seconds() / 60
                if mins_away <= 0:
                    task = meeting.get('task')
                    duration = meeting.get('duration_minutes', WORK_MINUTES)
                    session2 = load_session()
                    session2.setdefault('completed_ids', []).append(key)
                    session2['next_work_minutes'] = duration
                    save_session(session2)
                    completed_ids_set.add(key)
                    if task:
                        with open(ACK_FILE, 'w') as f:
                            f.write(f"continue:{task}")
                        print(f"\n  Auto-starting meeting: '{meeting['name']}' (task={task}, {duration} min)")
                        notify("Pomodoro", f"Meeting starting: {meeting['name']}")
                    else:
                        queue_prompt('error',
                            f"Meeting '{meeting.get('name', '?')}' (id={key}) started but has no 'task' field. "
                            f"Add task to the meeting entry in ~/.claude/productivity/session.yaml.")

            # --- Chores (mid-phase alert) ---
            for chore in load_chore_timers():
                key = f"chore:{chore['id']}"
                if key in completed_ids_set or key in alerted:
                    continue
                try:
                    if now >= parse_user_timestamp(chore['end_time']):
                        alerted.add(key)
                        queue_prompt('chore',
                            f"Chore '{chore['name']}' is now due. "
                            f"Ask the user if it is completed. "
                            f"If completed: add '{key}' to the completed_ids list in "
                            f"~/.claude/productivity/session.yaml. "
                            f"If more time needed: add {key}: {{delay: <minutes or 'DD/MM/YYYY HH:MM'>}} "
                            f"under extensions in ~/.claude/productivity/session.yaml.")
                        notify("Pomodoro", f"Chore due: {chore['name']}")
                        print(f"\n  Chore due: '{chore['name']}'")
                except ValueError:
                    pass

            # --- Reminders (mid-phase alert) ---
            today_day = now.strftime('%a').lower()[:3]
            for reminder in load_reminders():
                key = f"reminder:{reminder['id']}"
                if key in completed_ids_set or key in alerted:
                    continue
                days = reminder.get('days', 'daily')
                if days != 'daily' and today_day not in days:
                    continue
                h, m_str = reminder['time'].split(':')
                due_at = now.replace(hour=int(h), minute=int(m_str), second=0, microsecond=0)
                if now >= due_at:
                    alerted.add(key)
                    queue_prompt('reminder',
                        f"Reminder '{reminder['name']}' is now due. "
                        f"Ask the user if they've done it. "
                        f"If done: add '{key}' to the completed_ids list in "
                        f"~/.claude/productivity/session.yaml. "
                        f"If deferring: do nothing (fires again next session).")
                    notify("Pomodoro", f"Reminder: {reminder['name']}")
                    print(f"\n  Reminder due: '{reminder['name']}'")

            # --- Snooze expiry cleanup ---
            # Remove expired reminder snooze entries from extensions so items can re-alert.
            session2 = load_session()
            extensions = session2.get('extensions', {})
            expired_keys = [
                k for k, v in extensions.items()
                if 'until' in v and _snooze_expired(v['until'], now)
            ]
            if expired_keys:
                for k in expired_keys:
                    del extensions[k]
                    alerted.discard(k)
                session2['extensions'] = extensions
                save_session(session2)

        except Exception as e:
            print(f"\n  Meeting monitor error: {e}")
        await asyncio.sleep(30)


def _snooze_expired(until_str, now):
    """Return True if the snooze timestamp has passed or cannot be parsed."""
    try:
        return now >= parse_user_timestamp(until_str)
    except ValueError:
        return True


# === PHASE FUNCTIONS ===

async def work_phase(is_fun_task=False):
    """Run work timer, queue prompt, wait for ack. Returns ack dict."""
    session = load_session()
    work_started_at = session.get('last_ack_time') or datetime.now().isoformat()
    initial_task = session.get('current_task')

    # B1: read into local variable first, then clear unconditionally
    work_mins = session.get('next_work_minutes') or WORK_MINUTES
    session['next_work_minutes'] = None
    save_session(session)

    print(f"WORK phase started ({work_mins} min)")
    timer_result = await countdown(work_mins, f"WORK ({initial_task})")
    notify("Pomodoro", "Work session complete!")

    # Build and queue the work complete prompt
    session = load_session()
    task_name = session.get('current_task')
    meeting = check_upcoming_meeting(session)
    upcoming_break_mins = session.get('next_break_minutes') or BREAK_MINUTES

    elapsed_min = timer_result.get('elapsed_seconds', work_mins * 60) / 60
    prompt = WORK_COMPLETE_PROMPT_TEMPLATE.format(
        elapsed=elapsed_min, task=task_name or 'Unknown')
    process_extensions()
    session = load_session()
    prompt += due_items_text(check_due_items(session), hard_blocker=False)

    if meeting:
        mid, name, mins_away = meeting
        extend_mins = int(mins_away - upcoming_break_mins)
        if extend_mins > 0:
            prompt += (f"\n\nMeeting '{name}' starts in {int(mins_away)} minutes. "
                       f"Suggest extending work by {extend_mins} min for a "
                       f"{upcoming_break_mins}-min break before it.")
            notify("Pomodoro", f"Meeting '{name}' in {int(mins_away)} min!")
            print(f"  Meeting '{name}' in {int(mins_away)} min")

    if should_suggest_end(session) and not has_undelivered('end_session_suggestion'):
        elapsed = hours_elapsed(session.get('start_time'))
        now_str = datetime.now().strftime('%H:%M')
        git_info = has_git_tasks(session.get('session_log', {}))
        git_summary = '; '.join(f"{k}: has_git={v}" for k, v in git_info.items())
        prompt += (f"\n\n{END_SESSION_PROMPT_TEMPLATE.format(elapsed=elapsed, now=now_str)}"
                   f" Tasks this session: {git_summary}.")

    queue_prompt('work_complete', prompt)
    print("WORK phase complete")

    ack = await wait_for_ack()

    # Handle extend: run more work time, then wait for ack again
    if ack["action"] == "extend":
        session = load_session()
        # If a meeting is upcoming, use time-to-meeting minus break as the extension
        if meeting:
            mid = meeting[0]
            meetings_list = session.get('meetings', [])
            matching = [m for m in meetings_list if m.get('id') == mid]
            if matching:
                try:
                    start_dt = parse_user_timestamp(matching[0]['start_time'])
                except ValueError:
                    start_dt = None
                mins_away_now = (
                    (start_dt - datetime.now()).total_seconds() / 60
                    if start_dt else 0
                )
                if mins_away_now > upcoming_break_mins:
                    extend_mins = int(mins_away_now - upcoming_break_mins)
                else:
                    extend_mins = session.get('next_work_minutes') or WORK_MINUTES
            else:
                extend_mins = session.get('next_work_minutes') or WORK_MINUTES
        else:
            extend_mins = session.get('next_work_minutes') or WORK_MINUTES
        session['next_work_minutes'] = None
        save_session(session)
        print(f"  Extending work by {extend_mins} min")
        notify("Pomodoro", f"Work extended by {extend_mins} min")
        current_task = session.get('current_task', 'Unknown')
        await countdown(extend_mins, f"EXTENDED ({current_task})")
        notify("Pomodoro", "Extended work complete!")
        queue_prompt('work_complete',
            f"Extended work session complete on {session.get('current_task', 'Unknown')}. "
            f"Write one of: 'continue' (start break), 'extend' (more work), 'end' (end session) "
            f"to ~/.claude/productivity/acknowledged.txt using Write tool.")
        ack = await wait_for_ack()

    # Log time per task using countdown's task_switches data
    task_switches = timer_result.get('task_switches', [])
    session = load_session()

    # Also account for any ack wait time (attribute to the last active task)
    started = datetime.fromisoformat(work_started_at)
    total_real_elapsed = (datetime.now() - started).total_seconds()
    timer_elapsed = timer_result.get('elapsed_seconds', 0)
    ack_wait_seconds = max(0, total_real_elapsed - timer_elapsed)

    for i, segment in enumerate(task_switches):
        seg_task = segment['task_name']
        seg_seconds = segment['seconds_spent']
        # Add ack wait time to the last segment
        if i == len(task_switches) - 1:
            seg_seconds += ack_wait_seconds
        seg_hours = seg_seconds / 3600
        if seg_task in session['session_log']:
            session['session_log'][seg_task]['hours'] = round(
                session['session_log'][seg_task]['hours'] + seg_hours, 2)
            session['session_log'][seg_task]['sessions'] += 1

    # If no task switches recorded, fall back to simple tracking
    if not task_switches:
        elapsed_hours = total_real_elapsed / 3600
        if task_name and task_name in session['session_log']:
            session['session_log'][task_name]['hours'] = round(
                session['session_log'][task_name]['hours'] + elapsed_hours, 2)
            session['session_log'][task_name]['sessions'] += 1

    if is_fun_task:
        session['fun_sessions_completed'] += 1
    else:
        session['work_sessions_completed'] += 1
    save_session(session)

    return ack


def verify_resolution():
    """Verify all items from pending_resolution have been resolved.

    Called after break-end ack. Re-queues a hard-blocker prompt if any due items
    from the pre-ack check are still unresolved (not in completed_ids and not snoozed).
    Clears pending_resolution when done.
    Returns True if all resolved (or no pending items), False if a new prompt was queued.
    """
    session = load_session()
    pending = set(session.get('pending_resolution', []))
    if not pending:
        return True

    due = check_due_items(session)
    still_due = [item for item in due if item['id'] in pending]

    if not still_due:
        session['pending_resolution'] = []
        save_session(session)
        return True

    queue_prompt('break_complete',
        "Some items were not resolved. Do NOT write the ack until all are done."
        + due_items_text(still_due, hard_blocker=True))
    return False


async def break_phase():
    """Run break timer, queue prompt, wait for ack. Returns ack dict."""
    session = load_session()

    # B1: read into local variable first, then clear unconditionally
    break_mins = session.get('next_break_minutes') or BREAK_MINUTES
    session['next_break_minutes'] = None
    save_session(session)

    print(f"BREAK phase started ({break_mins} min)")
    await countdown(break_mins, "BREAK")  # return value unused for breaks
    notify("Pomodoro", "Break complete!")

    process_extensions()
    session = load_session()
    due = check_due_items(session)

    # Record items for post-ack verification
    session['pending_resolution'] = [item['id'] for item in due]
    save_session(session)

    prompt = BREAK_COMPLETE_PROMPT + due_items_text(due)
    queue_prompt('break_complete', prompt)
    print("BREAK phase complete")

    ack = await wait_for_ack()

    # Handle extend: run more break time, then wait for ack again
    if ack["action"] == "extend":
        session = load_session()
        # B1: read first, then clear unconditionally
        extend_mins = session.get('next_break_minutes') or BREAK_MINUTES
        session['next_break_minutes'] = None
        save_session(session)
        print(f"  Extending break by {extend_mins} min")
        notify("Pomodoro", f"Break extended by {extend_mins} min")
        await countdown(extend_mins, "BREAK EXTENDED")
        notify("Pomodoro", "Break extension complete!")
        queue_prompt('break_complete',
            "Break extension complete. "
            "Write 'continue:Task Name' or 'end' to ~/.claude/productivity/acknowledged.txt using Write tool. "
            "Task name must exactly match a task in tasks.yaml.")
        ack = await wait_for_ack()

    # Verify pending items were resolved; re-queue if any still due
    while ack["action"] != "end" and not verify_resolution():
        ack = await wait_for_ack()

    return ack


# === MAIN ===

async def async_main():
    if not shutil.which('notify-send'):
        print("Error: notify-send not found.")
        print("Install libnotify (e.g., 'pacman -S libnotify' on Arch)")
        return

    # Clear any stale queue entries from a previous session
    clear_queue()

    # Self-heal: assign IDs to any meetings that are missing them
    validate_meetings()

    # Process ack file left by Claude at startup (sets initial task)
    with open(ACK_FILE, 'r') as f:
        content = f.read().strip()
    os.remove(ACK_FILE)
    parsed = parse_ack(content)
    session = load_session()
    session["current_task"] = parsed["task_name"]
    session["current_task_type"] = parsed["task_type"]
    session["last_ack_time"] = datetime.now().isoformat()
    if parsed["task_name"] not in session["session_log"]:
        session["session_log"][parsed["task_name"]] = {"hours": 0, "sessions": 0}
    save_session(session)
    print(f"  Initial task: {parsed['task_name']} ({parsed['task_type']})")

    session = load_session()
    start_time_str = session.get('start_time')
    if not start_time_str or datetime.fromisoformat(start_time_str).date() != datetime.now().date():
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

    # Start meeting monitor as a background task
    monitor_task = asyncio.create_task(meeting_monitor())

    def end_session():
        monitor_task.cancel()
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
            ack = await work_phase(is_fun_task)
            if ack["action"] == "end":
                end_session()
                break

            ack = await break_phase()
            if ack["action"] == "end":
                end_session()
                break
    except (KeyboardInterrupt, asyncio.CancelledError):
        end_session()


def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
