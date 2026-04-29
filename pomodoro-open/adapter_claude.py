#!/usr/bin/env python3
"""
Adapter for Claude Code (Clawed).
Formats prompts for Clawed's hook injection system.
"""

import fcntl
import json
import os
import sys
from datetime import datetime

import pomodoro_core


class ClaudeAdapter:
    """Adapter that formats prompts for Clawed's hook system."""

    def __init__(self, base_dir=None):
        self.base_dir = base_dir or os.path.expanduser("~/.claude/productivity")
        self.queue_file = os.path.join(self.base_dir, "prompt_queue.json")
        self.ack_file = os.path.join(self.base_dir, "acknowledged.txt")
        self.session_file = os.path.join(self.base_dir, "session.yaml")
        self.chore_timers_file = os.path.join(self.base_dir, "chore_timers.yaml")

    def _substitute(self, text):
        """Replace agent-specific placeholders. Core uses <ack_file>, <tool_name>,
        <session_file>, <chore_timers_file> in prompt strings. Each adapter substitutes
        with values appropriate for its agent."""
        return (text
                .replace("<tool_name>", "Write tool")
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

    def _map_to_hook_events(self, prompt_type):
        """Map prompt type to Clawed hook event names.

        For other agents, this determines which events surface the prompt.
        For Claude, all events are surfaced via sh hooks, so mapping is
        informational — stored in queue for future filtering if needed.
        """
        mapping = {
            "session_start": ["SessionStart"],
            "work_complete": ["UserPromptSubmit", "PostToolUse"],
            "break_complete": ["UserPromptSubmit", "PostToolUse"],
            "suggest_break": ["UserPromptSubmit", "PostToolUse"],
            "suggest_work": ["UserPromptSubmit", "PostToolUse"],
            "meeting_starting": ["UserPromptSubmit", "PostToolUse"],
            "chore": ["UserPromptSubmit", "PostToolUse"],
            "reminder": ["UserPromptSubmit", "PostToolUse"],
            "meeting_warning": ["UserPromptSubmit", "PostToolUse"],
            "extend_reminder": ["UserPromptSubmit", "PostToolUse"],
            "error": ["UserPromptSubmit", "PostToolUse"],
        }
        return mapping.get(prompt_type, ["UserPromptSubmit", "PostToolUse"])

    def surface_prompt(self, prompt_type, prompt_text):
        """Append prompt to queue for the hook to surface on next fire."""
        text = self._substitute(prompt_text)
        queue = self._load_queue()
        nid = max((e["id"] for e in queue), default=0) + 1
        queue.append({
            "id": nid,
            "timestamp": datetime.now().isoformat(),
            "type": prompt_type,
            "prompt": text,
            "delivered": False,
            "hook_events": self._map_to_hook_events(prompt_type),
        })
        self._save_queue(queue)

    def has_undelivered(self, prompt_type):
        """Return True if any undelivered entry of this type exists in queue."""
        queue = self._load_queue()
        return any(e["type"] == prompt_type and not e.get("delivered") for e in queue)

    def clear(self):
        """Clear all entries from queue."""
        self._save_queue([])


def main():
    base_dir = sys.argv[1] if len(sys.argv) > 1 else None
    adapter = ClaudeAdapter(base_dir)
    config = pomodoro_core.create_config(base_dir, adapter)
    core = pomodoro_core.PomodoroCore(config)
    pomodoro_core.run(core)


if __name__ == "__main__":
    main()