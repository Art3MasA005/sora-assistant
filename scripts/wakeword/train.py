"""Train the on-device "Hey Sora" wake-word model, in openWakeWord's format: Google's speech
embedding (openWakeWord's melspectrogram.onnx + embedding_model.onnx, shared by every wake word)
turns audio into 96 numbers per 80 ms; this trains the small part on top that looks at the last
16 of them (1.28 s) and says how sure it is that someone just said "Hey Sora".

Run it with the training venv (data/wakeword/.venv: openwakeword, with PyTorch borrowed from the
sedld conda env through --system-site-packages):

    data\\wakeword\\.venv\\Scripts\\python scripts\\wakeword\\train.py
    data\\wakeword\\.venv\\Scripts\\python scripts\\wakeword\\train.py --refresh   # recompute features

Inputs, in data/wakeword/:
  synthetic/{positive,negative}/*.wav    make_synthetic.py (Edge TTS voices)
  recorded/{positive,negative}/*.wav     the owner (app: Settings → Voice → Teach Sora your voice)
  features/acav_part.npy                 general audio as features: negatives (first part of
                                         openWakeWord's ACAV100M set)
  features/validation_set_features.npy   ~11 h of general audio: only to count false wakes per hour
Output: data/models/wakeword/hey_sora.onnx and report.json (recall, false wakes per hour, the
threshold to use).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
import wave
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "wakeword"
OUT = ROOT / "data" / "models" / "wakeword"
SR = 16000
WIN = 2 * SR  # each training example is 2 s of audio; the model sees its last 16 embedding frames
FRAMES = 16

rng = np.random.default_rng(1)


# ------------------------------------------------------------------ audio

def load(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        assert w.getframerate() == SR and w.getnchannels() == 1 and w.getsampwidth() == 2, path
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


def trim(x: np.ndarray) -> np.ndarray:
    """Cuts the silence around the speech (20 ms frames quieter than 35 dB under the loudest)."""
    n = len(x) // 320
    if n < 3:
        return x
    db = 10 * np.log10(np.mean(x[: n * 320].reshape(n, 320) ** 2, axis=1) + 1e-10)
    loud = np.where(db > db.max() - 35)[0]
    return x[max(0, loud[0] - 2) * 320 : min(n, loud[-1] + 3) * 320]


def colored_noise(n: int) -> np.ndarray:
    """White, pink or brown noise."""
    spectrum = np.fft.rfft(rng.standard_normal(n))
    f = np.arange(len(spectrum)) + 1.0
    spectrum /= f ** rng.choice([0.0, 0.5, 1.0])
    x = np.fft.irfft(spectrum, n)
    return x / (np.abs(x).max() + 1e-9)


def reverb(x: np.ndarray) -> np.ndarray:
    """A made-up room: noise that dies away over 0.15–0.7 s."""
    from scipy.signal import fftconvolve

    rt60 = rng.uniform(0.15, 0.7)
    t = np.arange(int(rt60 * SR)) / SR
    ir = rng.standard_normal(len(t)) * np.exp(-6.9 * t / rt60)
    ir[0] = 1.0
    y = fftconvolve(x, ir)[: len(x)]
    return y / (np.abs(y).max() + 1e-9) * (np.abs(x).max() + 1e-9)


def lowpass(x: np.ndarray) -> np.ndarray:
    from scipy.signal import butter, sosfilt

    return sosfilt(butter(4, rng.uniform(3000, 7000), fs=SR, output="sos"), x)


class Mixer:
    """Puts a clip into a 2 s window over background sound and makes it sound like a real mic."""

    def __init__(self, babble: list[np.ndarray]):
        self.babble = babble  # other speech, played quietly behind

    def background(self) -> np.ndarray:
        r = rng.random()
        if r < 0.45:
            return colored_noise(WIN)
        if r < 0.75 and self.babble:
            b = np.concatenate([self.babble[i] for i in rng.integers(0, len(self.babble), 4)])
            b = np.pad(b, (0, max(0, WIN - len(b))))
            start = rng.integers(0, len(b) - WIN + 1)
            return b[start : start + WIN] / (np.abs(b).max() + 1e-9)
        return colored_noise(WIN) * 0.05  # a quiet room

    def window(self, clip: np.ndarray | None, end_at: int | None = None) -> np.ndarray:
        """[clip] ends [end_at] samples into the window (random if None); None = background only."""
        x = np.zeros(WIN, np.float32)
        if clip is not None:
            clip = clip[-WIN:]
            if rng.random() < 0.4:
                clip = reverb(clip)
            end = end_at if end_at is not None else rng.integers(len(clip), WIN + 1)
            clip = clip[-end:]
            x[end - len(clip) : end] = clip
            peak = np.abs(x).max() + 1e-9
        else:
            peak = 0.3
        if rng.random() < 0.85:
            snr = rng.uniform(3, 30)
            bg = self.background()
            speech_rms = np.sqrt(np.mean(x[x != 0] ** 2)) if clip is not None else peak / 4
            x = x + bg / (np.sqrt(np.mean(bg**2)) + 1e-9) * speech_rms / (10 ** (snr / 20))
        if rng.random() < 0.3:
            x = lowpass(x)
        x = x / (np.abs(x).max() + 1e-9) * rng.uniform(0.05, 0.9)
        return (x * 32767).astype(np.int16)


# ------------------------------------------------------------------ datasets

def files(kind: str) -> tuple[list[Path], list[Path]]:
    syn = sorted((DATA / "synthetic" / kind).glob("*.wav"))
    rec = sorted((DATA / "recorded" / kind).glob("*.wav"))
    return syn, rec


def is_test(path: Path, synthetic: bool) -> bool:
    """Held out from training: some whole TTS voices, and every fifth recording of the owner."""
    key = "-".join(path.stem.split("-")[:3]) if synthetic else path.stem
    return zlib.crc32(key.encode()) % (7 if synthetic else 5) == 0


REC_COPIES = 10  # augmented copies of each of the owner's recordings (--rec-copies)


def build_audio(test: bool) -> dict[str, np.ndarray]:
    """2 s windows as int16: positive / negative (incl. cut-off "Hey So…" and plain background); for
    the test split also owner_positive, the owner's own held-out takes."""
    syn_pos, rec_pos = files("positive")
    syn_neg, rec_neg = files("negative")
    pick = lambda fs, syn: [f for f in fs if is_test(f, syn) == test]  # noqa: E731
    owner = [trim(load(f)) for f in pick(rec_pos, False)]
    pos = [(trim(load(f)), 4) for f in pick(syn_pos, True)] + [(c, REC_COPIES) for c in owner]
    neg = [(trim(load(f)), 2) for f in pick(syn_neg, True)] + [(trim(load(f)), max(2, REC_COPIES // 2))
                                                                 for f in pick(rec_neg, False)]
    mixer = Mixer([c for c, _ in neg])
    if test:  # one plain copy each: what the model must get right
        pos, neg = [(c, 1) for c, _ in pos], [(c, 1) for c, _ in neg]

    positive = []
    for clip, copies in pos:
        for _ in range(copies):
            # the name ends 0.05–0.35 s before the end of the window, as when the mic stream is checked live
            positive.append(mixer.window(clip, WIN - int(rng.uniform(0.05, 0.35) * SR)))
    negative = []
    for clip, copies in neg:
        for _ in range(copies):
            negative.append(mixer.window(clip))
    for clip, _ in pos:  # the name cut off half-way ("Hey So…") is not the name
        negative.append(mixer.window(clip[: int(len(clip) * rng.uniform(0.35, 0.55))]))
    for _ in range(len(pos) // (1 if test else 2)):
        negative.append(mixer.window(None))
    out = {"positive": np.stack(positive), "negative": np.stack(negative)}
    if test and owner:
        out["owner_positive"] = np.stack([mixer.window(c, WIN - int(0.2 * SR)) for c in owner])
    return out


def embed(audio: np.ndarray) -> np.ndarray:
    from openwakeword.utils import AudioFeatures

    feats = AudioFeatures(inference_framework="onnx", ncpu=8)
    out = feats.embed_clips(audio, batch_size=64, ncpu=8)
    return out[:, -FRAMES:, :].astype(np.float32)


def features(refresh: bool) -> dict[str, np.ndarray]:
    """Embeddings for train/test positives and negatives, cached until the clips change."""
    listing = f"{REC_COPIES}|" + "".join(str(p) for k in ("positive", "negative") for fs in files(k) for p in fs)
    key = hashlib.sha1(listing.encode()).hexdigest()[:10]
    cache = DATA / "cache" / f"features-{key}.npz"
    if cache.exists() and not refresh:
        return dict(np.load(cache))
    out = {}
    for split in ("train", "test"):
        t0 = time.time()
        audio = build_audio(split == "test")
        for kind, x in audio.items():
            out[f"{split}_{kind}"] = embed(x)
        print(f"{split}: {len(audio['positive'])} positive, {len(audio['negative'])} negative windows "
              f"({time.time() - t0:.0f} s)", flush=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, **out)
    return out


def open_npy(path: Path) -> np.ndarray:
    """A (possibly cut-short) .npy of shape (N, 16, 96) as a memory map of the whole rows it has."""
    with open(path, "rb") as fh:
        version = np.lib.format.read_magic(fh)
        shape, fortran, dtype = np.lib.format._read_array_header(fh, version)
        offset = fh.tell()
    row = int(np.prod(shape[1:])) * np.dtype(dtype).itemsize
    rows = min(shape[0], (path.stat().st_size - offset) // row)
    return np.memmap(path, dtype=dtype, mode="r", offset=offset, shape=(rows, *shape[1:]))


# ------------------------------------------------------------------ model

def make_model():
    import torch.nn as nn

    # openWakeWord's own "dnn" shape: small, fast on a phone
    return nn.Sequential(
        nn.Flatten(),
        nn.Linear(FRAMES * 96, 128), nn.LayerNorm(128), nn.ReLU(),
        nn.Linear(128, 128), nn.LayerNorm(128), nn.ReLU(),
        nn.Linear(128, 1),
    )


def scores(model, x: np.ndarray, batch: int = 4096) -> np.ndarray:
    import torch

    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(x), batch):
            xb = torch.from_numpy(np.asarray(x[i : i + batch], np.float32)).cuda()
            out.append(torch.sigmoid(model(xb)).squeeze(1).cpu().numpy())
    model.train()
    return np.concatenate(out) if out else np.zeros(0)


def false_wakes(s: np.ndarray, threshold: float) -> int:
    """Separate wakes in a stream of per-80 ms scores (a wake blocks the next 2 s, as live)."""
    count, quiet_until = 0, -1
    for i in np.flatnonzero(s > threshold):
        if i > quiet_until:
            count += 1
            quiet_until = i + 25
    return count


def train(data: dict[str, np.ndarray], steps: int, max_neg_weight: float = 15):
    import torch

    torch.manual_seed(1)
    acav = open_npy(DATA / "features" / "acav_part.npy")
    print(f"general-audio negatives: {len(acav):,} windows", flush=True)
    pos, neg = data["train_positive"], data["train_negative"]
    model = make_model().cuda()
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-2)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=1e-3, total_steps=steps, pct_start=0.1)
    bce = torch.nn.BCEWithLogitsLoss(reduction="none")
    t0 = time.time()
    for step in range(steps):
        ip = rng.integers(0, len(pos), 256)
        ineg = rng.integers(0, len(neg), 256)
        ia = np.sort(rng.integers(0, len(acav), 512))
        x = np.concatenate([pos[ip], neg[ineg], np.asarray(acav[ia], np.float32)])
        y = np.concatenate([np.ones(256), np.zeros(256 + 512)]).astype(np.float32)
        # false wakes cost more and more as training goes on (as openWakeWord does)
        w_neg = 1 + (max_neg_weight - 1) * step / steps
        w = np.concatenate([np.ones(256), np.full(256 + 512, w_neg)]).astype(np.float32)
        xb, yb, wb = (torch.from_numpy(a).cuda() for a in (x, y, w))
        loss = (bce(model(xb).squeeze(1), yb) * wb).mean()
        opt.zero_grad()
        loss.backward()
        opt.step()
        sched.step()
        if step % 2000 == 0 or step == steps - 1:
            print(f"  step {step:6d}  loss {loss.item():.4f}  ({time.time() - t0:.0f} s)", flush=True)
    return model


def evaluate(model, data: dict[str, np.ndarray]) -> dict:
    # one 96-number frame per 80 ms of continuous audio → every 16-frame window, as the live stream sees it
    frames = np.load(DATA / "features" / "validation_set_features.npy", mmap_mode="r")
    val = np.lib.stride_tricks.sliding_window_view(frames, FRAMES, axis=0).transpose(0, 2, 1)
    hours = len(frames) * 0.08 / 3600
    s_val = scores(model, val)
    s_pos, s_neg = scores(model, data["test_positive"]), scores(model, data["test_negative"])
    s_own = scores(model, data["test_owner_positive"]) if "test_owner_positive" in data else np.zeros(0)
    rows = []
    for t in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        rows.append({
            "threshold": t,
            "recall": float((s_pos > t).mean()),
            "owner_recall": float((s_own > t).mean()) if len(s_own) else None,
            "false_accept_test_negatives": float((s_neg > t).mean()),
            "false_wakes_per_hour": false_wakes(s_val, t) / hours,
        })
    # the lowest threshold with at most one false wake every two hours
    ok = [r for r in rows if r["false_wakes_per_hour"] <= 0.5] or rows[-1:]
    return {"hours_of_general_audio": hours, "test_positives": len(s_pos), "test_negatives": len(s_neg),
            "thresholds": rows, "threshold": ok[0]["threshold"]}


def export(model, path: Path) -> None:
    import torch

    path.parent.mkdir(parents=True, exist_ok=True)
    full = torch.nn.Sequential(model, torch.nn.Sigmoid()).cpu().eval()
    torch.onnx.export(full, torch.zeros(1, FRAMES, 96), str(path), input_names=["input"], output_names=["output"],
                      opset_version=13)
    # the shared feature models go next to it, so the PC agent and the phone app need only this folder
    import shutil

    import openwakeword

    resources = Path(openwakeword.__file__).parent / "resources" / "models"
    for name in ("melspectrogram.onnx", "embedding_model.onnx"):
        shutil.copy(resources / name, path.parent / name)


def check_with_openwakeword(path: Path, threshold: float) -> None:
    """Loads the exported model the way the PC agent will and scores a few held-out clips."""
    from openwakeword.model import Model

    m = Model(wakeword_models=[str(path)], inference_framework="onnx")
    name = path.stem
    for kind in ("positive", "negative"):
        fs = [f for f in files(kind)[0] if is_test(f, True)]
        random.Random(3).shuffle(fs)
        hits = 0
        for f in fs[:20]:
            m.reset()
            pcm = (load(f) * 32767).astype(np.int16)
            pcm = np.concatenate([np.zeros(SR, np.int16), pcm, np.zeros(SR // 2, np.int16)])
            best = max(p[name] for p in m.predict_clip(pcm))
            hits += best > threshold
        print(f"  openwakeword check, {kind}: {hits}/{min(20, len(fs))} clips woke it")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="recompute the features")
    ap.add_argument("--steps", type=int, default=20000)
    ap.add_argument("--rec-copies", type=int, default=REC_COPIES, help="augmented copies of each own recording")
    ap.add_argument("--neg-weight", type=float, default=40, help="how much false wakes cost by the end")
    ap.add_argument("--no-save", action="store_true", help="only report (to compare settings)")
    args = ap.parse_args()
    globals()["REC_COPIES"] = args.rec_copies
    data = features(args.refresh)
    for k, v in data.items():
        print(f"  {k}: {v.shape}")
    model = train(data, args.steps, args.neg_weight)
    report = evaluate(model, data)
    report["trained_on"] = {
        kind: {"synthetic": len(files(kind)[0]), "recorded": len(files(kind)[1])} for kind in ("positive", "negative")
    }
    if args.no_save:
        print(json.dumps(report["thresholds"]), flush=True)
        return
    path = OUT / "hey_sora.onnx"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    export(model, path)
    check_with_openwakeword(path, report["threshold"])
    print(f"saved {path}")


if __name__ == "__main__":
    main()
