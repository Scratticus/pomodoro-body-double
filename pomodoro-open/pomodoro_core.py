#!/usr/bin/env python3
"""
Pomodoro Core - ALL logic.
Calls adapter for agent-specific behavior: surface_prompt, notify.
"""

import asyncio
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta
import yaml


# Set POMODORO_DEBUG=1 to print "[Sending notification: ...]" lines on every
# notify-send call. Off by default to keep the timer terminal clean. Failures
# always print regardless.
DEBUG = os.environ.get('POMODORO_DEBUG', '').lower() in ('1', 'true', 'yes')


def create_config(base_dir, adapter):
    if base_dir is None:
        base_dir = adapter.base_dir
    return {
        'WORK_MINUTES': 25,
        'BREAK_MINUTES': 5,
        'EXTEND_MINUTES': 10,
        'SUGGEST_END_AFTER_HOURS': 9,
        'SUGGEST_END_AT_HOUR': 17.5,
        'POLL_INTERVAL': 1,
        'MEETING_WARNING_THRESHOLDS': [60, 30, 15, 5],
        
        'SESSION_FILE': os.path.join(base_dir, 'session.yaml'),
        'LOG_FILE': os.path.join(base_dir, 'log.yaml'),
        'TASKS_FILE': os.path.join(base_dir, 'tasks.yaml'),
        'REMINDERS_FILE': os.path.join(base_dir, 'reminders.yaml'),
        'CHORE_TIMERS_FILE': os.path.join(base_dir, 'chore_timers.yaml'),
        'QUEUE_FILE': os.path.join(base_dir, 'prompt_queue.json'),
        'ACK_FILE': os.path.join(base_dir, 'acknowledged.txt'),
        
        'adapter': adapter,
    }


# === PROMPT TEMPLATES ===

SUGGEST_BREAK_TEMPLATE = (
    "Work phase complete. {elapsed:.0f} min worked on {task}. "
    "Remind the user to drink water, stand up and stretch. "
    "Ask if they want to take a break. "
    "Write one of: 'break' (start break), 'extend' (more work), 'end' (end session) "
    "to <ack_file> using <tool_name>."
)

SUGGEST_WORK_TEMPLATE = (
    "Break complete. "
    "Ask the user which task they want to work on next. "
    "Write 'work:Task Name' or 'end' to <ack_file> using <tool_name>. "
    "Task name must exactly match a task in tasks.yaml."
)

END_SESSION_TEMPLATE = (
    "Session duration: {elapsed:.1f} hours. Current time: {now}. "
    "Ask if the user wants to end the session or keep working. "
    "To end: write 'end' to <ack_file> using <tool_name>."
)


class PomodoroCore:
    """All pomodoro logic - calls adapter for agent-specific behavior."""
    
    def __init__(self, config):
        self.config = config
        self.adapter = config['adapter']

    # === DEBUG ===

    def _dbg(self, msg):
        """Print only when POMODORO_DEBUG is set. Used for status chatter that
        clutters the timer terminal in normal operation."""
        if DEBUG:
            print(msg)

    # === NOTIFY ===
    
    def notify(self, title, message):
        """Send notification - calls adapter's notify if available, else default."""
        notify_fn = getattr(self.adapter, 'notify', None)
        if notify_fn:
            try:
                notify_fn(title, message)
            except Exception:
                self._default_notify(title, message)
        else:
            self._default_notify(title, message)

    def _default_notify(self, title, message):
        """Default notification via notify-send. Success print is gated behind
        POMODORO_DEBUG; failures and errors always surface."""
        if DEBUG:
            print(f"  [Sending notification: {title} - {message}]")
        try:
            result = subprocess.run([
                'notify-send',
                '-h', 'string:sound-name:message-new-instant',
                title, message
            ], capture_output=True)
            if result.returncode != 0:
                print(f"  [Notification failed: {result.stderr.decode().strip()}]")
        except Exception as e:
            print(f"  [Notification error: {e}]")

# === SESSION/LOG ===

    def load_session(self):
        with open(self.config['SESSION_FILE'], 'r') as f:
            return yaml.safe_load(f)

    def save_session(self, session):
        sf = self.config['SESSION_FILE']
        with open(sf + '.tmp', 'w') as f:
            yaml.dump(session, f)
        os.rename(sf + '.tmp', sf)

    def load_log(self):
        with open(self.config['LOG_FILE'], 'r') as f:
            return yaml.safe_load(f) or {'projects': {}}

    def save_log(self, log):
        with open(self.config['LOG_FILE'], 'w') as f:
            yaml.dump(log, f, default_flow_style=False)

    def load_tasks(self):
        with open(self.config['TASKS_FILE'], 'r') as f:
            return yaml.safe_load(f)

    # === HELPERS ===

    def normalize(self, name):
        return re.sub(r'[\s\-\u2013\u2014_]+', '', name.lower())

    def find_task(self, task_name):
        tasks = self.load_tasks()
        norm = self.normalize(task_name)
        for t in tasks.get('work_tasks', []):
            if self.normalize(t['name']) == norm:
                return t['name'], 'work'
        for t in tasks.get('fun_productive', []):
            if self.normalize(t['name']) == norm:
                return t['name'], 'fun'
        return None, None

    def hours_elapsed(self, start):
        if not start:
            return 0
        return (datetime.now() - datetime.fromisoformat(start)).total_seconds() / 3600

    def parse_ts(self, value):
        if isinstance(value, str):
            for fmt in ('%d/%m/%Y %H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f'):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        raise ValueError(f"Can't parse: {value!r}")

    def fmt_ts(self, dt):
        return dt.strftime('%d/%m/%Y %H:%M')

    def ensure_ids(self, items):
        if not items:
            return False
        used = set()
        nid = max((i['id'] for i in items if 'id' in i), default=0) + 1
        changed = False
        for i in items:
            if 'id' not in i or i['id'] in used:
                i['id'] = nid
                nid += 1
                changed = True
            used.add(i['id'])
        return changed

    # === VALIDATION ===

    REMINDER_KNOWN_FIELDS = {'id', 'name', 'time', 'days', 'skip_if_sick', 'end_date'}
    CHORE_KNOWN_FIELDS = {'id', 'name', 'end_time', 'duration_minutes'}
    MEETING_KNOWN_FIELDS = {'id', 'name', 'start_time', 'duration_minutes', 'task'}

    def check_unknown_fields(self, item, known_fields, source):
        """Queue error prompt if unknown fields found."""
        unexpected = {k for k in item if k not in known_fields}
        if not unexpected:
            return True
        self.adapter.surface_prompt('error',
            f"Entry in {source} has unexpected fields: {sorted(unexpected)}. "
            f"Full entry: {dict(item)}. "
            f"Expected fields: {sorted(known_fields)}. "
            f"Rename any mismatched keys in {source} to match the expected format. "
            f"Notify briefly what was changed. Only ask the user if the correct mapping is genuinely unclear.")
        return False

    # === ACK ===

    def parse_ack(self, content):
        """Parse ack content with full error handling.

        New vocabulary (Step 5):
            work:Task Name  - start/switch to a work phase on Task
            break           - start a break phase
            extend          - extend the current phase
            end             - end the session

        Pure: returns parsed dict or None on error. No side effects on session state.
        Callers route the result based on context (mid-phase task switch, phase
        transition, etc.). The legacy 'continue' tokens are explicitly rejected
        with a vocabulary-update prompt.
        """
        if content == "end":
            return {"action": "end"}
        if content == "break":
            return {"action": "break"}
        if content == "extend":
            return {"action": "extend"}

        # Reject legacy 'continue' / 'continue:Task' explicitly.
        if content == "continue" or content.startswith("continue:"):
            self._dbg(f"REJECTED legacy ack: {content}")
            self.adapter.surface_prompt('error',
                f"Received legacy ack '{content}'. The vocabulary has changed: "
                f"use 'work:Task Name' to start/switch a work phase, 'break' to start a break, "
                f"'extend' to extend the current phase, or 'end' to end the session. "
                f"Re-write <ack_file> with the correct token using <tool_name>.")
            return None

        parts = content.split(":", 1)
        if len(parts) != 2 or not parts[1].strip():
            self._dbg(f"MALFORMED ack: {content}")
            self.adapter.surface_prompt('error',
                f"Malformed ack received: '{content}'. Expected one of: 'work:Task Name', "
                f"'break', 'extend', or 'end'. Check the format and re-write <ack_file> using <tool_name>.")
            return None

        if parts[0] != "work":
            self._dbg(f"UNKNOWN action: {parts[0]}")
            self.adapter.surface_prompt('error',
                f"Unknown ack action '{parts[0]}' in '{content}'. The only prefixed action is "
                f"'work:Task Name'. Other valid acks are 'break', 'extend', and 'end'. "
                f"Re-write <ack_file> using <tool_name>.")
            return None

        raw_name = parts[1]
        task_name, task_type = self.find_task(raw_name)

        if task_type is None:
            tasks = self.load_tasks()
            work_names = [t['name'] for t in tasks.get('work_tasks', [])]
            fun_names = [t['name'] for t in tasks.get('fun_productive', [])]
            existing = ', '.join(work_names + fun_names)
            self._dbg(f"UNKNOWN task: {raw_name}")
            self.adapter.surface_prompt('error',
                f"Task '{raw_name}' is not in tasks.yaml. Existing tasks: [{existing}]. "
                f"Check if this is a typo or name mismatch. If it's a genuinely new task, "
                f"add it to tasks.yaml under the correct category. Confirm with the user, "
                f"then re-write <ack_file> using <tool_name>.")
            return None

        log = self.load_log()
        if task_name not in log['projects']:
            existing = ', '.join(log['projects'].keys())
            self._dbg(f"MISSING from log: {task_name}")
            self.adapter.surface_prompt('error',
                f"Task '{task_name}' is not in log.yaml. Existing projects: [{existing}]. "
                f"Check if this is a typo or name mismatch. If it's a genuinely new task, "
                f"add it to log.yaml with zeroed values. Confirm with the user, "
                f"then re-write <ack_file> using <tool_name>.")
            return None

        return {"action": "work", "task_name": task_name, "task_type": task_type}

    REMINDER_INTERVAL_DEFAULT = 300

    async def wait_for_ack(self):
        """Block until ack appears, with periodic reminder notifications.

        Used only for session_start in the new design (Step 5) — work/break phases
        do their own ack polling inside countdown. Session_start has no timer to
        auto-extend, so the auto-extend-on-overdue block from the old version is gone.
        """
        af = self.config['ACK_FILE']
        last_reminder_time = asyncio.get_event_loop().time()

        while True:
            now = asyncio.get_event_loop().time()
            session = self.load_session()
            reminder_enabled = session.get('reminder_enabled', True)
            reminder_interval = session.get('reminder_interval_minutes', self.REMINDER_INTERVAL_DEFAULT / 60) * 60
            if reminder_enabled and now - last_reminder_time >= reminder_interval:
                self.notify("Pomodoro", "Still waiting for you to start a session!")
                last_reminder_time = now

            if os.path.exists(af) and os.path.getsize(af) > 0:
                with open(af, 'r') as f:
                    content = f.read().strip()
                os.remove(af)
                parsed = self.parse_ack(content)

                if parsed is None:
                    self._dbg("Waiting for corrected ack...")
                    continue

                session = self.load_session()
                session["last_ack_time"] = datetime.now().isoformat()
                # Step 3a: preserve extend_minutes through 'extend' acks.
                if parsed["action"] != "extend":
                    session["extend_minutes"] = None

                if "task_name" in parsed:
                    session["current_task"] = parsed["task_name"]
                    session["current_task_type"] = parsed["task_type"]
                    if parsed["task_name"] not in session["session_log"]:
                        session["session_log"][parsed["task_name"]] = {"hours": 0, "sessions": 0}
                    self.save_session(session)
                    self._dbg(f"Ack: {parsed['task_name']}")
                else:
                    self.save_session(session)
                    self._dbg(f"Ack: {parsed['action']}")

                # Apply meeting-aware durations
                session = self.load_session()
                self.apply_meeting_aware_durations(session)

                return parsed
            await asyncio.sleep(self.config['POLL_INTERVAL'])

    # === CHORES/REMINDERS ===

    def load_reminders(self):
        rf = self.config['REMINDERS_FILE']
        if not os.path.exists(rf):
            return []
        with open(rf, 'r') as f:
            data = yaml.safe_load(f)
        reminders = data.get('static_reminders') or []
        if self.ensure_ids(reminders):
            self.save_reminders(reminders)
        return [r for r in reminders
                if self.check_unknown_fields(r, self.REMINDER_KNOWN_FIELDS, 'reminders.yaml')]

    def save_reminders(self, reminders):
        with open(self.config['REMINDERS_FILE'] + '.tmp', 'w') as f:
            yaml.dump({'static_reminders': reminders}, f, default_flow_style=False)
        os.rename(self.config['REMINDERS_FILE'] + '.tmp', self.config['REMINDERS_FILE'])

    def cleanup_expired_reminders(self):
        """Drop reminders whose end_date + time is more than 30 min past. Silent."""
        now = datetime.now()

        def reminder_due_dt(r):
            h, m = r['time'].split(':')
            base = datetime.strptime(str(r['end_date']), '%d/%m/%Y')
            return base.replace(hour=int(h), minute=int(m), second=0, microsecond=0)

        reminders = self.load_reminders()
        expired = [r for r in reminders if r.get('end_date') and
                   (now - reminder_due_dt(r)).total_seconds() > 1800]
        if expired:
            active = [r for r in reminders if r not in expired]
            self.save_reminders(active)
            self._dbg(f"  Removed {len(expired)} expired reminder(s).")

    def load_chores(self):
        cf = self.config['CHORE_TIMERS_FILE']
        if not os.path.exists(cf):
            return []
        with open(cf, 'r') as f:
            data = yaml.safe_load(f) or {}
        timers = data.get('chore_timers') or []
        changed = self.ensure_ids(timers)
        valid = []
        for c in timers:
            if not self.check_unknown_fields(c, self.CHORE_KNOWN_FIELDS, 'chore_timers.yaml'):
                continue
            if 'duration_minutes' in c:
                c['end_time'] = (datetime.now() + timedelta(minutes=c['duration_minutes'])).isoformat()
                del c['duration_minutes']
                changed = True
            elif 'end_time' not in c:
                self.adapter.surface_prompt('error',
                    f"Chore '{c.get('name', '?')}' (id={c.get('id', '?')}) has no end_time or duration_minutes. "
                    f"Ask the user how long it takes and write duration_minutes: N to the chore entry "
                    f"in <chore_timers_file>.")
                continue
            valid.append(c)
        if changed:
            self.save_chores(timers)
        return valid

    def save_chores(self, timers):
        with open(self.config['CHORE_TIMERS_FILE'] + '.tmp', 'w') as f:
            yaml.dump({'chore_timers': timers}, f, default_flow_style=False)
        os.rename(self.config['CHORE_TIMERS_FILE'] + '.tmp', self.config['CHORE_TIMERS_FILE'])

    def clean_chores(self, done=None):
        if done is None:
            done = set()
        cutoff = datetime.now() - timedelta(hours=1)
        timers = [c for c in self.load_chores() if c.get('id') not in done]
        try:
            timers = [c for c in timers if self.parse_ts(c['end_time']) >= cutoff]
        except ValueError:
            pass
        self.save_chores(timers)

    def check_due(self):
        """Check for due chores and reminders."""
        session = self.load_session()
        done = set(session.get('completed_ids', []))
        ext = session.get('extensions', {})
        now = datetime.now()
        due = []

        for c in self.load_chores():
            key = f"chore:{c['id']}"
            if key in done:
                continue
            try:
                if now >= self.parse_ts(c['end_time']):
                    due.append({'id': key, 'name': c['name'], 'type': 'chore'})
            except ValueError:
                pass

        today = now.strftime('%a').lower()[:3]
        for r in self.load_reminders():
            key = f"reminder:{r['id']}"
            if key in done:
                continue
            snooze = ext.get(key, {})
            if 'until' in snooze:
                try:
                    if now < self.parse_ts(snooze['until']):
                        continue
                except ValueError:
                    pass
            days = r.get('days', 'daily')
            if days != 'daily' and today not in days:
                continue
            h, m = r['time'].split(':')
            due_at = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
            if now >= due_at:
                due.append({'id': key, 'name': r['name'], 'type': 'reminder'})

        return due

    def due_text(self, due_items, hard=True):
        """Build prompt snippet for due items."""
        if not due_items:
            return ""
        lines = []
        for item in due_items:
            iid = item['id']
            name = item['name']
            if hard:
                lines.append(
                    f"  - {item['type'].capitalize()} '{name}' (id={iid}): "
                    f"HARD BLOCKER — do NOT write any ack or allow the session to proceed. "
                    f"Ask the user to resolve this. "
                    f"If done: add '{iid}' to completed_ids in <session_file>. "
                    f"If more time needed: add {iid}: {{delay: <minutes>}} "
                    f"under extensions in <session_file>."
                )
            else:
                lines.append(
                    f"  - {item['type'].capitalize()} '{name}' (id={iid}) is due. "
                    f"Mention it to the user; it becomes a hard blocker at break end."
                )
        header = "\n\nDue items - resolve before continuing:\n" if hard else "\n\nFYI - due items (non-blocking):\n"
        return header + "\n".join(lines)

    # === EXTENSIONS ===

    def process_extensions(self):
        """Process pending extension requests."""
        session = self.load_session()
        extensions = session.get('extensions', {})
        if not extensions:
            return
        chores = {c['id']: c for c in self.load_chores()}
        reminder_ids = {r['id'] for r in self.load_reminders()}
        updated = {}
        chores_changed = False
        now = datetime.now()
        
        for item_id, attrs in extensions.items():
            if 'until' in attrs:
                updated[item_id] = attrs
                continue
            delay = attrs.get('delay')
            if delay is None:
                self.adapter.surface_prompt('error',
                    f"Extension '{item_id}' in session.yaml has no 'delay' field. "
                    f"Expected {{delay: <minutes>}}. Correct it in <session_file>.")
                continue
            try:
                item_type, int_id_str = item_id.split(':', 1)
                int_id = int(int_id_str)
            except (ValueError, AttributeError):
                self.adapter.surface_prompt('error',
                    f"Extension key '{item_id}' is not a valid prefixed id (e.g. 'chore:1'). "
                    f"Correct it in <session_file>.")
                continue

            if isinstance(delay, int):
                until_dt = now + timedelta(minutes=delay)
            else:
                try:
                    until_dt = self.parse_ts(str(delay))
                    if until_dt <= now:
                        self.adapter.surface_prompt('error',
                            f"Extension for {item_id} has a timestamp in the past: '{delay}'. "
                            f"Confirm the correct time with the user and rewrite the entry in <session_file>.")
                        continue
                except ValueError:
                    self.adapter.surface_prompt('error',
                        f"Extension for {item_id} has an unrecognised delay format: '{delay}'. "
                        f"Use an integer number of minutes (e.g. {{delay: 30}}).")
                    continue

            until_str = self.fmt_ts(until_dt)
            if item_type == 'chore':
                if int_id in chores:
                    chores[int_id]['end_time'] = until_str
                    chores_changed = True
                else:
                    self.adapter.surface_prompt('error', f"Extension '{item_id}' not found in chore_timers.yaml.")
            elif item_type == 'reminder':
                if int_id in reminder_ids:
                    updated[item_id] = {'until': until_str}
                else:
                    self.adapter.surface_prompt('error', f"Extension '{item_id}' not found in reminders.yaml.")
            else:
                self.adapter.surface_prompt('error',
                    f"Unrecognised type in extension key '{item_id}'. Expected 'chore:N' or 'reminder:N'.")
        
        if chores_changed:
            self.save_chores(list(chores.values()))
        session['extensions'] = updated
        self.save_session(session)

    # === MEETINGS ===

    def validate_meetings(self):
        """Validate meetings, generate reminders, check fields."""
        session = self.load_session()
        meets = session.get('meetings', [])
        if not meets:
            return
        self.ensure_ids(meets)
        existing = {r['id']: r for r in session.get('meeting_reminders', [])}
        for m in meets:
            if not self.check_unknown_fields(m, self.MEETING_KNOWN_FIELDS, 'session.yaml (meetings)'):
                continue
            errors = []
            if 'start_time' not in m:
                errors.append("start_time")
            if 'duration_minutes' not in m:
                errors.append("duration_minutes")
            if 'task' not in m:
                errors.append("task")
            if errors:
                self.adapter.surface_prompt('error',
                    f"Meeting '{m.get('name', '?')}' (id={m['id']}) is missing: "
                    f"{', '.join(errors)}. Add the missing fields to the meeting entry in <session_file>.")
                continue
            for mins in self.config['MEETING_WARNING_THRESHOLDS']:
                try:
                    start = self.parse_ts(m['start_time'])
                except ValueError:
                    continue
                due = start - timedelta(minutes=mins)
                rid = f"mtgrem:{m['id']}:{mins}"
                existing[rid] = {'id': rid, 'meeting_id': m['id'], 'name': m['name'], 'due_at': self.fmt_ts(due)}
        session['meetings'] = meets
        session['meeting_reminders'] = list(existing.values())
        self.save_session(session)

    def check_meeting(self):
        """Check if meeting starts within 30 min."""
        session = self.load_session()
        now = datetime.now()
        done = set(session.get('completed_ids', []))
        for m in session.get('meetings', []):
            if 'id' not in m or f"meeting:{m['id']}" in done:
                continue
            try:
                start = self.parse_ts(m['start_time'])
            except ValueError:
                continue
            mins = (start - now).total_seconds() / 60
            if 0 < mins <= 30:
                return m['id'], m['name'], mins
        return None

    def should_end(self, session):
        """Check if should suggest ending."""
        if self.hours_elapsed(session.get('start_time')) >= session.get('suggest_end_after_hours', self.config['SUGGEST_END_AFTER_HOURS']):
            return True
        now = datetime.now()
        if now.hour + now.minute/60 >= session.get('suggest_end_at_hour', self.config['SUGGEST_END_AT_HOUR']):
            return True
        return False

    def apply_meeting_aware_durations(self, session):
        """Adjust durations based on upcoming meetings."""
        now = datetime.now()
        min_mins = float('inf')
        done = set(session.get('completed_ids', []))
        for m in session.get('meetings', []):
            if 'id' not in m or f"meeting:{m['id']}" in done:
                continue
            try:
                start = self.parse_ts(m['start_time'])
            except ValueError:
                continue
            mins = (start - now).total_seconds() / 60
            if 0 < mins < min_mins:
                min_mins = mins

        if min_mins == float('inf'):
            return

        one_cycle = self.config['WORK_MINUTES'] + self.config['BREAK_MINUTES']
        two_cycles = 2 * one_cycle

        if min_mins <= self.config['BREAK_MINUTES'] + 5:
            if not session.get('next_break_minutes'):
                session['next_break_minutes'] = max(1, int(min_mins))
        elif min_mins <= one_cycle:
            if not session.get('next_work_minutes'):
                session['next_work_minutes'] = max(5, int(min_mins - self.config['BREAK_MINUTES']))
        elif min_mins <= two_cycles:
            if not session.get('next_work_minutes'):
                session['next_work_minutes'] = max(5, int((min_mins - self.config['BREAK_MINUTES']) / 2))

        self.save_session(session)

    def git_tasks(self, session_log):
        tasks = self.load_tasks()
        all_t = tasks.get('work_tasks', []) + tasks.get('fun_productive', [])
        return {t['name']: t.get('has_git', False) for t in all_t if t['name'] in session_log}

    def _snooze_expired(self, until_str, now):
        try:
            return now >= self.parse_ts(until_str)
        except ValueError:
            return True

    # === TIMER ===

    async def countdown(self, minutes, label, exit_actions=frozenset()):
        """Run a countdown timer with mid-timer ack file polling and session-yaml
        polling for overrides / extensions / task switches.

        Per-iteration (~1 s):
          - Ack file: read + remove if present. Dispatch via parse_ack (Step 5):
              * extend       - read session.extend_minutes (or EXTEND_MINUTES default),
                               add to remain + total, clear extend_minutes (Step 3b),
                               continue countdown.
              * work:Task    - if 'work' is in exit_actions (break-end calling),
                               exit early so the caller can transition to a work phase.
                               Otherwise, route through session.task_switch — the
                               existing session-poll handler below will apply on the
                               next 10 s tick.
              * break / end  - if in exit_actions, exit early.
              * unparsable   - parse_ack queues an error prompt; continue.

        Per ten iterations (~10 s):
          - timer_override_minutes: clamp / reset remaining time. Cleared after use.
          - extend_minutes: add to remain + total. Cleared after use (Step 3b).
            (Mirrors the ack-dispatch path for users who edit session.yaml directly.)
          - task_switch: log the elapsed segment on the old task and switch.

        Returns dict with elapsed_seconds, task_switches, early_ack
        (early_ack is None when the timer expires normally; populated when an
        action in exit_actions arrives mid-timer).
        """
        remain = int(minutes * 60)
        total = remain
        check = 10
        count = 0
        switches = []
        switch_start = 0
        af = self.config['ACK_FILE']

        while remain > 0:
            m, s = divmod(remain, 60)
            print(f"\r{label} {m:02d}:{s:02d}", end="", flush=True)

            # === ACK FILE POLL (every ~1 s) ===
            # Ordered before the session-poll so 'extend' ack consumes extend_minutes
            # deterministically when both an ack and a YAML edit arrive in the same window.
            if os.path.exists(af) and os.path.getsize(af) > 0:
                try:
                    with open(af, 'r') as f:
                        content = f.read().strip()
                    os.remove(af)
                    parsed = self.parse_ack(content)
                    if parsed is None:
                        # parse_ack queued an error prompt; keep counting and wait for retry.
                        pass
                    elif parsed['action'] == 'extend':
                        session = self.load_session()
                        ext = session.get('extend_minutes') or self.config['EXTEND_MINUTES']
                        remain += int(ext * 60)
                        total += int(ext * 60)
                        session['extend_minutes'] = None  # clear-on-use (Step 3b)
                        session['last_ack_time'] = datetime.now().isoformat()
                        self.save_session(session)
                        self._dbg(f" +{int(ext)}m")
                        self.notify("Pomodoro", f"Phase extended by {int(ext)} min")
                    elif parsed['action'] in exit_actions:
                        # Phase-changing ack — log the trailing segment and return.
                        elapsed_seg = (total - remain) - switch_start
                        if elapsed_seg > 0:
                            session = self.load_session()
                            switches.append({'task_name': session.get('current_task', 'Unknown'),
                                             'seconds': elapsed_seg})
                        session = self.load_session()
                        session['last_ack_time'] = datetime.now().isoformat()
                        # Clear extend_minutes on non-extend transitions (Step 3a invariant).
                        session['extend_minutes'] = None
                        self.save_session(session)
                        # Newline so the freeze of the timer line is clean before the next phase prints.
                        print()
                        return {'elapsed_seconds': total - remain, 'task_switches': switches,
                                'early_ack': parsed}
                    elif parsed['action'] == 'work':
                        # Mid-phase task switch (work:Task arrived during work phase).
                        # Route through session.task_switch — the existing handler below
                        # will log time + apply the switch on its next 10 s tick.
                        session = self.load_session()
                        if parsed['task_name'] != session.get('current_task'):
                            session['task_switch'] = parsed['task_name']
                            session['last_ack_time'] = datetime.now().isoformat()
                            self.save_session(session)
                    elif parsed['action'] == 'break':
                        # 'break' arrived during a break phase (not in exit_actions). No-op.
                        pass
                except Exception as e:
                    self._dbg(f"\n  Ack-poll error: {e}")

            await asyncio.sleep(1)
            remain -= 1
            count += 1
            if count >= check:
                count = 0
                try:
                    session = self.load_session()
                    override = session.get('timer_override_minutes')
                    if override is not None:
                        remain = int(override * 60)
                        if remain == 0:
                            self._dbg("Ended early")
                            self.notify("Pomodoro", "Phase ended early")
                        else:
                            self._dbg(f"Timer override: {remain//60}m")
                            self.notify("Pomodoro", f"Timer adjusted to {remain//60} min")
                        session['timer_override_minutes'] = None
                        self.save_session(session)

                    ext = session.get('extend_minutes')
                    if ext and ext > 0:
                        remain += int(ext * 60)
                        total += int(ext * 60)
                        self._dbg(f"Extended +{int(ext)}m")
                        self.notify("Pomodoro", f"Phase extended by {int(ext)} min")
                        session['extend_minutes'] = None
                        self.save_session(session)

                    switch = session.get('task_switch')
                    if switch:
                        elapsed = (total - remain) - switch_start
                        old = session.get('current_task', 'Unknown')
                        switches.append({'task_name': old, 'seconds': elapsed})
                        new, ttype = self.find_task(switch)
                        if new:
                            session['current_task'] = new
                            session['current_task_type'] = ttype
                            if new not in session.get('session_log', {}):
                                session['session_log'][new] = {"hours": 0, "sessions": 0}
                            # Print new task name on its own line. The frozen timer
                            # line above shows when the switch happened; the next
                            # countdown tick overwrites a fresh line below the header.
                            print(f"\n{new}")
                            self.notify("Pomodoro", f"Switched to {new}")
                        else:
                            print(f"\nSwitch failed: {switch}")
                            self.adapter.surface_prompt('error',
                                f"Task switch failed: '{switch}' not in tasks.yaml. Check the name and try again.")
                        session['task_switch'] = None
                        switch_start = total - remain
                        self.save_session(session)
                except Exception:
                    pass

        print(f"\r{label} 00:00")
        elapsed = (total - remain) - switch_start
        if elapsed > 0:
            session = self.load_session()
            switches.append({'task_name': session.get('current_task', 'Unknown'), 'seconds': elapsed})
        return {'elapsed_seconds': total, 'task_switches': switches, 'early_ack': None}

    # === WORK ===

    async def work_phase(self, is_fun=False):
        """Run a work timer, then auto-extend with nudges until 'break' or 'end' arrives.

        Auto-extend loop semantics (Step 5):
          1. Main timer runs. Mid-timer ack handling lives in countdown.
          2. On 'break' or 'end' ack mid-timer: log time and return ack.
          3. On timer expiry without phase-change: notify + queue suggest_break (deduped),
             auto-extend by EXTEND_MINUTES (or session.extend_minutes if user customised),
             repeat. Each cycle re-queues suggest_break only if no undelivered one exists.
        """
        # Apply meeting-aware durations now that the new phase is starting.
        session = self.load_session()
        self.apply_meeting_aware_durations(session)
        session = self.load_session()
        started = session.get('last_ack_time') or datetime.now().isoformat()
        task = session.get('current_task')

        mins = session.get('next_work_minutes') or self.config['WORK_MINUTES']
        session['next_work_minutes'] = None
        self.save_session(session)

        # Task header (one-time, replaces the old "WORK (Nm)" duration line).
        # Mid-phase task switches print their own header from countdown's task_switch handler.
        print(task or 'Unknown')
        self._dbg(f"WORK ({mins}m)")

        # Main work timer. Exits early on 'break' or 'end' ack mid-timer.
        result = await self.countdown(mins, "WORK", exit_actions={'break', 'end'})

        all_switches = list(result.get('task_switches', []))
        timer_seconds = result.get('elapsed_seconds', 0)

        if result.get('early_ack') is not None:
            ack = result['early_ack']
            self._log_work_segment(started, timer_seconds, all_switches, task, is_fun)
            return ack

        # Timer expired without phase-change. Process any pending extensions
        # (chore/reminder delays) and enter the symmetric auto-extend loop.
        self.notify("Pomodoro", "Work session complete!")
        self.process_extensions()

        while True:
            # Queue suggest_break (deduped — only if no undelivered one already in queue).
            if not self.adapter.has_undelivered('suggest_break'):
                session = self.load_session()
                current_task = session.get('current_task') or task or 'Unknown'
                elapsed_min = timer_seconds / 60
                prompt = SUGGEST_BREAK_TEMPLATE.format(elapsed=elapsed_min, task=current_task)
                prompt += self.due_text(self.check_due(), hard=False)

                meeting = self.check_meeting()
                break_mins = session.get('next_break_minutes') or self.config['BREAK_MINUTES']
                if meeting:
                    _, name, away = meeting
                    ext = int(away - break_mins)
                    if ext > 0:
                        prompt += (f"\n\nMeeting '{name}' starts in {int(away)} minutes. "
                                   f"Suggest extending work by {ext} min for a "
                                   f"{break_mins}-min break before it.")
                        self.notify("Pomodoro", f"Meeting '{name}' in {int(away)} min!")

                if self.should_end(session) and not self.adapter.has_undelivered('end_session_suggestion'):
                    elapsed_h = self.hours_elapsed(session.get('start_time'))
                    now_str = datetime.now().strftime('%H:%M')
                    git_info = self.git_tasks(session.get('session_log', {}))
                    git_summary = '; '.join(f"{k}: has_git={v}" for k, v in git_info.items())
                    prompt += (f"\n\n{END_SESSION_TEMPLATE.format(elapsed=elapsed_h, now=now_str)}"
                               f" Tasks this session: {git_summary}.")

                self.adapter.surface_prompt('suggest_break', prompt)

            # Auto-extend duration. Step 3b: clear extend_minutes on read.
            session = self.load_session()
            ext_mins = session.get('extend_minutes') or self.config['EXTEND_MINUTES']
            session['extend_minutes'] = None
            self.save_session(session)

            self._dbg(f"+{ext_mins}m work (auto-extend, awaiting break/extend/end)")
            self.notify("Pomodoro", f"Work auto-extended by {ext_mins} min — break/extend/end?")

            ext_result = await self.countdown(
                ext_mins,
                "WORK",
                exit_actions={'break', 'end'},
            )

            all_switches.extend(ext_result.get('task_switches', []))
            timer_seconds += ext_result.get('elapsed_seconds', 0)

            if ext_result.get('early_ack') is not None:
                ack = ext_result['early_ack']
                self._log_work_segment(started, timer_seconds, all_switches, task, is_fun)
                return ack
            # Timer expired again without ack — loop, re-queue (deduped) and auto-extend.

    def _log_work_segment(self, started, timer_seconds, switches, fallback_task, is_fun):
        """Allocate elapsed wall-clock time to per-task hours in session_log.

        Wall-clock = timer + ack-wait. The trailing wait gets attributed to the
        last segment (whichever task was active when the ack arrived).
        """
        session = self.load_session()
        total = (datetime.now() - datetime.fromisoformat(started)).total_seconds()
        wait = max(0, total - timer_seconds)

        for i, seg in enumerate(switches):
            hrs = (seg['seconds'] + (wait if i == len(switches) - 1 else 0)) / 3600
            if seg['task_name'] in session['session_log']:
                session['session_log'][seg['task_name']]['hours'] = round(
                    session['session_log'][seg['task_name']]['hours'] + hrs, 2)
                session['session_log'][seg['task_name']]['sessions'] += 1

        if not switches:
            hrs = total / 3600
            if fallback_task in session['session_log']:
                session['session_log'][fallback_task]['hours'] = round(
                    session['session_log'][fallback_task]['hours'] + hrs, 2)
                session['session_log'][fallback_task]['sessions'] += 1

        if is_fun:
            session['fun_sessions_completed'] += 1
        else:
            session['work_sessions_completed'] += 1
        self.save_session(session)

    # === BREAK ===

    async def break_phase(self):
        """Run a break timer, then auto-extend with nudges until 'work:Task' or 'end' arrives.

        Symmetric mirror of work_phase. _verify_resolution gates the 'work:Task' exit
        when pending due items remain unresolved — in that case we re-queue (deduped)
        and continue the auto-extend loop until items resolve.
        """
        # Apply meeting-aware durations now that the new phase is starting.
        session = self.load_session()
        self.apply_meeting_aware_durations(session)
        session = self.load_session()

        mins = session.get('next_break_minutes') or self.config['BREAK_MINUTES']
        session['next_break_minutes'] = None
        self.save_session(session)

        self._dbg(f"BREAK ({mins}m)")

        # Main break timer. Exits early on 'work' or 'end' ack.
        result = await self.countdown(mins, "BREAK", exit_actions={'work', 'end'})

        if result.get('early_ack') is not None:
            ack = result['early_ack']
            if ack.get('action') == 'work':
                # pending_resolution is empty here (set after timer expires), so
                # verify is a trivial pass.
                self._apply_task_transition(ack)
            return ack

        # Timer expired. Snapshot due items into pending_resolution and enter the
        # symmetric auto-extend loop.
        self.notify("Pomodoro", "Break complete!")
        self.process_extensions()
        session = self.load_session()
        due = self.check_due()
        session['pending_resolution'] = [item['id'] for item in due]
        self.save_session(session)

        while True:
            # Queue suggest_work (deduped). Re-evaluates due_text each cycle so
            # newly-due items show up.
            if not self.adapter.has_undelivered('suggest_work'):
                current_due = self.check_due()
                prompt = SUGGEST_WORK_TEMPLATE + self.due_text(current_due, hard=True)
                self.adapter.surface_prompt('suggest_work', prompt)

            session = self.load_session()
            ext_mins = session.get('extend_minutes') or self.config['EXTEND_MINUTES']
            session['extend_minutes'] = None  # Step 3b
            self.save_session(session)

            self._dbg(f"+{ext_mins}m break (auto-extend, awaiting work/end)")
            self.notify("Pomodoro", f"Break auto-extended by {ext_mins} min — work:Task / end?")

            ext_result = await self.countdown(ext_mins, "BREAK", exit_actions={'work', 'end'})

            if ext_result.get('early_ack') is not None:
                ack = ext_result['early_ack']
                if ack.get('action') == 'work':
                    if not self._verify_resolution():
                        # _verify_resolution queued a hard-blocker re-prompt; swallow
                        # this ack and continue auto-extending until items resolve.
                        continue
                    self._apply_task_transition(ack)
                return ack
            # Timer expired again — loop, re-queue (deduped), auto-extend.

    def _apply_task_transition(self, ack):
        """Apply a 'work:Task' phase transition (called from break_phase on early exit).

        Sets current_task / current_task_type, ensures session_log has an entry,
        clears any stale task_switch field. The work_phase started after this will
        see a clean current_task with no pending switch.
        """
        session = self.load_session()
        session['current_task'] = ack['task_name']
        session['current_task_type'] = ack['task_type']
        session['task_switch'] = None  # defensive: clear stale value
        if ack['task_name'] not in session.get('session_log', {}):
            session['session_log'][ack['task_name']] = {'hours': 0, 'sessions': 0}
        session['last_ack_time'] = datetime.now().isoformat()
        self.save_session(session)

    def _verify_resolution(self):
        """Verify pending items are resolved after break end.

        Queues a hard-blocker re-prompt under the 'suggest_work' event type so it
        deduplicates with the regular suggest_work prompt the auto-extend loop emits.
        """
        session = self.load_session()
        pending = set(session.get('pending_resolution', []))
        if not pending:
            return True

        due = self.check_due()
        still_due = [i for i in due if i['id'] in pending]

        if not still_due:
            session['pending_resolution'] = []
            self.save_session(session)
            return True

        self.adapter.surface_prompt('suggest_work',
            "Some items were not resolved. Do NOT post a 'work:Task' ack until all are done."
            + self.due_text(still_due, hard=True))
        return False

    # === SESSION ===

    def reset_session(self):
        """Reset session state."""
        session = self.load_session()
        completed_ids = session.get('completed_ids', [])
        completed_chore_ids = {int(x.split(':')[1]) for x in completed_ids if x.startswith('chore:')}
        self.clean_chores(completed_chore_ids)

        af = self.config['ACK_FILE']
        if os.path.exists(af):
            os.remove(af)

        session = {
            'work_sessions_completed': 0,
            'fun_sessions_completed': 0,
            'current_task': None,
            'current_task_type': None,
            'start_time': None,
            'suggest_end_after_hours': self.config['SUGGEST_END_AFTER_HOURS'],
            'suggest_end_at_hour': self.config['SUGGEST_END_AT_HOUR'],
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
        self.save_session(session)
        # Wipes the prompt queue so nothing stale carries over.
        self.adapter.clear()

    def flush_log(self):
        session = self.load_session()
        log = self.load_log()
        for task, data in session['session_log'].items():
            proj = log['projects'][task]
            proj['total_sessions'] += data['sessions']
            proj['total_hours'] = round(proj['total_hours'] + data['hours'], 2)
        self.save_log(log)

    # === MONITOR ===

    async def meeting_monitor(self):
        session = self.load_session()
        alerted = set(session.get('startup_alerted', []))
        if alerted:
            session['startup_alerted'] = []
            self.save_session(session)
        snapshot = {}

        while True:
            try:
                session = self.load_session()
                now = datetime.now()
                done = set(session.get('completed_ids', []))

                meets = session.get('meetings', [])
                ids = {m['id'] for m in meets if 'id' in m}
                if set(snapshot.keys()) != ids or any(snapshot.get(m['id']) != m.get('start_time') for m in meets if 'id' in m):
                    self.validate_meetings()
                    session = self.load_session()
                    done = set(session.get('completed_ids', []))
                snapshot = {m['id']: m.get('start_time') for m in session.get('meetings', []) if 'id' in m}

                for mr in session.get('meeting_reminders', []):
                    rid = mr['id']
                    if rid in done or rid in alerted:
                        continue
                    try:
                        due = self.parse_ts(mr['due_at'])
                    except ValueError:
                        continue
                    if now >= due:
                        alerted.add(rid)
                        s2 = self.load_session()
                        s2.setdefault('completed_ids', []).append(rid)
                        self.save_session(s2)
                        self.adapter.surface_prompt('meeting_warning',
                            f"Meeting '{mr['name']}' is coming up soon. "
                            f"Inform the user and help them wrap up if needed.")
                        self.notify("Pomodoro", f"Meeting '{mr['name']}' soon!")
                        self._dbg(f"Meeting: {mr['name']}")

                for m in session.get('meetings', []):
                    if 'id' not in m:
                        continue
                    key = f"meeting:{m['id']}"
                    if key in done:
                        continue
                    try:
                        start = self.parse_ts(m['start_time'])
                    except ValueError:
                        continue
                    mins_away = (start - now).total_seconds() / 60
                    if mins_away <= 0:
                        task = m.get('task')
                        dur = m.get('duration_minutes', self.config['WORK_MINUTES'])
                        s2 = self.load_session()
                        s2.setdefault('completed_ids', []).append(key)
                        s2['next_work_minutes'] = dur
                        self.save_session(s2)
                        done.add(key)
                        if task:
                            # Step 5: do not auto-ack. Queue a meeting_starting prompt
                            # and let Claude (with user consent) post 'work:{task}' to ack.
                            self.adapter.surface_prompt('meeting_starting',
                                f"Meeting '{m['name']}' starts now ({dur} min). "
                                f"Ask the user to confirm. Once confirmed, post 'work:{task}' to "
                                f"<ack_file> using <tool_name>. "
                                f"The next work phase will use the meeting duration ({dur} min).")
                            self._dbg(f"Meeting start (awaiting consent): {m['name']}")
                            self.notify("Pomodoro", f"Meeting starting: {m['name']} — confirm with user")
                        else:
                            self.adapter.surface_prompt('error',
                                f"Meeting '{m.get('name', '?')}' started but has no 'task' field. "
                                f"Add task to the meeting entry in <session_file>.")

                for c in self.load_chores():
                    key = f"chore:{c['id']}"
                    if key in done or key in alerted:
                        continue
                    try:
                        if now >= self.parse_ts(c['end_time']):
                            alerted.add(key)
                            self.adapter.surface_prompt('chore',
                                f"Chore '{c['name']}' is now due. "
                                f"Ask the user if it is completed. "
                                f"If completed: add '{key}' to the completed_ids list in <session_file>. "
                                f"If more time needed: add {key}: {{delay: <minutes>}} under extensions "
                                f"in <session_file>.")
                            self.notify("Pomodoro", f"Chore due: {c['name']}")
                            self._dbg(f"Chore: {c['name']}")
                    except ValueError:
                        pass

                today = now.strftime('%a').lower()[:3]
                for r in self.load_reminders():
                    key = f"reminder:{r['id']}"
                    if key in done or key in alerted:
                        continue
                    days = r.get('days', 'daily')
                    if days != 'daily' and today not in days:
                        continue
                    h, m = r['time'].split(':')
                    due = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
                    if now >= due:
                        alerted.add(key)
                        self.adapter.surface_prompt('reminder',
                            f"Reminder '{r['name']}' is now due. "
                            f"Ask the user if they've done it. "
                            f"If done: add '{key}' to the completed_ids list in <session_file>. "
                            f"If deferring: do nothing (fires again next session).")
                        self.notify("Pomodoro", f"Reminder: {r['name']}")
                        self._dbg(f"Reminder: {r['name']}")

                # Clean expired snoozes
                session2 = self.load_session()
                extensions = session2.get('extensions', {})
                expired_keys = [k for k, v in extensions.items() if 'until' in v and self._snooze_expired(v['until'], now)]
                if expired_keys:
                    for k in expired_keys:
                        del extensions[k]
                        alerted.discard(k)
                    session2['extensions'] = extensions
                    self.save_session(session2)

            except Exception as e:
                # Real errors should surface — could indicate a bug worth fixing.
                print(f"Monitor error: {e}")
            await asyncio.sleep(30)

    # === MAIN ===

    async def run_session(self):
        # Precondition: notify-send must be available (Step 2c)
        if not shutil.which('notify-send'):
            print("Error: notify-send not found.")
            print("Install libnotify (e.g., 'pacman -S libnotify' on Arch)")
            return

        # Preserve un-flushed hours from a previous launch before resetting (Step 2a)
        pre = self.load_session()
        if pre.get('session_log'):
            try:
                self.flush_log()
            except (KeyError, FileNotFoundError) as e:
                print(f"  flush_log warning during startup: {e}")

        # Stale-ack-file warning (debug-gated) — announce before reset_session removes it
        af = self.config['ACK_FILE']
        if os.path.exists(af):
            self._dbg("  Cleared stale ack file from previous session.")

        # Standalone startup chore sweep with size-delta print (debug-gated).
        # reset_session calls clean_chores which drops chores >1h past end_time.
        chores_before = len(self.load_chores())
        self.reset_session()
        chores_after = len(self.load_chores())
        if chores_before != chores_after:
            self._dbg(f"  Cleared {chores_before - chores_after} expired chore(s) from previous session.")

        # Expired-reminder sweep (Step 2c)
        self.cleanup_expired_reminders()

        # Explicit validate_meetings self-heal at startup (Step 2c)
        self.validate_meetings()

        # Queue session_start prompt and wait for ack.
        # (Step 2b: dropped the ack-exists branch — reset_session always deletes the ack.)
        tasks = self.load_tasks()
        task_names = (
            [t['name'] for t in tasks.get('work_tasks', [])] +
            [t['name'] for t in tasks.get('fun_productive', [])]
        )
        session = self.load_session()
        due = self.check_due()
        if due:
            session['startup_alerted'] = [item['id'] for item in due]
            self.save_session(session)
        prompt = (
            f"Pomodoro has started but no ack file was found. "
            f"Ask the user what task they're working on. "
            f"Available tasks: [{', '.join(task_names)}]. "
        )
        if due:
            prompt += self.due_text(due, hard=False)
            prompt += "\nHandle the above items in your response before confirming the task. "
        prompt += (
            f"Write 'work:Task Name' to <ack_file> "
            f"using <tool_name> immediately after they confirm -- before reading any task files."
        )
        self.adapter.surface_prompt('session_start', prompt)
        print("Waiting...")
        await self.wait_for_ack()

        # Post-ack: set start_time (Step 2b: the dead continuation check is gone — reset_session always nulled it).
        # suggest_end_after_hours / suggest_end_at_hour are also always set by reset_session, so no fallback needed.
        session = self.load_session()
        session['start_time'] = datetime.now().isoformat()
        self.save_session(session)

        # Note: the task header is printed by work_phase at the start of each phase,
        # so we don't print one here. work_phase will pick up current_task and print it.

        monitor_task = asyncio.create_task(self.meeting_monitor())

        def end_session():
            monitor_task.cancel()
            session = self.load_session()
            elapsed = self.hours_elapsed(session.get('start_time'))
            print(f"Done. {elapsed:.1f}h work:{session['work_sessions_completed']} fun:{session['fun_sessions_completed']}")
            self.flush_log()
            self.reset_session()

        try:
            while True:
                is_fun = self.load_session().get('current_task_type') == 'fun'
                ack = await self.work_phase(is_fun)
                if ack.get("action") == "end":
                    end_session()
                    break

                ack = await self.break_phase()
                if ack.get("action") == "end":
                    end_session()
                    break
        except (KeyboardInterrupt, asyncio.CancelledError):
            end_session()


def run(core):
    asyncio.run(core.run_session())


if __name__ == "__main__":
    import sys
    
    class DefaultAdapter:
        """Default adapter — prints prompts to stdout for manual debugging."""

        def surface_prompt(self, prompt_type, prompt_text):
            print(f"[{prompt_type}] {prompt_text}")

        def has_undelivered(self, prompt_type):
            return False

        def clear(self):
            pass

        def notify(self, title, message):
            try:
                subprocess.run(['notify-send', '-h', 'string:sound-name:message-new-instant', title, message],
                             capture_output=True)
            except Exception:
                pass
    
    base = sys.argv[1] if len(sys.argv) > 1 else None
    if not base:
        print("Usage: python pomodoro_core.py <base_dir>")
        print("Example: /path/to/test_data/")
        sys.exit(1)
    
    adapter = DefaultAdapter()
    config = create_config(base, adapter)
    core = PomodoroCore(config)
    run(core)