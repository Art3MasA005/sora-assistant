"""Hears "Hey Sora" right on this PC, without the server: the same steps as openWakeWord's streaming
code, with onnxruntime only (the Android app does the same in Dart).

Every 80 ms of 16 kHz audio (1280 samples, plus the 480 before it):
  melspectrogram.onnx → 8 mel frames (each /10 + 2)
  embedding_model.onnx on the last 76 mel frames → 96 numbers
  hey_sora.onnx on the last 16 of those (1.28 s) → how sure it is, 0..1

The model files live in data/models/wakeword/ (scripts/wakeword/train.py puts them there).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

CHUNK = 1280  # 80 ms
CONTEXT = 480  # earlier samples the mel model needs to give 8 frames for a chunk
MEL_FRAMES, FEATURE_FRAMES = 76, 16


class WakeModel:
    def __init__(self, folder: Path, name: str = "hey_sora"):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = opts.inter_op_num_threads = 1  # tiny models: one core is plenty

        def load(file: str):
            return ort.InferenceSession(str(folder / file), sess_options=opts, providers=["CPUExecutionProvider"])

        self._mel, self._emb, self._wake = load("melspectrogram.onnx"), load("embedding_model.onnx"), load(f"{name}.onnx")
        self.reset()

    def reset(self) -> None:
        """Forget what was heard (after a wake, or after Sora spoke)."""
        self._pending = np.zeros(0, np.int16)
        self._raw = np.zeros(CONTEXT, np.int16)
        self._mels = np.ones((MEL_FRAMES, 32), np.float32)
        noise = np.random.default_rng(0).integers(-1000, 1000, CHUNK * 50).astype(np.int16)
        self._feats = np.zeros((0, 96), np.float32)
        self._warm = 0
        for i in range(0, len(noise), CHUNK):  # start from background-like features, as openWakeWord does
            self._step(noise[i : i + CHUNK])
        self._warm = 0

    def _step(self, chunk: np.ndarray) -> float:
        audio = np.concatenate([self._raw, chunk])
        self._raw = audio[-CONTEXT:]
        mel = self._mel.run(None, {"input": audio[None].astype(np.float32)})[0].squeeze() / 10 + 2
        self._mels = np.vstack([self._mels, mel])[-MEL_FRAMES * 2 :]
        emb = self._emb.run(None, {"input_1": self._mels[-MEL_FRAMES:][None, :, :, None]})[0].reshape(1, 96)
        self._feats = np.vstack([self._feats, emb])[-FEATURE_FRAMES * 2 :]
        self._warm += 1
        if len(self._feats) < FEATURE_FRAMES or self._warm < 5:  # the first few frames aren't reliable
            return 0.0
        x = self._feats[-FEATURE_FRAMES:][None].astype(np.float32)
        return float(self._wake.run(None, {"input": x})[0].reshape(-1)[0])

    def __call__(self, pcm: np.ndarray) -> float:
        """Feed 16 kHz audio (int16, or float in -1..1); returns the highest score among the 80 ms steps
        it completed (0 if none)."""
        if pcm.dtype != np.int16:
            pcm = (np.clip(pcm, -1, 1) * 32767).astype(np.int16)
        self._pending = np.concatenate([self._pending, pcm])
        best = 0.0
        while len(self._pending) >= CHUNK:
            chunk, self._pending = self._pending[:CHUNK], self._pending[CHUNK:]
            best = max(best, self._step(chunk))
        return best
