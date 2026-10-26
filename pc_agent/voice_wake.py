"""Hands-free Sora on the PC: say "Hey Sora" (or "Sora, …") and talk; it keeps listening after each
answer until you go quiet for a few seconds or say bye / thanks / ধন্যবাদ.

The mic is watched by Silero VAD (tiny, on the CPU), which cuts it into bits of speech, and by the
on-device "Hey Sora" model (wake_model.py, from scripts/wakeword/train.py). While waiting, a bit of
speech goes to the Sora server's /api/voice/wake — where the local Whisper checks it again and
hears what followed the name — only if the model heard its name in it. Without the model files
(or with WAKE_ENGINE=whisper in .env) every bit of speech goes to Whisper, as before. Nothing
leaves the PC. During a conversation, speech goes to /api/voice/turn and the spoken reply is
played back.

Needs: sounddevice, sherpa-onnx, httpx, and data/models/vad/silero_vad.onnx. It can be switched
off and on from the Windows app (Settings → Hey Sora) or by asking Sora; while off the mic is closed.
The choice is kept in data/pc_agent.json; WAKE_WORD=0 in .env makes off the default.
"""

from __future__ import annotations

import base64
import ctypes
import io
import json
import logging
import os
import queue
import tempfile
import threading
import time
import wave
from pathlib import Path

from corner_orb import orb

log = logging.getLogger("sora-voice")

ROOT = Path(__file__).resolve().parents[1]
VAD_MODEL = ROOT / "data" / "models" / "vad" / "silero_vad.onnx"
STATE_FILE = ROOT / "data" / "pc_agent.json"
WAKE_MODEL_DIR = ROOT / "data" / "models" / "wakeword"
RATE = 16000
WINDOW = 512  # Silero VAD frame (32 ms)
FOLLOW_UP_SECONDS = 8.0  # quiet this long during a conversation → back to waiting for the wake word
WAKE_CLIP_SECONDS = 4.0  # only the start of a long stretch of speech is checked for the wake word
NEW_CONVERSATION_AFTER = 15 * 60  # seconds; a later "Hey Sora" starts a fresh conversation


def available() -> str | None:
    """None if hands-free voice can run here, else why not."""
    try:
        import sherpa_onnx  # noqa: F401
        import sounddevice  # noqa: F401
        import httpx  # noqa: F401
    except ImportError as exc:
        return f"missing package: {exc.name}"
    if not VAD_MODEL.exists():
        return f"missing {VAD_MODEL}"
    return None


_on = threading.Event()  # set: listening for "Hey Sora"; clear: the mic is closed


def _load_enabled() -> bool:
    try:
        return bool(json.loads(STATE_FILE.read_text(encoding="utf-8"))["hey_sora"])
    except (OSError, ValueError, KeyError, TypeError):
        return os.environ.get("WAKE_WORD", "1").strip().lower() not in {"0", "false", "off", "no"}


def _wake_model():
    """The on-device "Hey Sora" model, or None (not trained yet, WAKE_ENGINE=whisper, or it won't load)."""
    if os.environ.get("WAKE_ENGINE", "model").strip().lower() == "whisper":
        return None
    if not (WAKE_MODEL_DIR / "hey_sora.onnx").exists():
        return None
    try:
        from wake_model import WakeModel

        return WakeModel(WAKE_MODEL_DIR)
    except Exception as exc:
        log.warning("on-device wake model not loaded (%s); every bit of speech goes to Whisper", exc)
        return None


def status() -> dict:
    problem = available()
    return {"enabled": _on.is_set(), "available": problem is None, "problem": problem,
            "engine": _engine}


_engine = "whisper"  # what decides "Hey Sora" was said: "model" (on this PC, then Whisper) or "whisper"


def set_enabled(on: bool) -> dict:
    """Turns "Hey Sora" on or off (off closes the mic) and remembers it."""
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    state["hey_sora"] = bool(on)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    if on:
        _on.set()
        orb.start()
    else:
        _on.clear()
        orb.stop()
    log.info("hands-free voice switched %s", "on" if on else "off")
    return status()


def _wav(samples) -> bytes:
    import numpy as np

    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def _tone(freqs: list[float], ms: int = 110, volume: float = 0.18) -> None:
    """Short chime: rising notes = listening, falling = done."""
    import numpy as np
    import sounddevice as sd

    parts = []
    for f in freqs:
        t = np.arange(int(24000 * ms / 1000)) / 24000
        env = np.minimum(1, np.minimum(t, t[::-1]) * 60)  # soft attack/release, no clicks
        parts.append(np.sin(2 * np.pi * f * t) * env * volume)
    sd.play(np.concatenate(parts).astype(np.float32), 24000, blocking=True)


_playing = threading.Lock()  # a voice reply and a routine's result take turns (one MCI alias)


def _play_mp3(data: bytes) -> None:
    """Plays MP3 bytes through Windows' MCI (no decoder needed) and waits until it finishes."""
    mci = ctypes.windll.winmm.mciSendStringW
    fd, path = tempfile.mkstemp(suffix=".mp3")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        with _playing:
            mci(f'open "{path}" type mpegvideo alias sora_reply', None, 0, None)
            mci("play sora_reply wait", None, 0, None)
            mci("close sora_reply", None, 0, None)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def say(params: dict) -> dict:
    """Says something aloud on this PC (a routine's result): plays the MP3 the server made."""
    audio = params.get("audio_mp3_base64")
    if not audio:
        raise ValueError("no audio to play")
    _play_mp3(base64.b64decode(audio))
    return {"said": True}


class VoiceLoop:
    def __init__(self, server: str, token: str):
        import httpx

        self.server = server.rstrip("/")
        self.http = httpx.Client(timeout=120, headers={"Authorization": f"Bearer {token}"})
        self.audio: queue.Queue = queue.Queue()
        self.conversation: str | None = None
        self.last_turn = 0.0
        self.listening_until = 0.0  # > now: in a conversation, waiting for the next thing said
        global _engine
        self.wake = _wake_model()
        _engine = "model" if self.wake else "whisper"
        # the model's score that counts as hearing its name (WAKE_THRESHOLD in .env)
        self.threshold = float(os.environ.get("WAKE_THRESHOLD") or 0.5)
        # Time counted in mic samples, not by the clock, so it stays right when the PC is busy.
        self.samples = 0  # heard so far
        self.name_heard_at = -10**9  # sample count when the on-device model last heard "Hey Sora"
        self.skipped = 0  # bits of speech not sent to the server since the last log line
        log.info("wake word decided by %s", "the on-device model, then Whisper" if self.wake else "Whisper")

    # ------------------------------------------------------------ mic and VAD

    def _vad(self, silence: float):
        """Cuts the mic into bits of speech; a bit ends after [silence] seconds of quiet."""
        import sherpa_onnx as so

        c = so.VadModelConfig()
        c.silero_vad.model = str(VAD_MODEL)
        c.silero_vad.threshold = 0.5
        c.silero_vad.min_silence_duration = silence
        c.silero_vad.min_speech_duration = 0.25
        c.silero_vad.max_speech_duration = 20
        c.sample_rate = RATE
        return so.VoiceActivityDetector(c, buffer_size_in_seconds=60)

    def run(self) -> None:
        import sounddevice as sd

        # Waiting for "Hey Sora": a short pause ends a bit, so it answers quickly. In a conversation a
        # longer one, so "আব্বুকে… ফোন দাও" with a breath after the name stays one request.
        vads = (self._vad(0.6), self._vad(1.2))

        def on_audio(indata, frames, t, status):
            self.audio.put(indata[:, 0].copy())

        while True:
            _on.wait()
            try:
                with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=WINDOW, callback=on_audio):
                    log.info("hands-free voice on: say \"Hey Sora\"")
                    self._listen(vads)
                log.info("hands-free voice off: mic closed")
            except Exception as exc:  # mic unplugged, device busy...
                log.warning("voice loop stopped (%s); retrying in 10 s", exc)
                time.sleep(10)

    def _listen(self, vads) -> None:
        """Until "Hey Sora" is switched off."""
        wake_vad, talk_vad = vads
        while True:
            vad = talk_vad if self.listening_until else wake_vad
            if not _on.is_set():
                self.listening_until = 0.0
                orb.hide()
                self._drain()
                wake_vad.reset()
                talk_vad.reset()
                return
            try:
                chunk = self.audio.get(timeout=0.5)
            except queue.Empty:
                continue
            vad.accept_waveform(chunk)
            self.samples += len(chunk)
            if self.wake is not None and not self.listening_until and self.wake(chunk) > self.threshold:
                self.name_heard_at = self.samples
                orb.show("listening")  # it heard its name: show so at once, before the server has had its say
            orb.level(chunk)
            while not vad.empty():
                segment = vad.front.samples
                vad.pop()
                if self._handle(segment):
                    # We were busy (server, speaking): forget what the mic heard meanwhile — that was
                    # mostly Sora's own voice — and start fresh.
                    self._drain()
                    wake_vad.reset()
                    talk_vad.reset()
                    if self.wake is not None:
                        self.wake.reset()
            if self.listening_until and time.time() > self.listening_until and not vad.is_speech_detected():
                self._end_conversation()

    def _drain(self) -> None:
        while not self.audio.empty():
            try:
                self.audio.get_nowait()
            except queue.Empty:
                break

    # ------------------------------------------------------------ talking to the server

    def _post(self, path: str, samples, **form) -> dict | None:
        files = {"audio": ("speech.wav", _wav(samples), "audio/wav")}
        data = {k: v for k, v in form.items() if v is not None}
        try:
            resp = self.http.post(f"{self.server}{path}", files=files, data=data)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            log.warning("%s failed: %s", path, exc)
            return None

    def _handle(self, segment) -> bool:
        """Returns True if it did something (so audio heard meanwhile should be dropped)."""
        seconds = len(segment) / RATE
        if seconds < 0.35:
            return False
        if not self.listening_until:  # waiting for the wake word
            # The model scores the end of the name while it's being said; the bit of speech comes out of
            # the VAD a little later, once there's a pause.
            if self.wake is not None and (self.samples - self.name_heard_at) / RATE > seconds + 1.0:
                self.skipped += 1
                if self.skipped % 50 == 0:
                    log.info("%d bits of speech without \"Hey Sora\" kept off the server", self.skipped)
                return False
            if time.time() - self.last_turn > NEW_CONVERSATION_AFTER:
                self.conversation = None
            if orb.state != "hide":
                orb.show("thinking")  # only once the model heard the name: not for every bit of speech
            result = self._post("/api/voice/wake", segment[: int(RATE * WAKE_CLIP_SECONDS)],
                                conversation_id=self.conversation)
            if not result or not result.get("wake"):
                orb.hide()
                if self.wake is not None:
                    log.info("model heard its name, Whisper didn't: %r", (result or {}).get("transcript"))
                return False
            log.info("wake: %r", result.get("transcript"))
            if result.get("reply"):
                orb.show("speaking")
                self._speak(result)
            else:
                _tone([660, 880])
            self._start_listening()
            return True
        orb.show("thinking")
        result = self._post("/api/voice/turn", segment, conversation_id=self.conversation)
        if result is None:
            _tone([440, 330])
            self._start_listening()
            return True
        status = result.get("status")
        if status == "end":
            log.info("conversation ended by %r", result.get("transcript"))
            self._end_conversation()
            return True
        if status == "empty" or not result.get("reply"):
            self._start_listening()
            return True
        log.info("you: %r", result.get("transcript"))
        orb.show("speaking")
        self._speak(result)
        self._start_listening()
        return True

    def _speak(self, result: dict) -> None:
        self.conversation = result.get("conversation_id") or self.conversation
        self.last_turn = time.time()
        audio = result.get("audio_mp3_base64")
        if audio:
            _play_mp3(base64.b64decode(audio))

    def _start_listening(self) -> None:
        self.listening_until = time.time() + FOLLOW_UP_SECONDS
        orb.show("listening")

    def _end_conversation(self) -> None:
        self.listening_until = 0.0
        orb.hide()
        self.last_turn = time.time()
        _tone([880, 660])
        log.info("waiting for \"Hey Sora\" again")


def start(server: str, token: str) -> threading.Thread | None:
    """Starts hands-free voice in a background thread (it waits while switched off), unless it can't
    run here."""
    problem = available()
    if problem:
        log.warning("hands-free voice not started: %s", problem)
        return None
    if _load_enabled():
        _on.set()
        orb.start()
    else:
        log.info("hands-free voice is off (turn it on in the Sora app's Settings)")
    thread = threading.Thread(target=VoiceLoop(server, token).run, name="sora-voice", daemon=True)
    thread.start()
    return thread
