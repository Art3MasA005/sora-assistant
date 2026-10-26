"""Server-side voice for clients that can't do STT/TTS on device (the Windows app)."""

from __future__ import annotations

import base64
import uuid
import hashlib
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from sora.agent.runner import Origin, get_agent
from sora.api.deps import collect, current_device
from sora.config import get_settings
from sora.models import Device
from sora.services.voice import VoiceError, synthesize, transcribe, wav_16k
from sora.textutil import is_goodbye, wake_match

router = APIRouter(prefix="/api/voice", tags=["voice"])

MAX_AUDIO_BYTES = 25 * 1024 * 1024


async def _read_audio(audio: UploadFile) -> bytes:
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio is larger than 25 MB")
    if not data:
        raise HTTPException(400, "Empty audio")
    return data


@router.post("/transcribe")
async def transcribe_audio(audio: UploadFile = File(...), language: str | None = Form(None),
                           device: Device = Depends(current_device)):
    data = await _read_audio(audio)
    try:
        return {"text": await transcribe(data, audio.filename or "audio.webm", language)}
    except VoiceError as exc:
        raise HTTPException(502, str(exc)) from exc


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    voice: str | None = Field(None, description="Edge TTS voice name; default picks Bangla or English automatically.")
    rate: str = Field("+0%", pattern=r"^[+-]\d{1,3}%$")


@router.post("/speak", response_class=Response, responses={200: {"content": {"audio/mpeg": {}}}})
async def speak(body: SpeakIn, device: Device = Depends(current_device)):
    try:
        audio = await synthesize(body.text, body.voice, body.rate)
    except VoiceError as exc:
        raise HTTPException(502, str(exc)) from exc
    return Response(audio, media_type="audio/mpeg")


async def _agent_turn(text: str, conversation_id: uuid.UUID | None, device: Device, speak_reply: bool) -> dict:
    result = await collect(
        get_agent().chat(text, conversation_id, Origin(device_id=device.id, kind=device.kind, voice=True))
    )
    result["transcript"] = text
    if speak_reply and result["reply"]:
        try:
            result["audio_mp3_base64"] = base64.b64encode(await synthesize(result["reply"])).decode()
        except VoiceError as exc:
            result["tts_error"] = str(exc)
    return result


@router.post("/turn")
async def voice_turn(audio: UploadFile = File(...), conversation_id: uuid.UUID | None = Form(None),
                     language: str | None = Form(None), speak_reply: bool = Form(True),
                     device: Device = Depends(current_device)):
    """One voice round trip: audio in → transcript → agent → reply text (+ MP3 as base64).

    status "empty" = nothing was said; "end" = the owner said bye/thanks, so a hands-free
    conversation should stop listening (the agent is not called)."""
    data = await _read_audio(audio)
    try:
        text = await transcribe(data, audio.filename or "audio.webm", language)
    except VoiceError as exc:
        raise HTTPException(502, str(exc)) from exc
    if not text:
        return {"transcript": "", "reply": "", "status": "empty", "events": []}
    if is_goodbye(text):
        return {"transcript": text, "reply": "", "status": "end", "events": []}
    return await _agent_turn(text, conversation_id, device, speak_reply)


@router.post("/wake")
async def voice_wake(audio: UploadFile = File(...), conversation_id: uuid.UUID | None = Form(None),
                     speak_reply: bool = Form(True), device: Device = Depends(current_device)):
    """Is this short clip someone calling Sora? The apps send each bit of speech they hear while
    waiting for the wake word. {"wake": false} = ignore it. {"wake": true} with no reply = start
    listening; if a request followed in the same breath ("Hey Sora, what's the time?"), it is
    answered right away like /turn."""
    data = await _read_audio(audio)
    name = audio.filename or "audio.wav"
    try:
        # Checked in English mode: it writes "Sora" reliably even in Bangla speech ("Sora youtube
        # kholo"), where Bangla mode with the hotword garbles.
        heard = await transcribe(data, name, "en", hotwords="Sora")
        woke, command = wake_match(heard)
        if not woke:
            return {"wake": False, "transcript": heard}
        if len(command) >= 3:
            # A request followed: transcribe it properly (Bangla in Bangla script).
            full = await transcribe(data, name)
            again, rest = wake_match(full)
            command = rest if again else full
    except VoiceError as exc:
        raise HTTPException(502, str(exc)) from exc
    if len(command) < 3:
        return {"wake": True, "transcript": heard, "reply": "", "status": "listening", "events": []}
    return {"wake": True, **await _agent_turn(command, conversation_id, device, speak_reply)}


# ---------------------------------------------------------------- "Hey Sora" training samples

SAMPLE_KINDS = ("positive", "negative")  # the owner saying "Hey Sora" / something else


def samples_dir() -> Path:
    """data/wakeword/recorded/<kind>/<device kind>-<device id>-<time>.wav: the owner's own voice for
    training the on-device "Hey Sora" model (scripts/wakeword). The file name keeps which device's
    microphone it came from."""
    return get_settings().data_dir / "wakeword" / "recorded"


def _sample_counts(device: Device) -> dict:
    mine = f"{device.kind}-{device.id.hex[:8]}-"
    out: dict = {}
    for kind in SAMPLE_KINDS:
        files = list((samples_dir() / kind).glob("*.wav"))
        out[kind] = {"total": len(files), "this_device": sum(f.name.startswith(mine) for f in files)}
    return out


@router.get("/wake-samples")
async def wake_samples(device: Device = Depends(current_device)):
    """How many "Hey Sora" (positive) and other (negative) recordings there are, in all and from this device."""
    return _sample_counts(device)


@router.post("/wake-samples")
async def add_wake_sample(audio: UploadFile = File(...), kind: str = Form(...), device: Device = Depends(current_device)):
    if kind not in SAMPLE_KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(SAMPLE_KINDS)}")
    data = await _read_audio(audio)
    try:
        wav = wav_16k(data)
    except VoiceError as exc:
        raise HTTPException(400, str(exc)) from exc
    if len(wav) < 44 + 16000:  # under half a second
        raise HTTPException(400, "The recording is too short")
    folder = samples_dir() / kind
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    (folder / f"{device.kind}-{device.id.hex[:8]}-{stamp}.wav").write_bytes(wav)
    return _sample_counts(device)


@router.delete("/wake-samples/last")
async def undo_wake_sample(device: Device = Depends(current_device)):
    """Removes this device's newest recording (a bad take)."""
    mine = f"{device.kind}-{device.id.hex[:8]}-"
    files = [f for kind in SAMPLE_KINDS for f in (samples_dir() / kind).glob(f"{mine}*.wav")]
    if files:
        max(files, key=lambda f: f.name[len(mine):]).unlink()
    return _sample_counts(device)


# ---------------------------------------------------------------- the on-device "Hey Sora" model

WAKE_MODEL_FILES = ("melspectrogram.onnx", "embedding_model.onnx", "hey_sora.onnx")


def wake_model_dir() -> Path:
    return get_settings().data_dir / "models" / "wakeword"


@router.get("/wake-model")
async def wake_model(device: Device = Depends(current_device)):
    """The model the phone app runs to hear "Hey Sora" by itself (scripts/wakeword/train.py makes it).
    `version` changes with every retrain, so the app downloads the files again only then."""
    folder = wake_model_dir()
    if not all((folder / name).is_file() for name in WAKE_MODEL_FILES):
        raise HTTPException(404, "no wake-word model has been trained yet")
    digest = hashlib.sha1()
    for name in WAKE_MODEL_FILES:
        digest.update((folder / name).read_bytes())
    return {"version": digest.hexdigest()[:12], "threshold": get_settings().wake_threshold, "files": list(WAKE_MODEL_FILES)}


@router.get("/wake-model/{name}")
async def wake_model_file(name: str, device: Device = Depends(current_device)):
    if name not in WAKE_MODEL_FILES or not (wake_model_dir() / name).is_file():
        raise HTTPException(404, "not found")
    return FileResponse(wake_model_dir() / name, media_type="application/octet-stream")
