"""Speech-to-text and text-to-speech.

Speech-to-text runs on the server for every client (Whisper: local GPU or a hosted API), so
Bangla, English and a mix of both are understood the same on any phone or PC. Speech is
Edge neural TTS.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import logging
import os
import re
import wave
from pathlib import Path

import httpx

from sora.config import get_settings
from sora.textutil import has_bengali

log = logging.getLogger(__name__)


class VoiceError(RuntimeError):
    pass


_local_model = None


def _add_cuda_dlls() -> None:
    """On Windows the CUDA libraries come from the nvidia-* pip packages; let ctranslate2 find them."""
    if os.name != "nt":
        return
    try:
        import nvidia
    except ImportError:
        return
    for root in nvidia.__path__:
        for lib in Path(root).iterdir():
            bin_dir = lib / "bin"
            if bin_dir.is_dir():
                os.add_dll_directory(str(bin_dir))
                os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


def _load_local_model():
    global _local_model
    if _local_model is None:
        try:
            import ctranslate2
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise VoiceError("STT_PROVIDER=local needs `pip install -e backend[local-stt]`") from exc
        s = get_settings()
        if s.whisper_model_dir:
            os.environ.setdefault("HF_HOME", str(Path(s.whisper_model_dir) / "hf"))
        _add_cuda_dlls()
        gpu = ctranslate2.get_cuda_device_count() > 0
        options = dict(device="cuda" if gpu else "cpu", compute_type="float16" if gpu else "int8",
                       download_root=s.whisper_model_dir or None)
        try:
            # The copy on disk, without asking Hugging Face first: that check, on every load, once
            # re-linked the model's files while it was being opened and voice failed until a restart.
            _local_model = WhisperModel(s.whisper_local_model, local_files_only=True, **options)
        except Exception:
            log.info("local whisper %s isn't on this PC yet: downloading it", s.whisper_local_model)
            _local_model = WhisperModel(s.whisper_local_model, **options)
        log.info("local whisper %s loaded on %s", s.whisper_local_model, "GPU" if gpu else "CPU")
    return _local_model


def _decode_audio(data: bytes):
    """Any audio file → 16 kHz mono float32 samples. The apps send 16 kHz WAV, read without a decoder."""
    import numpy as np

    try:
        with wave.open(io.BytesIO(data)) as w:
            if (w.getsampwidth(), w.getnchannels(), w.getframerate()) == (2, 1, 16000):
                return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    except (wave.Error, EOFError):
        pass
    import av

    chunks = []
    try:
        with av.open(io.BytesIO(data)) as container:
            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
            for frame in container.decode(audio=0):
                chunks += [f.to_ndarray().reshape(-1) for f in resampler.resample(frame)]
            chunks += [f.to_ndarray().reshape(-1) for f in resampler.resample(None)]
    except av.FFmpegError as exc:
        raise VoiceError(f"could not read the audio: {exc}") from exc
    if not chunks:
        return np.zeros(0, np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768


def wav_16k(data: bytes) -> bytes:
    """Any audio file → 16 kHz mono 16-bit WAV (how "Hey Sora" training samples are kept)."""
    import numpy as np

    pcm = (np.clip(_decode_audio(data), -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    return buf.getvalue()


def _pick_language(model, audio) -> str:
    """Bangla or English. Whisper rarely gives "bn" much weight — Bangla speech, and short English
    commands in a Bangladeshi accent, score as Hindi or Urdu — while clear English it is sure of
    (0.9+). So: English when it is clearly English, Bangla otherwise. In Bangla mode large-v3 writes
    stray English words in Bangla letters by sound ("সোরা কল টাস্টিট"), which Sora is told to read
    by sound; English mode would garble the Bangla instead."""
    _lang, _p, probs = model.detect_language(audio)
    return "en" if dict(probs).get("en", 0.0) >= 0.6 else "bn"


def _transcribe_local(data: bytes, language: str | None, hotwords: str | None = None) -> str:
    import numpy as np

    model = _load_local_model()
    audio = _decode_audio(data)
    if audio.size < 16000 * 0.3:  # under 0.3 s: nothing to recognise
        return ""
    if hotwords:
        # Whisper tends to drop a clip's very first word ("Sora, open YouTube" → "Open YouTube");
        # half a second of silence in front keeps it.
        audio = np.concatenate([np.zeros(8000, dtype=audio.dtype), audio])
    if not language:
        language = _pick_language(model, audio)
    segments, _info = model.transcribe(audio, language=language, vad_filter=not hotwords, beam_size=5,
                                       condition_on_previous_text=False, hotwords=hotwords or None)
    return " ".join(seg.text.strip() for seg in segments).strip()


def stt_ready() -> bool:
    """Whether server speech-to-text can work as configured (checked without loading anything)."""
    s = get_settings()
    provider = s.stt_provider.lower()
    if provider == "none":
        return False
    if provider == "local":
        return importlib.util.find_spec("faster_whisper") is not None
    return bool(s.stt_api_key)


async def warm_up() -> None:
    """Load the local model in the background at start-up so the first voice turn isn't slow."""
    if get_settings().stt_provider.lower() == "local" and stt_ready():
        try:
            await asyncio.to_thread(_load_local_model)
        except Exception:
            log.exception("could not load the local whisper model")


async def transcribe(data: bytes, filename: str = "audio.webm", language: str | None = None,
                     hotwords: str | None = None) -> str:
    """[hotwords] (local Whisper only) nudges recognition towards a name, e.g. "Sora" for the wake word."""
    s = get_settings()
    language = language or s.stt_language or None
    provider = s.stt_provider.lower()
    if provider == "none":
        raise VoiceError("Server-side speech-to-text is disabled (STT_PROVIDER=none).")
    if provider == "local":
        return await asyncio.to_thread(_transcribe_local, data, language, hotwords)
    if not s.stt_api_key:
        raise VoiceError("STT_API_KEY is not set in .env")
    form = {"model": s.stt_model, "response_format": "json"}
    if language:
        form["language"] = language
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{s.stt_base_url.rstrip('/')}/audio/transcriptions",
            headers={"Authorization": f"Bearer {s.stt_api_key}"},
            data=form,
            files={"file": (filename, data)},
        )
    if resp.status_code >= 400:
        raise VoiceError(f"transcription failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json().get("text", "").strip()


def speakable(text: str) -> str:
    """Strip markdown and links so TTS doesn't read symbols aloud."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_#>`|]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


async def synthesize(text: str, voice: str | None = None, rate: str = "+0%") -> bytes:
    import edge_tts

    s = get_settings()
    clean = speakable(text)
    if not clean:
        raise VoiceError("nothing to speak")
    voice = voice or (s.tts_voice_bn if has_bengali(clean) else s.tts_voice_en)
    communicate = edge_tts.Communicate(clean, voice, rate=rate)
    audio = bytearray()
    try:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
    except Exception as exc:
        raise VoiceError(f"text-to-speech failed: {exc}") from exc
    if not audio:
        raise VoiceError("text-to-speech returned no audio")
    return bytes(audio)
