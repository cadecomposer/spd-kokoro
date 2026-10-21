# AGENTS.md

Guidance for AI coding agents working in this repository.

## What this is

`spd_kokoro` is a Speech Dispatcher output module (a single Python 3 file,
stdlib only) that speaks text through any OpenAI-compatible
`/v1/audio/speech` endpoint, primarily Kokoro-FastAPI on `localhost:8880`.
It lets Orca, Firefox Reader Mode, and `spd-say` use Kokoro as a TTS voice.

## Layout

- `spd_kokoro` — the module itself (~900 lines, Python 3, no third-party
  deps). Speaks the Speech Dispatcher output-module protocol on
  stdin/stdout (INIT / AUDIO / SET / LIST VOICES / SPEAK / STOP / QUIT…).
  Not a package; installed as an executable.
- `kokoro.conf` — module config template, installed to
  `~/.config/speech-dispatcher/modules/kokoro.conf`.
- `install.sh` / `uninstall.sh` — per-user install/uninstall. Edits
  `~/.config/speech-dispatcher/speechd.conf` (backs it up first), installs
  the binary to `~/.local/libexec/speech-dispatcher-modules/`.
- `test-protocol.py` — protocol-level test harness.
- `README.md` — user-facing documentation; keep it in sync with behavior
  changes.

## Conventions

- Python: stdlib only (urllib, json, subprocess, threading…). No pip
  installs, no `requirements.txt`. Target the oldest Python Speech
  Dispatcher 0.12 ships with (3.8-era syntax is fine; the file already uses
  `from __future__ import annotations`).
- Audio playback shells out to an available player (`pw-play`, `paplay`,
  `mpv`, `ffplay`, `aplay`) — keep that fallback chain working.
- Bash scripts use `set -euo pipefail`; install/uninstall must be safe to
  re-run (idempotent) and back up `speechd.conf` before editing it.
- The module must never hard-crash speech-dispatcher: if the TTS endpoint
  is down, fall back gracefully (see `FALLBACK_VOICE_IDS`).

## Testing

There is no unit-test framework. To test locally:

1. Start Kokoro-FastAPI (or any OpenAI-compatible TTS) on port 8880.
2. `./install.sh` (add `--default` to make kokoro the default module).
3. `spd-say -o kokoro -w "Hello"` / `spd-say -L -o kokoro`.

Note: if speech-dispatcher runs as a **system** service, restarting it
needs `sudo systemctl daemon-reload && sudo systemctl restart
speech-dispatcherd` (the user service is named `speech-dispatcher`, the
system one `speech-dispatcherd`).

## Gotchas

- Voice ids are prefixed with language+gender (`af_heart` = en-US female);
  see `LANGUAGE_BY_PREFIX`.
- Config keys live in `kokoro.conf`; new options need a default in both the
  config template and the module's parsing code.
- Don't commit `__pycache__/` (already gitignored).
