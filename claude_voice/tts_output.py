"""
TTS output module using Piper.

Two interfaces:

1. speak(text) / speak_chunks(text)
   Complete string in, spoken sentence by sentence. Used by ack_handler
   and anywhere the full text is already available.

2. StreamingSpeaker
   Feed partial text chunks as they arrive (e.g. from claude_bridge).
   Accumulates a buffer, speaks each sentence the moment it's complete,
   holds the incomplete tail until more text arrives or flush() is called.

Standalone test:
    python -m claude_voice.tts_output "Hello, this is a test sentence."
    python -m claude_voice.tts_output --stream
"""

import re
import sys
import wave
import io
import asyncio
import threading

from piper import PiperVoice
from piper.voice import SynthesisConfig

from .config import PIPER_MODEL_PATH, PIPER_MODEL_CONFIG

# Slightly slower than default (1.0) — keeps Cori natural without rushing
SPEECH_RATE = SynthesisConfig(length_scale=1.0)


# === MODEL LOADING ===

_voice = None
_voice_lock = threading.Lock()


def get_voice():
    """Load Piper voice model (lazy, cached)."""
    global _voice
    with _voice_lock:
        if _voice is None:
            print(f"  Loading TTS model: {PIPER_MODEL_PATH.name}...")
            _voice = PiperVoice.load(str(PIPER_MODEL_PATH), config_path=str(PIPER_MODEL_CONFIG))
            print("  TTS model ready.")
    return _voice


# === TEXT CLEANING ===

# Matches [ACK: ...] markers - stripped silently, not spoken
ACK_PATTERN = re.compile(r'\[ACK:[^\]]*\]')

# Sentence boundary: ., ?, ! or ; followed by whitespace or end of string
# Avoids splitting on e.g. "Mr." or "3.14" by requiring following whitespace/end
SENTENCE_BOUNDARY = re.compile(r'(?<=[.?!;])\s+')


def strip_markdown(text):
    """Remove markdown formatting that would sound odd when spoken."""
    # Code blocks (multi-line)
    text = re.sub(r'```[\s\S]*?```', 'code block', text)
    # Inline code
    text = re.sub(r'`[^`]+`', lambda m: m.group(0).strip('`'), text)
    # Bold/italic
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', text)
    # Headers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Bullet points
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    # Numbered lists
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    # Horizontal rules
    text = re.sub(r'^[-*_]{3,}$', '', text, flags=re.MULTILINE)
    # Links: [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remaining bare URLs
    text = re.sub(r'https?://\S+', 'link', text)
    return text.strip()


def extract_ack(text):
    """
    Extract [ACK: ...] markers from text.
    Returns (cleaned_text, list_of_ack_strings).
    e.g. "[ACK: continue:Job hunting]" -> ("", ["continue:Job hunting"])
    """
    acks = []
    for match in ACK_PATTERN.finditer(text):
        raw = match.group(0)
        ack_content = raw[5:-1].strip()  # strip [ACK: and ]
        acks.append(ack_content)
    cleaned = ACK_PATTERN.sub('', text).strip()
    return cleaned, acks


def clean_for_speech(text):
    """Full cleaning pipeline: extract ACKs, strip markdown, normalise whitespace."""
    text, acks = extract_ack(text)
    text = strip_markdown(text)
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip(), acks


def split_sentences(text):
    """Split text on sentence boundaries. Returns list of non-empty strings."""
    parts = SENTENCE_BOUNDARY.split(text)
    return [p.strip() for p in parts if p.strip()]


# === AUDIO PLAYBACK ===

def speak_text(text):
    """Synthesise and play a single chunk of text. Blocking."""
    import sounddevice as sd
    import numpy as np

    voice = get_voice()
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wav_file:
        voice.synthesize_wav(text, wav_file, syn_config=SPEECH_RATE)

    buf.seek(0)
    with wave.open(buf, 'rb') as wav_file:
        framerate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())

    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    sd.play(audio, samplerate=framerate, blocking=True)


# === ASYNC INTERFACE ===

async def speak_chunks(text):
    """
    Clean text, extract ACKs, split into sentences, speak each one.
    Yields ack strings as they're found (before speaking begins).
    Intended for streaming: call with partial text as it arrives.
    """
    cleaned, acks = clean_for_speech(text)
    sentences = split_sentences(cleaned)

    # Yield ACKs immediately so ack_handler can act without waiting for speech
    for ack in acks:
        yield ('ack', ack)

    # Speak sentences sequentially
    loop = asyncio.get_event_loop()
    for sentence in sentences:
        if sentence:
            await loop.run_in_executor(None, speak_text, sentence)
            yield ('spoken', sentence)


async def speak(text):
    """Speak text, returning list of any ACK strings found."""
    acks = []
    async for event_type, value in speak_chunks(text):
        if event_type == 'ack':
            acks.append(value)
    return acks


# === STREAMING INTERFACE ===

THINKING_PHRASES = ["... one moment.", "... let me think.", "... just a moment."]
_thinking_index = 0


class StreamingSpeaker:
    """
    Assembles partial text chunks into complete sentences. Speaking happens
    in a separate concurrent task via a queue, so the assembler never blocks
    waiting for audio to finish — sentence N+1 is ready the moment it completes,
    regardless of whether sentence N is still playing.

    Architecture:
        assembler task  -->  sentence_queue  -->  speaker task
        (feeds chunks,        (asyncio.Queue)      (speaks each
         detects boundaries,                        sentence in turn)
         pushes sentences)

    Usage:
        queue = asyncio.Queue()
        speaker = StreamingSpeaker(queue)

        async def speak_loop():
            while True:
                sentence = await queue.get()
                if sentence is None:
                    break
                await loop.run_in_executor(None, speak_text, sentence)

        asyncio.create_task(speak_loop())
        await speaker.start_thinking()
        async for event in speaker.feed(chunk):
            ...  # ('ack', value) events only — sentences go to queue
        async for event in speaker.flush():
            pass
        await queue.put(None)  # signal speaker to stop

    feed() and flush() yield:
        ('ack', ack_string)   -- ACK marker found and stripped (handle immediately)
        ('sentence', text)    -- complete sentence pushed to queue (informational)
    """

    def __init__(self, queue: asyncio.Queue):
        self._buffer = ""
        self._queue = queue

    async def start_thinking(self):
        """
        Queue a short phrase to signal Claude is thinking.
        Called once immediately after the user's prompt is sent, before
        any chunks arrive. Rotates through THINKING_PHRASES.
        """
        global _thinking_index
        phrase = THINKING_PHRASES[_thinking_index % len(THINKING_PHRASES)]
        _thinking_index += 1
        await self._queue.put(phrase)

    async def feed(self, chunk: str):
        """
        Add a chunk of text. Any completed sentences are pushed to the queue.
        ACK markers are yielded immediately for the caller to handle.
        """
        self._buffer += chunk

        # Extract ACK markers without .strip() — preserves inter-chunk whitespace
        acks = []
        for match in ACK_PATTERN.finditer(self._buffer):
            acks.append(match.group(0)[5:-1].strip())
        self._buffer = ACK_PATTERN.sub('', self._buffer)

        for ack in acks:
            yield ('ack', ack)

        while True:
            match = SENTENCE_BOUNDARY.search(self._buffer)
            if not match:
                break
            sentence = self._buffer[:match.start()]
            self._buffer = self._buffer[match.end():]

            sentence = strip_markdown(sentence)
            sentence = re.sub(r'\s+', ' ', sentence).strip()
            if sentence:
                await self._queue.put(sentence)
                yield ('sentence', sentence)

    async def flush(self):
        """
        Push any remaining buffered text to the queue (end of response).
        """
        remainder = self._buffer.strip()
        self._buffer = ""

        if not remainder:
            return

        remainder = strip_markdown(remainder)
        remainder = re.sub(r'\s+', ' ', remainder).strip()
        if remainder:
            await self._queue.put(remainder)
            yield ('sentence', remainder)


# === STANDALONE TEST ===

async def _test_streaming():
    """
    Simulate Claude generating text in chunks with realistic delays.
    Two sentences across eight chunks.

    The assembler and speaker run as separate concurrent tasks:
    - assembler: feeds chunks into StreamingSpeaker, pushes complete sentences
      to the queue as they arrive
    - speaker: reads from the queue and speaks each sentence

    This means sentence 2 is assembling in the background while sentence 1 is
    still playing — no gap between sentences.
    """
    chunks = [
        ("Good morning, ",          0.0),
        ("I hope you are ",         0.6),
        ("having a productive ",    0.5),
        ("day today.",              0.4),
        (" The voice interface ",   0.5),
        ("is now streaming ",       0.4),
        ("chunk by chunk, ",        0.5),
        ("just as intended.",       0.4),
    ]

    queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    async def assemble():
        speaker = StreamingSpeaker(queue)
        print("Thinking...")
        await speaker.start_thinking()
        for chunk, delay in chunks:
            await asyncio.sleep(delay)
            print(f"  feed: {chunk!r}")
            async for event_type, value in speaker.feed(chunk):
                print(f"    -> {event_type}: {value!r}")
        async for event_type, value in speaker.flush():
            print(f"    -> {event_type}: {value!r}")
        await queue.put(None)  # signal speaker to stop

    async def speak_loop():
        while True:
            sentence = await queue.get()
            if sentence is None:
                break
            print(f"  speaking: {sentence!r}")
            await loop.run_in_executor(None, speak_text, sentence)

    await asyncio.gather(assemble(), speak_loop())

if __name__ == "__main__":
    asyncio.run(_test_streaming())
