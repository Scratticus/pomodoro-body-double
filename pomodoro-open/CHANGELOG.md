# Changelog — pomodoro-open

Notable bug fixes and behaviour changes. Newest first. Append a new entry whenever a bug is resolved or a public behaviour changes.

---

## 2026-04-29

- **Repo restructure.** Split `pomodoro.py` monolith into `pomodoro-open/` package (`pomodoro_core.py` + adapters). Added install model with two-option CLAUDE.md handling (alt-location or overwrite). Removed voice interface (faster-whisper, sounddevice, piper-tts, pexpect) — Claude's built-in voice now handles that surface. Removed dead `SessionStart` echo hook from `settings.json`. New `scripts/backup-data.sh` for snapshotting `~/.claude/productivity/*.yaml` before testing changes.

## 2026-04-28 — Refactor

Resolved bugs from the modular split:

- **`extend_minutes` wipe.** `wait_for_ack` was clearing `extend_minutes = None` on every ack, including `extend` acks. Fix: only clear when `parsed["action"] != "extend"`. Combined with clear-on-use at every consumer site (Step 3b), customisation now applies once per `extend` ack and resets to default afterwards.

- **`session_log` wiped on restart (data loss).** `run_session` called `reset_session()` at startup, which zeroed `session_log` without flushing to `log.yaml`. Fix: flush before reset at startup.

- **Dead branches in `run_session`.** Because `reset_session()` deletes the ack and nulls `start_time`, two downstream branches were unreachable. Removed.

- **`load_chores` not persisting `ensure_ids`.** Track `changed`, save once at end of function.

- **OpenCode adapter contract gap.** Rewrote `surface_prompt` to append (not read-and-print), added `has_undelivered` / `clear` / `notify`, marked plugin-specific delivery format with TODOs.

- **`DefaultAdapter` silently dropping prompts.** Now prints to stdout for manual debugging.

## Pending — verify live

- "Start session worked, but start tasks were not handled." Likely: hook surfaces `[session_start] ...` but Claude does not act because the prompt arrives via `SessionStart` hook event and the hook script may not differentiate by event. Run one full session to confirm or surface root cause.
- "End ack is ignored." Walking the logic showed no obvious gap. Likely a stale-state issue (e.g. `pending_resolution` blocking). Reproduce live before fixing blind.
