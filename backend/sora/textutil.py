"""Text helpers: HTML to text, truncation, chunking for RAG."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

_BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table"}
_SKIP_TAGS = {"script", "style", "head", "noscript", "svg"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
        text = "".join(parser.parts)
    except Exception:  # malformed HTML: fall back to stripping tags
        text = unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated, {len(text) - limit} more characters]"


def chunk_text(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    """Split on paragraph boundaries where possible, keeping chunks near `size` characters."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        while len(para) > size:  # a single huge paragraph: hard split
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:size])
            para = para[size - overlap :]
        if len(current) + len(para) + 2 <= size:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                chunks.append(current)
            tail = current[-overlap:] if current else ""
            current = f"{tail}\n\n{para}" if tail else para
    if current:
        chunks.append(current)
    return chunks


def has_bengali(text: str) -> bool:
    return any("ঀ" <= ch <= "৿" for ch in text)


# Common Bangla words as typed in Latin letters ("Banglish"), excluding ones that are also everyday
# English words, so plain English is never mistaken for Bangla.
_BANGLISH = frozenset("""
ami amar amake amra amader tumi tomar tomake tomra apni apnar apnake ora oder eta ota oita
eita ekta kono kichu kisu kichui shob ki kii keno kothay kotha kobe kokhon kivabe kibhabe kemon kemne
koto koyta kar kake kon konta acho achen achi achhe nai nei hobe hoy hoyni hoise hoyeche hocche
korbo korba korben koro koren kore korte korcho korchi korlam korsi korechi korbe korun koiro korio
dao dite dibo diba dicchi diye niye nao nibo jao jabo jete ashbo asho ashen eso aso bolo bolun bolte
bollam dekho dekhao dekhte dekhi dekhabo shuno shunao pathao pathiye pathabo khulo kholo khule bondho
lagbe lagche lagse lage parbo parba paro paren pari chao chaccho dorkar valo bhalo kharap thik
accha acha achha ekhon tokhon aj aaj kalke porshu sokal bikal raat  bhai apu vai tahole jodi
kintu abar arekta onek beshi kom shudhu sudhu holo hoilo gelo gese geche ashche asche khub
er ta ti te ke gula gulo guli der janao jana janai janabe janaben obostha obosta khobor koi kothai bujhi
bujhlam bujho shesh sesh shuru suru kaj kaaj ase nai ektu akta chalao chalu bondo dekhaw lekho likho porbo
""".split())


# The wake word as Whisper writes it: "Sora" (and near spellings), or "Hey Sara" — but plain "Sara"
# is a name, so it only counts after hey/hi/ok. The owner says it "Shora"/"Shura" (Bangladeshi accent).
_WAKE = re.compile(
    r"(?:\b(?:hey|hei|hi|hello|ok|okay)[\s,!.]+)?\b(?:sora|shora|shura|shara|sorah|shorah|shurah|soraa|zora|soura|"
    r"shoura|sohra|shohra|sorra|shorra)\b"
    r"|\b(?:hey|hei|hi|ok|okay)[\s,!.]+(?:sara|sarah|sola|sura|surah)\b"
    r"|(?:হেই\s*|এই\s*)?(?:সোরা|শোরা|শুরা|সোরাহ|শোরাহ)",
    re.I,
)
_GOODBYE = re.compile(
    r"^\W*(?:ok(?:ay)?\W+)?(?:bye|goodbye|bye bye|good night|that'?s all|that is all|stop|stop listening|"
    r"thank you|thanks|thank you sora|thanks sora|never ?mind|no thanks|nothing|"
    r"ধন্যবাদ|থ্যাংক ইউ|বাই|ঠিক আছে|ঠিকাছে|থাক|আর কিছু না|আর কিছু লাগবে না|চুপ করো|বন্ধ করো|"
    r"dhonnobad|thik ache|thak|ar kichu na)(?:\W+sora)?\W*$",
    re.I,
)


def wake_match(text: str) -> tuple[bool, str]:
    """Whether [text] calls Sora, and what follows the wake word ("Hey Sora, open YouTube" →
    (True, "open YouTube")). Only the start of the utterance counts, so a passing mention doesn't."""
    found = _WAKE.search(text)
    if not found or found.start() > 24:
        return False, ""
    return True, text[found.end() :].lstrip(" ,.!?।-").strip()


def is_goodbye(text: str) -> bool:
    """A short "bye" / "thanks" / "ধন্যবাদ" that ends a hands-free conversation."""
    return bool(_GOODBYE.match(text.strip()))


def reply_language(text: str) -> str:
    """The language Sora should answer [text] in: "Bangla" for Bangla script or Banglish, else
    "English". Mixed messages count as Bangla when they lean on Banglish words."""
    if has_bengali(text):
        return "Bangla"
    words = re.findall(r"[a-z]+", text.lower())
    hits = sum(w in _BANGLISH for w in words)
    if hits >= 2 or (hits == 1 and len(words) <= 3):
        return "Bangla"
    return "English"
