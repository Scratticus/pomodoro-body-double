"""
STT input module using faster-whisper.

Always-on listening while active. Monitors in small 0.1s chunks to detect
speech vs silence. When speech ends (0.5s gap), transcribes the utterance
and types it immediately via ydotool (live feedback in the active window).

When a trigger word ("please", "thank you", "make it so") is detected at
the end of the accumulated text, followed by 1.5s of silence, presses Enter.
The trigger word is stripped from what's typed (or kept if it's the whole message).

Toggle on/off via dictation-toggle (starts/kills this process).

Standalone test:
    python -m claude_voice.stt_input
"""

import queue
import re
import subprocess
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from .config import (
    TRIGGER_WORDS,
    TRIGGER_SILENCE_SECONDS,
    WHISPER_MODEL,
    MIC_DEVICE,
)

SAMPLE_RATE = 16000
CHUNK_SECONDS = 0.5                                 # short chunks → live feel, no revision
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_SECONDS)
CALIBRATION_SECONDS = 2.0                           # ambient noise sampling at startup


def rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))


def type_text(text: str):
    """Type text into the active window via ydotool."""
    if not text:
        return
    subprocess.run(["ydotool", "type", "--", text], check=False)


def press_backspace(n: int):
    """Send n backspace key presses via ydotool."""
    if n <= 0:
        return
    subprocess.run(["ydotool", "key", "--"] + ["BackSpace"] * n, check=False)


def press_enter():
    """Send Enter key via ydotool."""
    subprocess.run(["ydotool", "key", "--", "Return"], check=False)


def has_trigger(text: str) -> bool:
    """Return True if text ends with a trigger word."""
    for trigger in TRIGGER_WORDS:
        pattern = rf'(?i){re.escape(trigger)}[\s.,!?]*$'
        if re.search(pattern, text):
            return True
    return False


def strip_trigger(text: str) -> str:
    """Remove the trigger phrase from the end of text.
    If the trigger IS the entire message, return it unchanged so it still gets sent."""
    for trigger in sorted(TRIGGER_WORDS, key=len, reverse=True):
        pattern = rf'(?i){re.escape(trigger)}[\s.,!?]*$'
        stripped = re.sub(pattern, '', text).strip()
        if stripped != text.strip():
            return stripped if stripped else text.strip()
    return text.strip()


def calibrate_silence(device) -> float:
    """
    Record CALIBRATION_SECONDS of ambient audio and return a silence threshold
    set to 3× the ambient RMS. Prints the result so you can sanity-check it.
    """
    print(f"Calibrating mic noise floor ({CALIBRATION_SECONDS}s — stay quiet)...")
    samples = int(SAMPLE_RATE * CALIBRATION_SECONDS)
    audio = sd.rec(samples, samplerate=SAMPLE_RATE, channels=1, dtype="int16", device=device)
    sd.wait()
    ambient_rms = rms(audio[:, 0])
    threshold = max(0.01, ambient_rms * 3)
    print(f"  ambient RMS: {ambient_rms:.4f} → silence threshold: {threshold:.4f}")
    return threshold


def run():
    """
    Main loop. Records 0.5s audio chunks and transcribes each one immediately.
    Text is typed via ydotool as each chunk arrives — live, with no revision.

    When a trigger word appears at the end of accumulated text, followed by
    TRIGGER_SILENCE_SECONDS of silence, presses Enter to send.
    """
    print(f"Loading Whisper model ({WHISPER_MODEL})...")
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")

    silence_threshold = calibrate_silence(MIC_DEVICE)

    print(f"Ready. Speak — end with one of {TRIGGER_WORDS} + pause to send.")

    audio_queue: queue.Queue[np.ndarray] = queue.Queue()
    accumulated_text = ""   # everything spoken, including trigger
    typed_so_far = ""       # what's been typed (trigger stripped)
    silence_chunks = 0
    trigger_seen = False
    silence_chunks_needed = max(1, int(TRIGGER_SILENCE_SECONDS / CHUNK_SECONDS))

    def audio_callback(indata, frames, time, status):
        audio_queue.put(indata[:, 0].copy())

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=CHUNK_SAMPLES,
        device=MIC_DEVICE,
        callback=audio_callback,
    ):
        while True:
            chunk = audio_queue.get()
            chunk_float = chunk.astype(np.float32) / 32768.0

            if rms(chunk_float) < silence_threshold:
                if trigger_seen:
                    silence_chunks += 1
                    if silence_chunks >= silence_chunks_needed:
                        print("  → SEND (Enter)")
                        press_enter()
                        accumulated_text = ""
                        typed_so_far = ""
                        trigger_seen = False
                        silence_chunks = 0
                continue

            # Speech — reset silence counter and transcribe immediately
            silence_chunks = 0
            segments, _ = model.transcribe(
                chunk_float,
                language="en",
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 200},
            )
            chunk_text = " ".join(s.text for s in segments).strip()
            if not chunk_text:
                continue

            print(f"  heard: {chunk_text!r}")
            accumulated_text = (accumulated_text + " " + chunk_text).strip()

            if has_trigger(accumulated_text):
                trigger_seen = True
                silence_chunks = 0
                text_to_show = strip_trigger(accumulated_text)
            else:
                text_to_show = accumulated_text

            # Type new portion, or send backspaces if trigger stripped already-typed text
            if len(text_to_show) > len(typed_so_far):
                new_part = text_to_show[len(typed_so_far):]
                type_text(new_part)
                typed_so_far = text_to_show
            elif len(text_to_show) < len(typed_so_far):
                backspaces = len(typed_so_far) - len(text_to_show)
                print(f"  → backspace ×{backspaces} (stripping trigger)")
                press_backspace(backspaces)
                typed_so_far = text_to_show


if __name__ == "__main__":
    run()
