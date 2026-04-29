#!/usr/bin/env python3
"""
Adapter for OpenCode.

Mirrors the contract documented in pomodoro-open/memory.md:
    surface_prompt(type, text)
    has_undelivered(type)
    clear()
    notify(title, message)   [optional]
    base_dir                  [attribute]

Pomodoro side just appends to the queue, identical to ClaudeAdapter. The
OpenCode plugin (separate code, not in this file) reads the queue and dispatches
to its own event surface. Plugin integration markers are TODOs at the bottom.
"""

import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime

import pomodoro_core


class OpenCodeAdapter:
    """Adapter that appends prompts to a queue file for the OpenCode plugin to consume."""

    def __init__(self, base_dir=None):
        self.base_dir = base_dir or os.path.expanduser("~/.claude/productivity")
        self.queue_file = os.path.join(self.base_dir, "prompt_queue.json")
        self.ack_file = os.path.join(self.base_dir, "acknowledged.txt")
        self.session_file = os.path.join(self.base_dir, "session.yaml")
        self.chore_timers_file = os.path.join(self.base_dir, "chore_timers.yaml")

    def _substitute(self, text):
        """Replace agent-specific placeholders. Core uses <ack_file>, <tool_name>,
        <session_file>, <chore_timers_file>. OpenCode's tool name is a placeholder
        until the plugin is built and the actual file-writing tool name is known."""
        return (text
                # TODO: confirm OpenCode's file-writing tool name with the plugin author
                .replace("<tool_name>", "the file-writing tool")
                .replace("<ack_file>", self.ack_file)
                .replace("<session_file>", self.session_file)
                .replace("<chore_timers_file>", self.chore_timers_file))

    def _load_queue(self):
        if not os.path.exists(self.queue_file):
            return []
        with open(self.queue_file, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _save_queue(self, queue):
        tmp = self.queue_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(queue, f, indent=2)
        os.rename(tmp, self.queue_file)

    def _map_to_opencode_events(self, prompt_type):
        """Map prompt type to OpenCode plugin event names (one-to-many).

        Stored on each queue entry under ``hook_events`` for the plugin to filter on.
        Event names are placeholders — verify against the actual OpenCode plugin API
        when the plugin is built. TODO: confirm event names with opencode-hooks-plugin.
        """
        mapping = {
            "session_start": ["session.created"],
            "work_complete": ["tool.execute.after"],
            "break_complete": ["tool.execute.after"],
            "suggest_break": ["tool.execute.after"],
            "suggest_work": ["tool.execute.after"],
            "meeting_starting": ["tool.execute.after", "session.idle"],
            "meeting_warning": ["tool.execute.after", "session.idle"],
            "chore": ["tool.execute.after", "session.idle"],
            "reminder": ["tool.execute.after", "session.idle"],
            "extend_reminder": ["tool.execute.after"],
            "error": ["tool.execute.after", "session.idle"],
        }
        return mapping.get(prompt_type, ["tool.execute.after"])

    def surface_prompt(self, prompt_type, prompt_text):
        """Append a prompt to the queue. Plugin reads + marks delivered later."""
        text = self._substitute(prompt_text)
        queue = self._load_queue()
        nid = max((e["id"] for e in queue), default=0) + 1
        queue.append({
            "id": nid,
            "timestamp": datetime.now().isoformat(),
            "type": prompt_type,
            "prompt": text,
            "delivered": False,
            "hook_events": self._map_to_opencode_events(prompt_type),
        })
        self._save_queue(queue)

    def has_undelivered(self, prompt_type):
        """Return True if any undelivered entry of this type exists in queue."""
        queue = self._load_queue()
        return any(e["type"] == prompt_type and not e.get("delivered") for e in queue)

    def clear(self):
        """Wipe the queue at session reset."""
        self._save_queue([])

    def notify(self, title, message):
        """Desktop notification. Same as Claude default — OpenCode plugin doesn't own
        notification surfaces, so we use notify-send directly."""
        try:
            subprocess.run(
                ["notify-send", "-h", "string:sound-name:message-new-instant", title, message],
                capture_output=True,
            )
        except Exception:
            pass


# === OpenCode plugin integration TODOs ===
#
# The plugin side (NOT in this file) needs to:
#   1. Subscribe to OpenCode events listed in _map_to_opencode_events.
#   2. On event, read prompt_queue.json, find undelivered entries whose
#      hook_events list contains the firing event, surface them to the agent,
#      and mark delivered.
#   3. Watch acknowledged.txt for ack writes from the agent (work:Task, break,
#      extend, end) and pass them through unchanged — pomodoro_core handles them.
#
# Verify event names against the actual OpenCode plugin API before shipping.


def main():
    base_dir = sys.argv[1] if len(sys.argv) > 1 else None
    adapter = OpenCodeAdapter(base_dir)
    config = pomodoro_core.create_config(base_dir, adapter)
    core = pomodoro_core.PomodoroCore(config)
    pomodoro_core.run(core)


if __name__ == "__main__":
    main()
