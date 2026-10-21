# spd-kokoro

A [Speech Dispatcher](https://freebsoft.org/speechd) output module that
speaks through any **OpenAI-compatible `/v1/audio/speech`** endpoint.
It was written for [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI)
running in Docker on `localhost:8880`, but it works with any compatible
server (including `tts-1` style APIs and other local TTS frontends).

This lets Orca, Firefox Reader Mode, `spd-say`, and every other Speech
Dispatcher client use Kokoro — including voice selection, rate, volume,
stop, and pause.

```
Orca / Firefox / spd-say
        │  SSIP
        ▼
speech-dispatcher
        │  output-module protocol (stdin/stdout)
        ▼
spd_kokoro  ──HTTP POST /v1/audio/speech──▶  Kokoro-FastAPI :8880
        │
        └──plays WAV with pw-play / paplay / mpv / ffplay / aplay
```

No third-party Python packages are required. This was developed and
tested with Speech Dispatcher 0.12.1 and Kokoro-FastAPI on Arch Linux
(PipeWire, PulseAudio compatibility).

## Quick start

```bash
# 1. Make sure Kokoro is up
curl -s http://localhost:8880/health
curl -s http://localhost:8880/v1/audio/voices | head -c 200

# 2. Install for the current user (does not change the default module)
./install.sh

# 3. Speak through it explicitly
spd-say -o kokoro -w "Hello from Kokoro"

# 4. Make it the default for Orca, Firefox, etc.
./install.sh --default

# 5. Or pick a voice (see the full list with: spd-say -L -o kokoro)
spd-say -o kokoro -y am_michael -w "A different voice"
```

The installer puts:

| File | Location |
| --- | --- |
| module binary | `~/.local/libexec/speech-dispatcher-modules/spd_kokoro` |
| module config | `~/.config/speech-dispatcher/modules/kokoro.conf` |
| server config | `~/.config/speech-dispatcher/speechd.conf` |

`speechd.conf` is backed up before it is edited, and the installer keeps
any modules you already had (for example Piper). Restart the server after
manual config changes:

```bash
systemctl --user restart speech-dispatcher
```

## Configuration

Edit `~/.config/speech-dispatcher/modules/kokoro.conf`. The defaults are
sensible for a local Kokoro-FastAPI container:

```conf
KokoroURL "http://localhost:8880/v1/audio/speech"
KokoroModel "kokoro"
KokoroVoice "af_heart"
KokoroFormat "wav"
```

Common changes:

| Option | Meaning |
| --- | --- |
| `KokoroURL` | Speech endpoint. Point this at another host/port if needed. |
| `KokoroVoicesURL` | Voices endpoint. Empty derives it from `KokoroURL`. |
| `KokoroAPIKey` | Optional `Authorization: Bearer ...` token. |
| `KokoroModel` | Model name: `kokoro`, `tts-1`, `tts-1-hd`, ... |
| `KokoroVoice` | Default voice, e.g. `af_heart`, `am_michael`, `bf_alice`. |
| `KokoroFormat` | `wav` (default), `mp3`, `opus`, `flac`, ... |
| `KokoroChunkChars` | Split long text at sentence boundaries (default 600). |
| `KokoroPlayer` | `auto`, or an absolute path to a player. |
| `KokoroPlayerArgs` | Extra player args, e.g. a PipeWire target/device. |
| `KokoroVolume` | Extra master gain, `0.0`–`1.0`. |
| `KokoroTimeout` | Synthesis timeout in seconds. |
| `KokoroLog` | Debug log file (empty = off). |
| `KokoroUniqueLangTags` | Report `en-US-x-af-heart` style tags (see Firefox below). |
| `KokoroPinVoice` | Always speak with `KokoroVoice`, ignoring client voice/language requests. |

### Voices

The module asks the endpoint for its voice list at startup
(`GET /v1/audio/voices`) and exposes every voice to Speech Dispatcher with
a language and gender. A built-in fallback list keeps the module usable if
the endpoint is temporarily down.

Voice IDs follow Kokoro's convention, `<language><gender>_<name>`:

| Prefix | Language | Prefix | Language |
| --- | --- | --- | --- |
| `af_` / `am_` | English (US) | `bf_` / `bm_` | English (GB) |
| `ef_` / `em_` | Spanish | `ff_` | French |
| `hf_` / `hm_` | Hindi | `if_` / `im_` | Italian |
| `jf_` / `jm_` | Japanese | `pf_` / `pm_` | Portuguese (BR) |
| `zf_` / `zm_` | Chinese | | |

Examples:

```bash
spd-say -L -o kokoro                       # list everything
spd-say -L -o kokoro -l en-GB             # list British voices
spd-say -o kokoro -y af_heart -w "..."    # specific voice
```

If a client only sets a language (Orca often does), the module picks a
matching voice, preferring `KokoroVoice` and then a female voice.

### Firefox Reader Mode (Narrate)

Two things in Firefox's Narrate menu are Firefox behaviour, not this module:

- **Every voice shows up as its language.** On Linux, Narrate labels each
  entry with the voice's language and deliberately ignores its name
  (`toolkit/components/narrate/NarrateControls.sys.mjs`,
  `_createVoiceLabel()`), so all `af_*` voices appear as
  "English (en-US)". `spd-say -L` shows the real names.
- **The "Default" voice is not `KokoroVoice`.** Firefox registers the
  voices in an unordered internal list and its automatic selection takes
  the *last* voice matching the article language
  (`nsSynthVoiceRegistry::FindVoiceByLang()`), which can be any voice —
  for example `af_nicole` instead of `af_heart`.

To pin the voice, set Firefox's own `narrate.voice` preference
(about:config → string; Firefox writes this pref itself when you pick a
voice from the menu):

```json
{"default":"urn:moz-tts:speechd:af_heart?en-US","en":"urn:moz-tts:speechd:af_heart?en-US"}
```

Keys are the detected article language (`en` for English, `default` for
when detection fails); values are
`urn:moz-tts:speechd:<voice>?<language>`. Note that a value in `user.js`
overrides the Narrate menu on every start, so remove the line if you want
to switch voices from the menu later.

To make the menu itself readable, enable:

```conf
KokoroUniqueLangTags 1
```

The module then reports `en-US-x-af-heart` instead of `en-US`, and Narrate
shows "English (en-US-x-af-heart)". The tags are valid BCP-47 and still
match `en-US` by prefix, but other clients see them too, which is why this
is off by default.

Alternatively, set `KokoroPinVoice 1` to make the module always speak with
`KokoroVoice` no matter what any client (including Firefox) requests.
Clients can still choose rate and volume, just not the voice.  If
`KokoroVoice` names a voice the endpoint does not know, the module falls
back to normal client-driven selection and logs a warning.

### Rate and volume

- Speech Dispatcher `rate` (-100…100) maps to Kokoro `speed` with
  `2^(rate/100)`, clamped to `KokoroMinSpeed`…`KokoroMaxSpeed`
  (0.5–2.0 by default). `-25` is about 0.84×, `+25` about 1.19×.
- Speech Dispatcher `volume` (-100…100) maps linearly to the player's
  stream volume. `-100` is silent, `0` is 50 %, `100` is 100 %.
- `pitch` and `pitch_range` are accepted but ignored: the OpenAI speech
  API has no pitch parameter, and client-side pitch shifting would
  degrade Kokoro's output.

## How it works

`spd_kokoro` implements Speech Dispatcher's output-module protocol
(`INIT`, `AUDIO`, `LOGLEVEL`, `SET`, `LIST VOICES`, `SPEAK`,
`CHAR`, `KEY`, `SOUND_ICON`, `STOP`, `PAUSE`, `QUIT`). For each utterance
it:

1. strips index marks / SSML if present;
2. splits long text into sentence-sized chunks (so time-to-first-audio
   stays short and long paragraphs never hit endpoint limits);
3. POSTs each chunk to `/v1/audio/speech`;
4. plays the returned audio with the best available player;
5. reports `701 BEGIN` / `702 END`, or `703 STOP` / `704 PAUSE` if canceled.

The module refuses Speech Dispatcher's "server audio" mode and plays audio
itself, which keeps stop/cancel latency low and avoids buffering the whole
utterance in the server.

## Troubleshooting

**No sound, but `curl` to Kokoro works**

```bash
spd-say -O                       # is kokoro listed?
spd-say -o kokoro -w "test"
```

Turn on the module log:

```conf
KokoroLog "/tmp/spd-kokoro.log"
```

then restart Speech Dispatcher and try again. The log records the chosen
voice, settings, HTTP errors, and player exit codes.

**HTTP 404 / connection refused**

Check the URL in `kokoro.conf`. Kokoro-FastAPI exposes
`/v1/audio/speech` and `/v1/audio/voices`; the plain `/audio/speech`
path from older docs is not used here.

**Module not listed**

Make sure the binary is executable and in the directory Speech
Dispatcher uses:

```bash
ls -l ~/.local/libexec/speech-dispatcher-modules/spd_kokoro
systemctl --user restart speech-dispatcher
```

**Test the protocol without Speech Dispatcher**

```bash
./test-protocol.py          # mock endpoint, silent fake player
./test-protocol.py --real   # your real Kokoro endpoint
./test-protocol.py -v       # show every protocol line
```

**Playback device**

`auto` prefers `pw-play`, then `paplay`, `mpv`, `ffplay`, `aplay`. To
choose a sink explicitly:

```conf
KokoroPlayerArgs "--target alsa_output.pci-0000_00_1f.3.analog-stereo"
```

(for `pw-play`; use `--device=...` for `paplay`).

## Uninstall

```bash
./uninstall.sh                 # remove module/config, restore default
./uninstall.sh --keep-config   # keep kokoro.conf
```

## Files

| File | Purpose |
| --- | --- |
| `spd_kokoro` | The output module (Python, stdlib only). |
| `kokoro.conf` | Module configuration. |
| `install.sh` | Per-user installer. |
| `uninstall.sh` | Per-user uninstaller. |
| `test-protocol.py` | Protocol test harness with mock HTTP server. |

## License

GPL-2.0-or-later, matching Speech Dispatcher's modules.
