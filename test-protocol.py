#!/usr/bin/env python3
"""
Protocol test harness for spd_kokoro.

Starts the module exactly the way Speech Dispatcher does (config path as
argv[1]), speaks the output-module protocol at it, and checks the replies.

By default a mock OpenAI-compatible server and a fake audio player are
used, so the test is silent and needs no network.  Pass --real to
synthesize through the real endpoint from kokoro.conf instead (playback is
still faked, so the test stays quiet).

Usage:
    ./test-protocol.py            # mock server + fake player
    ./test-protocol.py --real     # real Kokoro endpoint + fake player
    ./test-protocol.py -v         # show every protocol line
"""

from __future__ import annotations

import argparse
import io
import json
import os
import queue
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.path.join(HERE, "spd_kokoro")
CONFIG = os.path.join(HERE, "kokoro.conf")

VERBOSE = False
failures: list[str] = []


def log(message: str) -> None:
    if VERBOSE:
        print(f"    {message}")


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  ok   {message}")
    else:
        print(f"  FAIL {message}")
        failures.append(message)


def make_wav(seconds: float = 0.25, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(1500 * ((i // 40) % 2 * 2 - 1)))
            for i in range(int(rate * seconds))
        )
        wav.writeframes(frames)
    return buf.getvalue()


MOCK_WAV = make_wav()
MOCK_VOICES = {
    "voices": [
        {"id": "af_heart"},
        {"id": "am_michael"},
        {"id": "bf_alice"},
        {"id": "bm_george"},
        {"id": "ef_dora"},
    ]
}


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/v1/audio/voices"):
            body = json.dumps(MOCK_VOICES).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):  # noqa: N802
        if self.path.startswith("/v1/audio/speech"):
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            assert payload.get("input"), "empty input"
            assert payload.get("voice"), "missing voice"
            time.sleep(0.05)
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(MOCK_WAV)))
            self.end_headers()
            self.wfile.write(MOCK_WAV)
        else:
            self.send_error(404)


class ModuleHarness:
    def __init__(self, config: str):
        self.proc = subprocess.Popen(
            [sys.executable, MODULE, config],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self.lines: queue.Queue[str] = queue.Queue()
        self.stderr: list[str] = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            log(f"<- {line}")
            self.lines.put(line)

    def _read_stderr(self):
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr.append(line.rstrip("\n"))

    def send(self, line: str) -> None:
        log(f"-> {line}")
        assert self.proc.stdin is not None
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def send_block(self, lines: list[str]) -> None:
        for line in lines:
            self.send(line)

    def read(self, timeout: float = 8.0) -> str:
        try:
            return self.lines.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError("timed out waiting for module output") from None

    def expect(self, prefix: str, timeout: float = 8.0) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.read(max(0.1, deadline - time.time()))
            if line.startswith(prefix):
                return line
        raise AssertionError(f"did not see {prefix!r}")

    def collect_message(self, timeout: float = 8.0) -> list[str]:
        """Read a multi-line protocol reply, ending with a 'NNN ' line."""
        lines = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.read(max(0.1, deadline - time.time()))
            lines.append(line)
            if len(line) >= 4 and line[3] == " ":
                return lines
        raise AssertionError("unterminated protocol reply")

    def close(self):
        if self.proc.poll() is None:
            try:
                self.send("QUIT")
            except Exception:  # noqa: BLE001
                pass
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self.stderr:
            print("  module stderr:")
            for line in self.stderr:
                print(f"    {line}")


def fake_player(directory: str) -> str:
    path = os.path.join(directory, "pw-play")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\nsleep \"${FAKE_PLAYER_SLEEP:-0.30}\"\nexit 0\n")
    os.chmod(path, 0o755)
    return path


def write_config(directory: str, url: str, player: str,
                 extra: str = "") -> str:
    path = os.path.join(directory, "kokoro-test.conf")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f'KokoroURL "{url}"\n')
        fh.write(f'KokoroPlayer "{player}"\n')
        fh.write('KokoroVoice "af_heart"\n')
        fh.write('KokoroChunkChars 80\n')
        fh.write(f'KokoroLog "{os.path.join(directory, "module.log")}"\n')
        fh.write('KokoroTimeout 5\n')
        fh.write(extra)
    return path


def run_tests(config: str) -> None:
    module = ModuleHarness(config)
    try:
        # -- initialization -------------------------------------------------
        module.send("INIT")
        init = module.collect_message()
        check(init[-1] == "299 OK LOADED SUCCESSFULLY",
              "INIT returns 299 OK LOADED SUCCESSFULLY")

        # -- audio settings: server audio must be refused -------------------
        module.send("AUDIO")
        check(module.expect("207").startswith("207"),
              "AUDIO acknowledges parameter block")
        module.send_block(["audio_output_method=server", "."])
        check(module.expect("303").startswith("303"),
              "server-side audio is refused (module plays its own audio)")

        module.send("AUDIO")
        module.expect("207")
        module.send_block([
            "audio_output_method=pulse",
            "audio_pulse_device=NULL",
            "audio_pulse_min_length=10",
            ".",
        ])
        check(module.expect("203").startswith("203"),
              "client-side audio settings are accepted")

        # -- loglevel -------------------------------------------------------
        module.send("LOGLEVEL")
        module.expect("207")
        module.send_block(["log_level=3", "."])
        check(module.expect("203").startswith("203"), "LOGLEVEL is accepted")

        # -- voices ---------------------------------------------------------
        module.send("LIST VOICES")
        voices = module.collect_message()
        check(voices[-1] == "200 OK VOICE LIST SENT", "full voice list is sent")
        check(any("-af_heart\t" in line for line in voices),
              "voice list contains af_heart")
        check(any("-am_michael\t" in line for line in voices),
              "voice list contains am_michael")

        module.send("LIST VOICES en-GB")
        british = module.collect_message()
        check(all(line[3] != "-" or "\ten-GB\t" in line for line in british),
              "language filter returns only en-GB voices")
        check(any("-bf_alice\t" in line for line in british),
              "language filter includes bf_alice")

        # -- settings -------------------------------------------------------
        module.send("SET")
        module.expect("203")
        module.send_block([
            "rate=0",
            "pitch=0",
            "pitch_range=0",
            "volume=100",
            "language=en-US",
            "voice=FEMALE1",
            "synthesis_voice=af_heart",
            "punctuation_mode=none",
            "spelling_mode=none",
            "cap_let_recogn=none",
            ".",
        ])
        check(module.expect("203").startswith("203"), "SET is accepted")

        # -- speaking -------------------------------------------------------
        module.send("SPEAK")
        check(module.expect("202").startswith("202"),
              "SPEAK acknowledges the message header")
        module.send_block(["Hello from the protocol test.", "."])
        check(module.expect("200").startswith("200 OK SPEAKING"),
              "SPEAK returns 200 OK SPEAKING")
        check(module.expect("701").startswith("701"), "begin event (701) is sent")
        check(module.expect("702").startswith("702"), "end event (702) is sent")

        # -- stop -----------------------------------------------------------
        module.send("SPEAK")
        module.expect("202")
        module.send_block([
            "This is a longer sentence so that playback is still active "
            "when the stop request arrives. " * 4,
            ".",
        ])
        module.expect("200")
        module.expect("701")
        module.send("STOP")
        check(module.expect("703").startswith("703"), "STOP produces 703 STOP")

        # -- pause ----------------------------------------------------------
        module.send("SPEAK")
        module.expect("202")
        module.send_block(["Another long sentence for the pause test. " * 8, "."])
        module.expect("200")
        module.expect("701")
        module.send("PAUSE")
        check(module.expect("704").startswith("704"), "PAUSE produces 704 PAUSE")

        # -- quit -----------------------------------------------------------
        module.send("QUIT")
        check(module.expect("210").startswith("210"), "QUIT produces 210 OK QUIT")
        module.proc.wait(timeout=5)
        check(module.proc.returncode == 0, "module exits cleanly after QUIT")
    finally:
        module.close()


def run_failure_test(config: str) -> None:
    """An unreachable endpoint must still complete the message (701/702)."""
    module = ModuleHarness(config)
    try:
        module.send("INIT")
        module.collect_message()
        module.send("SPEAK")
        module.expect("202")
        module.send_block(["This message cannot be synthesized.", "."])
        module.expect("200")
        check(module.expect("701").startswith("701"),
              "failed synthesis still reports begin")
        check(module.expect("702").startswith("702"),
              "failed synthesis still reports end")
        module.send("QUIT")
        module.expect("210")
    finally:
        module.close()


def run_language_tag_test(directory: str, url: str, player: str) -> None:
    """KokoroUniqueLangTags must decorate tags but not break filtering."""
    config = write_config(directory, url, player, "KokoroUniqueLangTags 1\n")
    module = ModuleHarness(config)
    try:
        module.send("INIT")
        module.collect_message()
        module.send("LIST VOICES")
        voices = module.collect_message()
        check(any("\ten-US-x-af-heart\t" in line for line in voices),
              "unique language tags contain the voice id")
        check(any("\ten-GB-x-bf-alice\t" in line for line in voices),
              "unique language tags keep the dialect")
        module.send("LIST VOICES en-GB")
        british = module.collect_message()
        check(any(line.endswith("\ten-GB-x-bf-alice\tfemale")
                  for line in british),
              "language filtering still works with unique tags")
        module.send("QUIT")
        module.expect("210")
    finally:
        module.close()


def main() -> int:
    global VERBOSE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", action="store_true",
                        help="use the real endpoint from kokoro.conf")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="show every protocol line")
    args = parser.parse_args()
    VERBOSE = args.verbose

    if not os.path.exists(MODULE):
        print(f"module not found: {MODULE}")
        return 2

    tempdir = tempfile.mkdtemp(prefix="spd-kokoro-test-")
    server = None
    try:
        player = fake_player(tempdir)
        if args.real:
            # Read the URL from the real config without parsing it here.
            url = "http://localhost:8880/v1/audio/speech"
            with open(CONFIG, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip().startswith("KokoroURL"):
                        url = line.split(None, 1)[1].strip().strip('"')
                        break
            print(f"Using real endpoint: {url}")
        else:
            server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/v1/audio/speech"
            print(f"Using mock endpoint: {url}")

        config = write_config(tempdir, url, player)
        run_tests(config)

        print("Unique language tags:")
        run_language_tag_test(tempdir, url, player)

        # Error path: an endpoint that refuses connections.
        failure_config = write_config(
            tempdir, "http://127.0.0.1:1/v1/audio/speech", player)
        print("Failure handling:")
        run_failure_test(failure_config)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        shutil.rmtree(tempdir, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} test(s) failed")
        return 1
    print("All protocol tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
