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
import shutil
import subprocess
from datetime import datetime
import yaml


def notify(title, message):
    """Send a desktop notification with sound."""
    print(f"  [Sending notification: {title} - {message}]")
    result = subprocess.run(
        ["notify-send", "-h", "string:sound-name:message-new-instant", title, message],
        capture_output=True,
    )
    if result.returncode != 0:
        print(f"  [Notification failed: {result.stderr.decode()}]")


# === CONFIGURATION ===
WORK_MINUTES = 25
BREAK_MINUTES = 5
SUGGEST_END_AFTER_HOURS = 9
SUGGEST_END_AT_HOUR = 17.5
POLL_INTERVAL = 1

# Detect whether we're running under Claude Code or OpenCode
if os.path.exists(os.path.expanduser("~/.opencode")) or os.environ.get("OPENCODE_CLI"):
    CONFIG_DIR = os.path.expanduser("~/.opencode")
else:
    CONFIG_DIR = os.path.expanduser("~/.claude")

SESSION_FILE = os.path.join(CONFIG_DIR, "productivity/session.yaml")
LOG_FILE = os.path.join(CONFIG_DIR, "productivity/log.yaml")
TASKS_FILE = os.path.join(CONFIG_DIR, "productivity/tasks.yaml")
REMINDERS_FILE = os.path.join(CONFIG_DIR, "productivity/reminders.yaml")
QUEUE_FILE = os.path.join(CONFIG_DIR, "productivity/prompt_queue.json")
ACK_FILE = os.path.join(CONFIG_DIR, "productivity/acknowledged.txt")

# === PROMPTS (for Claude to act on) ===
WORK_COMPLETE_PROMPT = (
    "Work session complete. Remind the user to drink water, "
    "stand up and stretch, and check on household chores."
)

BREAK_COMPLETE_PROMPT = (
    "Break complete. Offer the user a choice: continue their "
    "previous work session if any, or try a different task."
)

END_SESSION_PROMPT = (
    "The user has been working for several hours. Gently suggest "
    "they might want to end the session for today. Ask if they'd "
    "like to wrap up, summarise what was accomplished, and save progress."
)


# === QUEUE FUNCTIONS ===


def load_queue():
    """Load the prompt queue from disk."""
    if not os.path.exists(QUEUE_FILE):
        return []
    with open(QUEUE_FILE, "r") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def save_queue(queue):
    """Atomic write of the queue to disk."""
    tmp = QUEUE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(queue, f, indent=2)
    os.rename(tmp, QUEUE_FILE)


def queue_prompt(prompt_type, prompt_text):
    """Append a prompt to the queue."""
    queue = load_queue()
    next_id = max((e["id"] for e in queue), default=0) + 1
    queue.append(
        {
            "id": next_id,
            "timestamp": datetime.now().isoformat(),
            "type": prompt_type,
            "prompt": prompt_text,
            "delivered": False,
        }
    )
    save_queue(queue)
    print(f"  Queued: [{prompt_type}]")


def has_undelivered(prompt_type):
    """Check if there's already an undelivered prompt of this type."""
    queue = load_queue()
    return any(e["type"] == prompt_type and not e["delivered"] for e in queue)


def clear_queue():
    """Clear all entries. Called at session reset."""
    save_queue([])


# === SESSION/LOG FUNCTIONS ===


def load_session():
    with open(SESSION_FILE, "r") as f:
        return yaml.safe_load(f)


def save_session(session):
    with open(SESSION_FILE, "w") as f:
        yaml.dump(session, f)
    os.environ["POMODORO_WORK_SESSIONS"] = str(session["work_sessions_completed"])
    os.environ["POMODORO_FUN_SESSIONS"] = str(session["fun_sessions_completed"])
    os.environ["POMODORO_CURRENT_TASK"] = str(session["current_task"] or "")
    os.environ["POMODORO_TASK_TYPE"] = str(session["current_task_type"] or "")
    os.environ["POMODORO_START_TIME"] = str(session.get("start_time") or "")


def load_log():
    with open(LOG_FILE, "r") as f:
        return yaml.safe_load(f) or {"projects": {}}


def save_log(log):
    with open(LOG_FILE, "w") as f:
        yaml.dump(log, f, default_flow_style=False)


def load_tasks():
    with open(TASKS_FILE, "r") as f:
        return yaml.safe_load(f)


def lookup_task_type(task_name):
    """Look up whether a task is 'work' or 'fun' from tasks.yaml."""
    tasks = load_tasks()
    for task in tasks.get("work_tasks", []):
        if task["name"] == task_name:
            return "work"
    for task in tasks.get("fun_productive", []):
        if task["name"] == task_name:
            return "fun"
    return None


# === ACK FUNCTIONS ===


def parse_ack(content):
    """Parse ack content.

    Formats:
      'continue:task_name' - start next work phase with this task (used after breaks)
      'continue'           - proceed to break (used after work, keeps current task)
      'extend'             - extend work phase (used when meeting is upcoming)
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
        queue_prompt(
            "error",
            f"Malformed ack received: '{content}'. Expected one of: 'continue:Task Name', "
            f"'continue', or 'end'. Check the format and re-write the ack file.",
        )
        return None

    task_name = parts[1]
    task_type = lookup_task_type(task_name)

    if task_type is None:
        tasks = load_tasks()
        work_names = [t["name"] for t in tasks.get("work_tasks", [])]
        fun_names = [t["name"] for t in tasks.get("fun_productive", [])]
        existing = ", ".join(work_names + fun_names)
        print(f"  Error: '{task_name}' not in tasks.yaml.")
        queue_prompt(
            "error",
            f"Task '{task_name}' is not in tasks.yaml. Existing tasks: [{existing}]. "
            f"Check if this is a typo or name mismatch. If it's a genuinely new task, "
            f"add it to tasks.yaml under the correct category. Confirm with the user, "
            f"then re-write the ack file.",
        )
        return None

    log = load_log()
    if task_name not in log["projects"]:
        existing = ", ".join(log["projects"].keys())
        print(f"  Error: '{task_name}' not in log.yaml.")
        queue_prompt(
            "error",
            f"Task '{task_name}' is not in log.yaml. Existing projects: [{existing}]. "
            f"Check if this is a typo or name mismatch. If it's a genuinely new task, "
            f"add it to log.yaml with zeroed values. Confirm with the user, "
            f"then re-write the ack file.",
        )
        return None

    return {"action": parts[0], "task_name": task_name, "task_type": task_type}


async def wait_for_ack():
    """Block until ack file appears, parse content, then clear it."""
    print("  Waiting for check-in...")
    while True:
        if os.path.exists(ACK_FILE) and os.path.getsize(ACK_FILE) > 0:
            with open(ACK_FILE, "r") as f:
                content = f.read().strip()
            os.remove(ACK_FILE)
            parsed = parse_ack(content)

            if parsed is None:
                print("  Waiting for corrected ack...")
                continue

            session = load_session()
            session["last_ack_time"] = datetime.now().isoformat()

            if "task_name" in parsed:
                session["current_task"] = parsed["task_name"]
                session["current_task_type"] = parsed["task_type"]
                if parsed["task_name"] not in session["session_log"]:
                    session["session_log"][parsed["task_name"]] = {
                        "hours": 0,
                        "sessions": 0,
                    }
                save_session(session)
                print(
                    f"  Acknowledged: {parsed['action']} - {parsed['task_name']} ({parsed['task_type']})"
                )
            else:
                save_session(session)
                print(f"  Acknowledged: {parsed['action']}")

            return parsed
        await asyncio.sleep(POLL_INTERVAL)


# === HELPER FUNCTIONS ===


def flush_session_log():
    """Merge session_log into main log.yaml at end of session."""
    session = load_session()
    log = load_log()
    for task_name, data in session["session_log"].items():
        project = log["projects"][task_name]
        project["total_sessions"] += data["sessions"]
        project["total_hours"] = round(project["total_hours"] + data["hours"], 2)
    save_log(log)


def reset_session():
    session = {
        "work_sessions_completed": 0,
        "fun_sessions_completed": 0,
        "current_task": None,
        "current_task_type": None,
        "start_time": None,
        "suggest_end_after_hours": SUGGEST_END_AFTER_HOURS,
        "suggest_end_at_hour": SUGGEST_END_AT_HOUR,
        "chore_timers": [],
        "meetings": [],
        "completed_items": [],
        "session_log": {},
        "last_ack_time": None,
        "next_work_minutes": None,
        "next_break_minutes": None,
        "timer_override_minutes": None,
        "task_switch": None,
    }
    save_session(session)
    clear_queue()


def hours_elapsed(start_time_str):
    if not start_time_str:
        return 0
    start = datetime.fromisoformat(start_time_str)
    return (datetime.now() - start).total_seconds() / 3600


def load_reminders():
    if not os.path.exists(REMINDERS_FILE):
        return []
    with open(REMINDERS_FILE, "r") as f:
        data = yaml.safe_load(f)
    return data.get("static_reminders", [])


def check_due_items(session):
    """Check for due chores and reminders. Returns list of due item names."""
    completed = session.get("completed_items", [])
    now = datetime.now()
    due = []

    for chore in session.get("chore_timers", []):
        if chore["name"] in completed:
            continue
        if now >= datetime.fromisoformat(chore["end_time"]):
            due.append(chore["name"])

    today_day = now.strftime("%a").lower()[:3]
    current_time = now.strftime("%H:%M")
    for reminder in load_reminders():
        if reminder["name"] in completed:
            continue
        days = reminder.get("days", "daily")
        if days != "daily" and today_day not in days:
            continue
        if current_time >= reminder["time"]:
            due.append(reminder["name"])

    return due


def due_items_text(due_items):
    """Build a prompt snippet for due items."""
    if not due_items:
        return ""
    names = ", ".join(due_items)
    return f"\n\nDue items: {names}. Remind the user and ask if they've handled these."


def check_upcoming_meeting(session):
    """Check if a meeting starts within 30 min. Returns (name, mins_away) or None."""
    now = datetime.now()
    for meeting in session.get("meetings", []):
        if meeting["name"] in session.get("completed_items", []):
            continue
        start = datetime.fromisoformat(meeting["start_time"])
        mins_away = (start - now).total_seconds() / 60
        if 0 < mins_away <= 30:
            return meeting["name"], mins_away
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
                # Check for timer override
                override = session.get("timer_override_minutes")
                if override is not None:
                    new_remaining = int(override * 60)
                    old_mins, old_secs = divmod(remaining, 60)
                    new_mins, new_secs = divmod(new_remaining, 60)
                    if new_remaining == 0:
                        print(f"\n  Phase ended early")
                        notify("Pomodoro", "Phase ended early")
                    else:
                        print(
                            f"\n  Timer override: {old_mins:02d}:{old_secs:02d} -> {new_mins:02d}:{new_secs:02d}"
                        )
                        notify("Pomodoro", f"Timer adjusted to {int(override)} min")
                    remaining = new_remaining
                    session["timer_override_minutes"] = None
                    save_session(session)

                # Check for task switch (work phases only)
                switch = session.get("task_switch")
                if switch is not None:
                    elapsed_on_current = (total_seconds - remaining) - switch_started_at
                    old_task = session.get("current_task", "Unknown")
                    task_switches.append(
                        {
                            "task_name": old_task,
                            "seconds_spent": elapsed_on_current,
                        }
                    )
                    new_task_type = lookup_task_type(switch)
                    if new_task_type:
                        session["current_task"] = switch
                        session["current_task_type"] = new_task_type
                        if switch not in session.get("session_log", {}):
                            session["session_log"][switch] = {"hours": 0, "sessions": 0}
                        print(f"\n  Switched: {old_task} -> {switch}")
                        notify("Pomodoro", f"Switched to {switch}")
                        label = f"WORK ({switch})"
                    else:
                        print(f"\n  Task switch failed: '{switch}' not in tasks.yaml")
                        queue_prompt(
                            "error",
                            f"Task switch failed: '{switch}' not in tasks.yaml. "
                            f"Check the name and try again.",
                        )
                    session["task_switch"] = None
                    switch_started_at = total_seconds - remaining
                    save_session(session)
            except Exception:
                pass  # don't crash the timer on a read error
    print(f"\r  {label} 00:00    ")
    # Record time for the final task segment
    elapsed_on_current = (total_seconds - remaining) - switch_started_at
    if elapsed_on_current > 0:
        session = load_session()
        task_switches.append(
            {
                "task_name": session.get("current_task", "Unknown"),
                "seconds_spent": elapsed_on_current,
            }
        )
    return {
        "elapsed_seconds": total_seconds,
        "task_switches": task_switches,
    }


def should_suggest_end(session):
    """Check if we should suggest ending, based on hours worked or clock time."""
    elapsed = hours_elapsed(session.get("start_time"))
    max_hours = session.get("suggest_end_after_hours", SUGGEST_END_AFTER_HOURS)
    end_at_hour = session.get("suggest_end_at_hour", SUGGEST_END_AT_HOUR)

    if elapsed >= max_hours:
        return True
    now = datetime.now()
    current_hour = now.hour + now.minute / 60
    if current_hour >= end_at_hour:
        return True
    return False


# === MEETING MONITOR ===

MEETING_WARNING_THRESHOLDS = [60, 30, 15, 5]  # minutes before meeting


async def meeting_monitor():
    """Async task that checks for upcoming meetings every 30 seconds.
    Queues warning prompts at 60, 30, 15, and 5 minute thresholds."""
    warned = {}  # {meeting_name: set of thresholds already warned}
    while True:
        try:
            session = load_session()
            now = datetime.now()
            completed = session.get("completed_items", [])
            for meeting in session.get("meetings", []):
                name = meeting["name"]
                if name in completed:
                    continue
                start = datetime.fromisoformat(meeting["start_time"])
                mins_away = (start - now).total_seconds() / 60
                if mins_away <= 0:
                    continue
                if name not in warned:
                    warned[name] = set()
                for threshold in sorted(MEETING_WARNING_THRESHOLDS):
                    if mins_away <= threshold and threshold not in warned[name]:
                        warned[name].add(threshold)
                        # Mark all larger thresholds as warned too
                        # (prevents cascade when meeting is already close)
                        for t in MEETING_WARNING_THRESHOLDS:
                            if t >= threshold:
                                warned[name].add(t)
                        queue_prompt(
                            "meeting_warning",
                            f"Meeting '{name}' starts in {int(mins_away)} minutes.",
                        )
                        notify("Pomodoro", f"Meeting '{name}' in {int(mins_away)} min!")
                        print(f"\n  Meeting warning: '{name}' in {int(mins_away)} min")
                        break
        except Exception as e:
            print(f"\n  Meeting monitor error: {e}")
        await asyncio.sleep(30)


# === PHASE FUNCTIONS ===


async def work_phase(is_fun_task=False):
    """Run work timer, queue prompt, wait for ack. Returns ack dict."""
    session = load_session()
    work_started_at = session.get("last_ack_time") or datetime.now().isoformat()
    initial_task = session.get("current_task")

    # Use override duration if set, then clear it
    work_mins = session.get("next_work_minutes") or WORK_MINUTES
    if session.get("next_work_minutes"):
        session["next_work_minutes"] = None
        save_session(session)

    print(f"WORK phase started ({work_mins} min)")
    timer_result = await countdown(work_mins, f"WORK ({initial_task})")
    notify("Pomodoro", "Work session complete!")

    # Build and queue the work complete prompt
    session = load_session()
    task_name = session.get("current_task")
    meeting = check_upcoming_meeting(session)
    upcoming_break_mins = session.get("next_break_minutes") or BREAK_MINUTES

    prompt = WORK_COMPLETE_PROMPT
    prompt += due_items_text(check_due_items(session))

    if meeting:
        name, mins_away = meeting
        extend_mins = int(mins_away - upcoming_break_mins)
        if extend_mins > 0:
            prompt += (
                f"\n\nMeeting '{name}' starts in {int(mins_away)} minutes. "
                f"Ask the user if they want to extend work by {extend_mins} more "
                f"minutes so there's still a {upcoming_break_mins}-min break before it. "
                f"If yes, write 'extend' ack. If no, write 'continue' as normal."
            )
            notify("Pomodoro", f"Meeting '{name}' in {int(mins_away)} min!")
            print(f"  Meeting '{name}' in {int(mins_away)} min")

    if should_suggest_end(session) and not has_undelivered("end_session_suggestion"):
        elapsed = hours_elapsed(session.get("start_time"))
        now = datetime.now().strftime("%H:%M")
        prompt += (
            f"\n\n{END_SESSION_PROMPT}\nSession duration so far: "
            f"{elapsed:.1f} hours. Current time: {now}."
        )

    queue_prompt("work_complete", prompt)
    print("WORK phase complete")

    ack = await wait_for_ack()

    # If user chose to extend for a meeting, run the extension countdown
    if ack["action"] == "extend" and meeting:
        name = meeting[0]
        # Look up the meeting safely
        meetings = load_session().get("meetings", [])
        matching = [m for m in meetings if m["name"] == name]
        if matching:
            mins_away_now = (
                datetime.fromisoformat(matching[0]["start_time"]) - datetime.now()
            ).total_seconds() / 60
            if mins_away_now > upcoming_break_mins:
                extend_mins = int(mins_away_now - upcoming_break_mins)
                print(f"  Extending work by {extend_mins} min for meeting '{name}'")
                await countdown(extend_mins, f"EXTENDED ({name})")
                notify("Pomodoro", "Extended work complete!")
                queue_prompt(
                    "work_complete",
                    "Extended work session complete. Proceeding to break before meeting.",
                )
                ack = await wait_for_ack()
            else:
                print(f"  Meeting '{name}' is too close, skipping extend")

    # Log time per task using countdown's task_switches data
    task_switches = timer_result.get("task_switches", [])
    session = load_session()

    # Also account for any ack wait time (attribute to the last active task)
    started = datetime.fromisoformat(work_started_at)
    total_real_elapsed = (datetime.now() - started).total_seconds()
    timer_elapsed = timer_result.get("elapsed_seconds", 0)
    ack_wait_seconds = max(0, total_real_elapsed - timer_elapsed)

    for i, segment in enumerate(task_switches):
        seg_task = segment["task_name"]
        seg_seconds = segment["seconds_spent"]
        # Add ack wait time to the last segment
        if i == len(task_switches) - 1:
            seg_seconds += ack_wait_seconds
        seg_hours = seg_seconds / 3600
        if seg_task in session["session_log"]:
            session["session_log"][seg_task]["hours"] = round(
                session["session_log"][seg_task]["hours"] + seg_hours, 2
            )
            session["session_log"][seg_task]["sessions"] += 1

    # If no task switches recorded, fall back to simple tracking
    if not task_switches:
        elapsed_hours = total_real_elapsed / 3600
        if task_name and task_name in session["session_log"]:
            session["session_log"][task_name]["hours"] = round(
                session["session_log"][task_name]["hours"] + elapsed_hours, 2
            )
            session["session_log"][task_name]["sessions"] += 1

    if is_fun_task:
        session["fun_sessions_completed"] += 1
    else:
        session["work_sessions_completed"] += 1
    save_session(session)

    return ack


async def break_phase():
    """Run break timer, queue prompt, wait for ack. Returns ack dict."""
    session = load_session()

    # Use override duration if set, then clear it
    break_mins = session.get("next_break_minutes") or BREAK_MINUTES
    if session.get("next_break_minutes"):
        session["next_break_minutes"] = None
        save_session(session)

    print(f"BREAK phase started ({break_mins} min)")
    await countdown(break_mins, "BREAK")  # return value unused for breaks
    notify("Pomodoro", "Break complete!")

    session = load_session()
    due = check_due_items(session)
    prompt = BREAK_COMPLETE_PROMPT + due_items_text(due)
    queue_prompt("break_complete", prompt)
    print("BREAK phase complete")

    return await wait_for_ack()


# === MAIN ===


async def async_main():
    if not shutil.which("notify-send"):
        print("Error: notify-send not found.")
        print("Install libnotify (e.g., 'pacman -S libnotify' on Arch)")
        return

    # Clear any stale queue entries from a previous session
    clear_queue()

    # Process ack file left by OpenCode at startup (sets initial task)
    with open(ACK_FILE, "r") as f:
        content = f.read().strip()
    os.remove(ACK_FILE)
    parsed = parse_ack(content)
    if parsed is None or "task_name" not in parsed:
        print("  Error: Invalid startup ack. Expected format: 'continue:Task Name'")
        return
    session = load_session()
    session["current_task"] = parsed["task_name"]
    session["current_task_type"] = parsed["task_type"]
    session["last_ack_time"] = datetime.now().isoformat()
    if parsed["task_name"] not in session["session_log"]:
        session["session_log"][parsed["task_name"]] = {"hours": 0, "sessions": 0}
    save_session(session)
    print(f"  Initial task: {parsed['task_name']} ({parsed['task_type']})")

    session = load_session()
    if not session.get("start_time"):
        session["start_time"] = datetime.now().isoformat()
    if "suggest_end_after_hours" not in session:
        session["suggest_end_after_hours"] = SUGGEST_END_AFTER_HOURS
    if "suggest_end_at_hour" not in session:
        session["suggest_end_at_hour"] = SUGGEST_END_AT_HOUR
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
        elapsed = hours_elapsed(session.get("start_time"))
        print(f"\nSession ended.")
        print(f"Duration: {elapsed:.1f} hours")
        print(f"Work sessions: {session['work_sessions_completed']}")
        print(f"Fun sessions: {session['fun_sessions_completed']}")
        flush_session_log()
        reset_session()

    try:
        while True:
            is_fun_task = load_session().get("current_task_type") == "fun"
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
