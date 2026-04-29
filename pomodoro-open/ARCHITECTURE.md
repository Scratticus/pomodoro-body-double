# Architecture — pomodoro-open

The package splits cleanly into agent-agnostic logic and per-agent adapters.

```
pomodoro_core.py    all timer / state / ack logic — knows nothing about Claude or any other agent
adapter_claude.py   Claude Code adapter — queue I/O, hook event mapping, placeholder substitution
adapter_opencode.py OpenCode adapter stub — contract-conformant, plugin TODOs
```

## Core ↔ Adapter contract

Every adapter must provide:

```python
surface_prompt(prompt_type, prompt_text)  # format placeholders + persist for the agent
has_undelivered(prompt_type)              # True if any undelivered entry matches type
clear()                                   # wipe queue at session reset
notify(title, message)                    # desktop notification (optional)
```

Optional but used by core:

```python
base_dir   # used by create_config() if base_dir is None
```

Per-adapter attributes used for placeholder substitution:

```python
ack_file, session_file, chore_timers_file, queue_file
```

## Placeholder substitution

Core builds prompts with placeholders: `<tool_name>`, `<ack_file>`, `<session_file>`, `<chore_timers_file>`. Each adapter's `_substitute()` method replaces them at delivery time using `str.replace`.

- `ClaudeAdapter` substitutes `<tool_name>` with `"Write tool"`.
- `OpenCodeAdapter`'s `<tool_name>` is a placeholder until the plugin is built and the actual file-writing tool name is known.

Angle-bracket placeholders (not curly braces) avoid collision with literal `{...}` text in prompts (e.g. YAML examples like `{delay: <minutes>}`).

## Ack vocabulary

`work:Task Name` | `break` | `extend` | `end`. Legacy `continue` and `continue:Task` tokens are rejected by `parse_ack` with a vocabulary-update prompt. See `pomodoro_core.py:parse_ack` for the full validation flow.

`parse_ack` is pure — no side effects. Routing of `work:Task` to `session.task_switch` happens in `countdown`'s mid-timer ack-poll dispatch when `'work'` is NOT in the caller's `exit_actions`.

## Symmetric auto-extend with nudges

Both work and break phases enter an auto-extend loop when their timer expires without a phase-changing ack:

1. Desktop notification.
2. Queue `suggest_break` (work-end) or `suggest_work` (break-end), deduped against undelivered queue entries.
3. Auto-extend timer by `EXTEND_MINUTES` (default 10, or `session.extend_minutes` if user set a custom value).
4. Repeat from step 1 at next zero. Loop exits only on `break`/`end` (work) or `work:Task`/`end` (break).

Reminder pings continue to fire independently throughout via the desktop notification path.

## Mid-timer ack polling

`countdown` polls the ack file every ~1 second alongside its existing session-yaml polling (~10s). Dispatch:

| Action | In `exit_actions` | Behaviour |
|---|---|---|
| `extend` | irrelevant | Read `session.extend_minutes` (or default), add to remain + total, clear field, continue countdown. |
| `work:Task` | yes | Return `early_ack`. Caller (break_phase) applies the task transition. |
| `work:Task` | no | Side-effect via `session.task_switch`. Existing handler applies on next 10 s tick. Continue countdown. |
| `break` | yes | Return `early_ack`. Caller (work_phase) starts a break. |
| `break` | no | No-op (mid-break `break` is meaningless). |
| `end` | always | Return `early_ack`. Caller exits, `run_session` ends session. |

The ack-poll runs **before** the session-poll on the same iteration, so an `extend` ack consumes `extend_minutes` deterministically when both an ack and a YAML edit arrive in the same window.

## Queue entry format

```json
{
  "id": 1,
  "timestamp": "2026-04-28T10:30:00",
  "type": "suggest_break",
  "prompt": "Work phase complete. ... Write 'break' / 'extend' / 'end' to /home/.../acknowledged.txt using Write tool.",
  "delivered": false,
  "hook_events": ["UserPromptSubmit", "PostToolUse"]
}
```

`delivered` is set by the hook when it surfaces the prompt. `hook_events` is for adapters that filter by event (Claude's hook ignores it; future adapters may use it).

## Event mapping

| Prompt type | Hook events (Claude) |
|---|---|
| session_start | UserPromptSubmit, PostToolUse |
| suggest_break | UserPromptSubmit, PostToolUse |
| suggest_work | UserPromptSubmit, PostToolUse |
| meeting_starting | UserPromptSubmit, PostToolUse |
| meeting_warning | UserPromptSubmit, PostToolUse |
| chore | UserPromptSubmit, PostToolUse |
| reminder | UserPromptSubmit, PostToolUse |
| error | UserPromptSubmit, PostToolUse |

## Running

```bash
python3 pomodoro-open/adapter_claude.py
```

Defaults to `~/.claude/productivity` via `ClaudeAdapter.base_dir`. The installed launcher at `~/.claude/productivity/pomodoro.py` shells out to this same adapter.
