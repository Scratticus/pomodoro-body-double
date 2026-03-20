# Credits and Acknowledgements

Open source dependencies, models, and resources used in this project.
This file is updated whenever a new external resource is added.

---

## Core Dependencies

| Name | Version | License | URL | Used For |
|------|---------|---------|-----|----------|
| Python | 3.x | PSF License | https://python.org | Runtime |
| PyYAML | 6.x | MIT | https://pyyaml.org | YAML file I/O |
| notify-send (libnotify) | system | LGPL-2.1 | https://gitlab.gnome.org/GNOME/libnotify | Desktop notifications |

## Voice Interface Dependencies

| Name | Version | License | URL | Used For |
|------|---------|---------|-----|----------|
| piper-tts | 1.4.1 | GPL-3.0 | https://github.com/OHF-voice/piper1-gpl | Text to speech engine |
| pexpect | latest | ISC | https://pexpect.readthedocs.io | Claude Code subprocess control |

## Speech Recognition

| Name | Version | License | URL | Used For |
|------|---------|---------|-----|----------|
| nerd-dictation | latest | GPL-2.0 | https://github.com/ideasman42/nerd-dictation | Current desktop dictation toggle |
| vosk | latest | Apache 2.0 | https://alphacephei.com/vosk | STT backend for nerd-dictation |

## Voice Models

| Name | License | URL | Used For |
|------|---------|-----|----------|
| vosk-model-en-us-0.42-gigaspeech | Apache 2.0 | https://alphacephei.com/vosk/models | Primary dictation model (2.3GB, podcast-trained) |
| vosk-model-small-en-us-0.15 | Apache 2.0 | https://alphacephei.com/vosk/models | Fallback dictation model (68MB) |

## Input Simulation

| Name | License | URL | Used For |
|------|---------|-----|----------|
| ydotool | GPL-3.0 | https://github.com/ReimuNotMoe/ydotool | Keyboard input simulation for dictation |

---

| en_GB-cori-high | MIT (dataset: public domain LibriVox) | https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_GB/cori/high | British English female TTS voice (109MB) |

## Pending (to add once confirmed)

- faster-whisper (STT for voice interface) - license TBC before adding
- sounddevice (microphone capture) - license TBC before adding

---

## License Compatibility Note

This project is licensed under GPL-3.0. All dependencies are compatible:
- GPL-3.0 deps (piper-tts, ydotool, nerd-dictation): same license
- Apache 2.0 deps (vosk, vosk models): permissive, GPL-3.0 compatible
- MIT deps (PyYAML): permissive, GPL-3.0 compatible
- ISC deps (pexpect): permissive, GPL-3.0 compatible
- LGPL deps (libnotify): compatible with GPL-3.0
