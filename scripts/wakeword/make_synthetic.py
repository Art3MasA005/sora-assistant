"""Synthetic training clips for the on-device "Hey Sora" model, made with Edge TTS (the voices Sora
already speaks with): "Hey Sora" / "Sora" in every English, Bangla, Hindi and Urdu voice (Indian,
Bangladeshi, Pakistani, British, American... accents), each at a random speed and pitch, plus
negatives — words that sound close ("Hey Siri", "Sorry", "সোনা") and ordinary requests without
the name.

    .venv\\Scripts\\python scripts\\wakeword\\make_synthetic.py            # all of it (~20 min)
    .venv\\Scripts\\python scripts\\wakeword\\make_synthetic.py --limit 20 # a quick try

Writes 16 kHz mono WAV to data/wakeword/synthetic/{positive,negative}/. Already-made clips are
skipped, so it can be stopped and run again. The owner's own recordings (Settings → Voice → Teach
Sora your voice) go to data/wakeword/recorded/ and matter most; these add variety.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import edge_tts  # noqa: E402

from sora.services.voice import wav_16k  # noqa: E402

OUT = ROOT / "data" / "wakeword" / "synthetic"
LOCALES = ("en-", "bn-", "hi-IN", "ur-")

POSITIVE_EN = ["Hey Sora", "Hey Sora!", "Hey, Sora.", "Sora", "Sora?", "Hey Sora?", "Okay Sora", "Sora!"]
POSITIVE_BN = ["হেই সোরা", "সোরা", "হেই, সোরা!", "সোরা?"]

# Sound close to "Sora" or are other assistants' names: the model must learn these are not it.
CONFUSABLE_EN = [
    "Hey Siri", "Sorry", "Hey Sara", "Sara", "Zora", "Story", "Soda", "Solar", "Sonar", "Hey Sarah",
    "Hey there", "Okay Google", "Hey Google", "Alexa", "So, right", "Sure", "Hey Soha", "Hey Sonia",
    "Aurora", "Hey Laura", "Hey Nora", "So rough", "Sore throat", "Hey sir", "Hey Siri, stop",
]
CONFUSABLE_BN = ["সোনা", "সারা দিন", "সরো তো", "সরাও", "সারা", "হেই সারা", "সুরা", "সোডা", "সরি", "হেই সিরি"]

# Ordinary speech: the model must stay quiet unless its name is said.
SPEECH_EN = [
    "Open YouTube on my phone.", "What's the weather like today?", "Call my mom.", "Set an alarm for seven.",
    "I'll be there in ten minutes.", "Can you send me the file?", "Let's have dinner at eight.",
    "The training finished last night.", "Turn the volume down a bit.", "Where did I put my keys?",
    "Good morning, how are you?", "Play some music.", "That was a really long day.", "Remind me tomorrow.",
    "Check my email please.", "The meeting starts at three.", "I think it's going to rain.",
    "Show me the latest results.", "Thanks a lot, see you later.", "What time is it now?",
]
SPEECH_BN = [
    "আজকে আবহাওয়া কেমন?", "আম্মুকে একটা ফোন দাও।", "ইউটিউব খোলো।", "আমি দশ মিনিটের মধ্যে আসছি।",
    "কালকে সকালে আমার ক্লাস আছে।", "ভাত খেয়েছ?", "গানটা একটু জোরে দাও।", "আজকে অনেক কাজ ছিল।",
    "মেসেজটা পাঠিয়ে দাও।", "এখন কয়টা বাজে?", "ট্রেনিং কি শেষ হয়েছে?", "আমি একটু পরে কথা বলব।",
    "লাইটটা বন্ধ করে দাও।", "চলো বাইরে যাই।", "ধন্যবাদ, পরে দেখা হবে।", "আমার ইমেইলগুলো দেখাও।",
]


def _jobs(voices: list[dict]) -> list[tuple[str, str, str]]:
    """(kind, voice, text) for every clip."""
    jobs = []
    for v in voices:
        name, bangla = v["ShortName"], v["Locale"].startswith("bn-")
        positives = POSITIVE_EN + (POSITIVE_BN if bangla else [])
        negatives = CONFUSABLE_EN + SPEECH_EN + (CONFUSABLE_BN + SPEECH_BN if bangla else [])
        jobs += [("positive", name, t) for t in positives]
        # a sample of the negatives per voice, so the set stays balanced
        jobs += [("negative", name, t) for t in random.Random(name).sample(negatives, min(len(negatives), 14))]
    return jobs


async def _make(kind: str, voice: str, text: str, sem: asyncio.Semaphore) -> bool:
    key = hashlib.sha1(f"{voice}|{text}".encode()).hexdigest()[:12]
    path = OUT / kind / f"{voice}-{key}.wav"
    if path.exists():
        return False
    rnd = random.Random(key)
    rate, pitch = f"{rnd.randint(-25, 20):+d}%", f"{rnd.randint(-12, 12):+d}Hz"
    async with sem:
        for attempt in range(3):
            try:
                audio = bytearray()
                async for chunk in edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).stream():
                    if chunk["type"] == "audio":
                        audio.extend(chunk["data"])
                path.write_bytes(wav_16k(bytes(audio)))
                return True
            except Exception as exc:  # throttled or a voice that can't say Bangla text: retry, then skip
                if attempt == 2:
                    print(f"skip {voice} {text!r}: {exc}")
                await asyncio.sleep(2 * (attempt + 1))
    return False


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only this many clips (a quick try)")
    args = ap.parse_args()
    voices = [v for v in await edge_tts.list_voices() if v["Locale"].startswith(LOCALES)]
    jobs = _jobs(voices)
    random.Random(7).shuffle(jobs)
    if args.limit:
        jobs = jobs[: args.limit]
    for kind in ("positive", "negative"):
        (OUT / kind).mkdir(parents=True, exist_ok=True)
    print(f"{len(voices)} voices, {len(jobs)} clips "
          f"({sum(j[0] == 'positive' for j in jobs)} positive) -> {OUT}")
    sem = asyncio.Semaphore(4)
    done = 0
    for i in range(0, len(jobs), 100):
        made = await asyncio.gather(*(_make(*j, sem) for j in jobs[i : i + 100]))
        done += sum(made)
        print(f"  {min(i + 100, len(jobs))}/{len(jobs)} ({done} new)", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
