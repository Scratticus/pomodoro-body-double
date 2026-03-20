"""
Configuration and constants for claude_voice.
All paths and tuneable values live here.
"""

from pathlib import Path

# === PRODUCTIVITY FILE PATHS ===
PRODUCTIVITY_DIR = Path.home() / ".claude" / "productivity"
SESSION_FILE = PRODUCTIVITY_DIR / "session.yaml"
CHORE_TIMERS_FILE = PRODUCTIVITY_DIR / "chore_timers.yaml"
QUEUE_FILE = PRODUCTIVITY_DIR / "prompt_queue.json"
ACK_FILE = PRODUCTIVITY_DIR / "acknowledged.txt"
TASKS_FILE = PRODUCTIVITY_DIR / "tasks.yaml"

# === PIPER TTS ===
PIPER_MODEL_PATH = Path.home() / ".local" / "share" / "piper" / "en_GB-cori-high.onnx"
PIPER_MODEL_CONFIG = Path.home() / ".local" / "share" / "piper" / "en_GB-cori-high.onnx.json"

# === VOICE INPUT ===
TRIGGER_WORDS = ["please", "thank you", "make it so"]
TRIGGER_SILENCE_SECONDS = 1.5
WHISPER_MODEL = "small"
MIC_DEVICE = None  # None = system default. Set to device name/index to override.

# === VOICE PERSONA ===
VOICE_PERSONA_FILE = Path(__file__).parent.parent / "voice_persona.yaml"
