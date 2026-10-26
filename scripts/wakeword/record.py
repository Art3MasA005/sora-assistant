"""Record your own voice for the "Hey Sora" model on this PC, in the terminal (the apps have the same
thing under Settings → Voice → Teach Sora your voice).

    .venv\\Scripts\\python scripts\\wakeword\\record.py

Enter = record one take (it stops by itself when you stop talking), u = undo the last take,
q = quit. First 50 takes of "Hey Sora" said in different ways, then 25 things that are not.
Takes go to data/wakeword/recorded/{positive,negative}/ (pcmic-…wav), then retrain with
scripts/wakeword/train.py. "Hey Sora" on this PC is paused meanwhile, so it doesn't answer.
"""

from __future__ import annotations

import sys
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pc_agent"))

from sora_pc_agent import load_env  # noqa: E402

OUT = ROOT / "data" / "wakeword" / "recorded"
RATE = 16000
GOALS = {"positive": 50, "negative": 25}

# The same prompts as the app (app/lib/voice/wake_trainer.dart).
POSITIVES = [
    ("Hey Sora", "normally · স্বাভাবিকভাবে"), ("Hey Sora", "quietly · আস্তে"), ("Sora", "just the name · শুধু নামটা"),
    ("Hey Sora", "a bit louder · একটু জোরে"), ("Hey Sora", "quickly · তাড়াতাড়ি"),
    ("Hey Sora", "from 2–3 metres away · ২–৩ মিটার দূর থেকে"), ("Sora", "slowly · ধীরে"),
    ("Hey Sora", "as if calling from another room · অন্য ঘর থেকে ডাকার মতো"),
    ("Hey Sora", "tired or sleepy · ক্লান্ত বা ঘুম-ঘুম গলায়"), ("Sora", "as if asking a question · প্রশ্ন করার মতো"),
]
NEGATIVES = [
    ("Hey Siri", ""), ("Sorry", ""), ("Hey Sara", ""), ("সোনা", ""), ("Story", ""), ("সারা দিন", ""),
    ("Hey Google", ""), ("সরো তো", ""), (None, "any sentence in Bangla · বাংলায় যেকোনো একটা বাক্য"),
    (None, "any sentence in English · ইংরেজিতে যেকোনো একটা বাক্য"), (None, "count from one to five · এক থেকে পাঁচ গুনুন"),
    (None, "a few words about your day · আপনার দিন নিয়ে দু-এক কথা"),
]


def mine(kind: str) -> list[Path]:
    return sorted((OUT / kind).glob("pcmic-*.wav"))


def record(max_seconds: float) -> np.ndarray | None:
    """One take: starts now, ends after 0.6 s of quiet following speech (None if nothing was said)."""
    import sounddevice as sd

    chunks: list[np.ndarray] = []
    floor, heard, quiet, start = None, False, 0.0, time.time()
    with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=800) as stream:
        while time.time() - start < max_seconds:
            block, _ = stream.read(800)  # 50 ms
            block = block[:, 0].copy()
            chunks.append(block)
            db = 20 * np.log10(np.sqrt(np.mean(block.astype(np.float32) ** 2)) / 32768 + 1e-9)
            floor = db if floor is None else min(floor, db) if not heard else floor
            loud = db > max(floor + 12, -50)
            bar = "#" * int(max(0, min(30, (db + 60) / 2)))
            print(f"\r  {'listening' if not heard else 'hearing  '} [{bar:<30}]", end="", flush=True)
            if loud:
                heard, quiet = True, 0.0
            elif heard:
                quiet += 0.05
                if quiet >= 0.6:
                    break
            elif time.time() - start > 5:
                break
    print("\r" + " " * 50 + "\r", end="")
    return np.concatenate(chunks) if heard else None


def save(kind: str, pcm: np.ndarray) -> Path:
    folder = OUT / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"pcmic-{datetime.now():%Y%m%d-%H%M%S-%f}.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.astype("<i2").tobytes())
    return path


class AgentVoice:
    """Pauses "Hey Sora" on this PC while recording (through the server, as the app's switch does)."""

    def __init__(self):
        import httpx

        env = load_env()
        self.http = httpx.Client(base_url=env.get("SORA_SERVER_URL", "http://127.0.0.1:8000"), timeout=15,
                                 headers={"Authorization": f"Bearer {env.get('PC_AGENT_TOKEN', '')}"})
        self.pc, self.was_on = None, False
        try:
            pcs = [d for d in self.http.get("/api/devices").json() if d["kind"] == "pc_agent" and d["online"]]
            if pcs:
                self.pc = pcs[0]["id"]
                self.was_on = bool(self._command({}).get("enabled"))
        except Exception as exc:
            print(f"(couldn't reach the Sora server to pause \"Hey Sora\": {exc})")

    def _command(self, params: dict) -> dict:
        r = self.http.post(f"/api/devices/{self.pc}/command", json={"action": "hey_sora", "params": params})
        return r.json().get("result") or {}

    def set(self, on: bool) -> None:
        if self.pc and self.was_on:
            try:
                self._command({"value": 1 if on else 0})
            except Exception:
                pass


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    agent = AgentVoice()
    agent.set(False)
    try:
        while True:
            p, n = len(mine("positive")), len(mine("negative"))
            if p >= GOALS["positive"] and n >= GOALS["negative"]:
                print(f"\nAll done: {p} \"Hey Sora\" and {n} other takes. More still help; q to finish.")
            kind = "positive" if p < GOALS["positive"] or n >= GOALS["negative"] else "negative"
            phrase, how = POSITIVES[p % len(POSITIVES)] if kind == "positive" else NEGATIVES[n % len(NEGATIVES)]
            if kind == "negative" and n == 0:
                print("\nNow some things that are NOT \"Hey Sora\", so Sora learns the difference.")
            print(f"\n[{p}/{GOALS['positive']} \"Hey Sora\" · {n}/{GOALS['negative']} other]")
            if phrase:
                print(f"  Say: \"{phrase}\"" + (f"  ({how})" if how else ""))
            else:
                print(f"  Say {how}")
            cmd = input("  Enter = record · u = undo · q = quit > ").strip().lower()
            if cmd == "q":
                break
            if cmd == "u":
                takes = mine("positive") + mine("negative")
                if takes:
                    last = max(takes, key=lambda f: f.name)
                    last.unlink()
                    print(f"  removed {last.parent.name}/{last.name}")
                continue
            pcm = record(4 if kind == "positive" else 7)
            if pcm is None:
                print("  Didn't hear anything. Try again.")
                continue
            save(kind, pcm)
            print(f"  saved ({len(pcm) / RATE:.1f} s)")
    finally:
        agent.set(True)
    print("\nRetrain with:  data\\wakeword\\.venv\\Scripts\\python scripts\\wakeword\\train.py")


if __name__ == "__main__":
    main()
