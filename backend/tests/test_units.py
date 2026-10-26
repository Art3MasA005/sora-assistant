"""Pure-function tests: text helpers, yes/no matcher, crypto, tool schemas, Docs formatting, Gmail parsing."""

from __future__ import annotations

import base64
import json

from sora.agent.prompts import classify_reply
from sora.agent.tools import registry
from sora.google.gmail import _walk, summarize_message
from sora.google.workspace import _format_requests
from sora.security import decrypt, encrypt, hash_password, hash_token, new_device_token, verify_password
from sora.services.voice import _decode_audio, speakable, stt_ready
from sora.textutil import chunk_text, has_bengali, html_to_text, is_goodbye, reply_language, wake_match


def test_html_to_text_drops_scripts_and_keeps_blocks():
    html = "<html><head><style>p{}</style></head><body><p>Hello</p><script>evil()</script><div>World &amp; you</div></body></html>"
    assert html_to_text(html) == "Hello\n\nWorld & you"


def test_chunk_text_respects_size_and_keeps_everything():
    paragraphs = [f"Paragraph {i} " + "word " * 60 for i in range(20)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, size=800, overlap=100)
    assert len(chunks) > 1
    assert all(len(c) <= 800 for c in chunks)
    for p in paragraphs:
        assert any(p.strip() in c for c in chunks)


def test_chunk_text_short_and_empty():
    assert chunk_text("  short  ") == ["short"]
    assert chunk_text("") == []


def test_has_bengali():
    assert has_bengali("আমার email check করো")
    assert not has_bengali("check my email")


def test_wake_word_and_goodbye():
    assert wake_match("Hey Sora, what's the time?") == (True, "what's the time?")
    assert wake_match("Sora. Open YouTube.") == (True, "Open YouTube.")
    assert wake_match("Hey Sora.") == (True, "")
    assert wake_match("Hey Sara, what's the time?") == (True, "what's the time?")
    assert wake_match("Hey Sola, open YouTube.") == (True, "open YouTube.")
    assert wake_match("Hey Shara, can you hear me?") == (True, "can you hear me?")
    assert wake_match("Sora YouTube kholo.") == (True, "YouTube kholo.")
    assert wake_match("হেই সোরা, কেমন আছো?") == (True, "কেমন আছো?")
    # the owner's accent, as Whisper wrote it on 2026-10-20
    for yes in ["Shura?", "Hey, Shura.", "Hey, Shorah.", "Hey, Shora.", "এই শোরা", "হেই শুরা"]:
        assert wake_match(yes)[0] is True, yes
    for no in ["Hey sorry, I'm late.", "Please send the report to Sara.", "The solar panel is on the roof.",
               "I was telling my friend about the new assistant called Sora yesterday", "Sure, Laura.",
               "Can you shut up?", "Sure, I'll do it."]:
        assert wake_match(no)[0] is False, no
    for bye in ["Bye", "Thank you.", "Thanks Sora!", "ok bye", "ধন্যবাদ", "ঠিক আছে।", "that's all", "stop listening"]:
        assert is_goodbye(bye), bye
    for more in ["Thanks, now open YouTube", "stop the music", "ঠিক আছে, এবার ইউটিউব খোলো", "এটা করার জন্য ধন্যবাদ"]:
        assert not is_goodbye(more), more


def test_reply_language_follows_the_latest_message():
    for en in ["Hey Sora, can you hear me?", "Rona, can you open YouTube for me?", "Send an email to a@b.com",
               "What's on my calendar tomorrow?", "ok", ""]:
        assert reply_language(en) == "English", en
    for bn in ["kemon acho?", "amar email gula dekho", "YouTube khulo", "kal sokal 9 tay remind koro",
               "training er current obostha janao",
               "আমার মেইল দেখো", "Gmail-এ কী আছে?"]:
        assert reply_language(bn) == "Bangla", bn


def test_classify_reply_bangla_english_and_banglish():
    for yes in ["yes", "Yes!", "ok", "haan", "ha", "হ্যাঁ", "ঠিক আছে", "পাঠাও", "go ahead", "send it", "pathao"]:
        assert classify_reply(yes) is True, yes
    for no in ["no", "cancel", "na", "না", "বাতিল", "থাক", "dont", "don't"]:
        assert classify_reply(no) is False, no
    for other in ["check my email", "আমার মেইল দেখো", "yes but change the subject to hello please now", ""]:
        assert classify_reply(other) is None, other


def test_password_hashing():
    stored = hash_password("correct horse battery")
    assert verify_password("correct horse battery", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("x", "garbage")


def test_tokens_and_encryption():
    token = new_device_token()
    assert token.startswith("sora_") and len(hash_token(token)) == 64
    secret = "ya29.access-token"
    enc = encrypt(secret)
    assert enc != secret and decrypt(enc) == secret
    assert encrypt(None) is None and decrypt(None) is None


def test_every_tool_schema_is_clean_json():
    names = set()
    for tool in registry.tools.values():
        schema = tool.schema()
        params = schema["function"]["parameters"]
        assert "$ref" not in json.dumps(schema), tool.name
        assert "title" not in params or isinstance(params.get("title"), dict), tool.name
        assert set(params.get("required", [])) <= set(params["properties"]), tool.name
        assert params["type"] == "object"
        assert tool.description and len(tool.description) < 400
        names.add(tool.name)
    assert len(names) == len(registry.tools) >= 40


def test_confirmation_rules():
    modify = registry.get("gmail_modify")
    assert not modify.needs_confirmation(modify.args_model(message_ids=["a"], mark_read=True))
    assert modify.needs_confirmation(modify.args_model(message_ids=["a"], trash=True))
    assert registry.get("gmail_send").needs_confirmation(registry.get("gmail_send").args_model(to="a@b.c", subject="s", body="b"))
    pc = registry.get("pc_action")
    assert not pc.needs_confirmation(pc.args_model(action="open_app", target="chrome"))
    assert pc.needs_confirmation(pc.args_model(action="shutdown"))
    cal = registry.get("calendar_create_event")
    assert not cal.needs_confirmation(cal.args_model(summary="x", start="2026-10-20T10:00"))
    assert cal.needs_confirmation(cal.args_model(summary="x", start="2026-10-20T10:00", attendees=["a@b.c"]))


def test_tool_visibility_by_integration():
    without = {t["function"]["name"] for t in registry.schemas(set())}
    assert "gmail_send" not in without and "pc_action" not in without and "memory_save" in without
    gmail_only = {t["function"]["name"] for t in registry.schemas({"gmail"})}
    assert "gmail_send" in gmail_only and "sheets_read" not in gmail_only and "phone_action" not in gmail_only
    sheets_only = {t["function"]["name"] for t in registry.schemas({"sheets"})}
    assert {"sheets_read", "sheets_write", "sheets_create"} <= sheets_only and "gmail_search" not in sheets_only


def test_google_services_from_scopes():
    from sora.google.oauth import SCOPES, SERVICES, granted_services

    g = "https://www.googleapis.com/auth/"
    assert granted_services(None) == set()
    assert granted_services([g + "gmail.modify"]) == {"gmail"}
    assert granted_services([g + "drive"]) == {"drive", "docs", "sheets", "slides"}  # Drive unlocks the editors
    assert granted_services([g + "contacts.readonly"]) == set()  # contacts needs both of its scopes
    assert granted_services(SCOPES) == set(SERVICES)


def test_docs_formatting_indices_are_utf16():
    text, requests = _format_requests("# Title\nনমস্কার 😀\n- item one\n1. first", 1)
    assert text == "Title\nনমস্কার 😀\nitem one\nfirst\n"
    heading = requests[1]["updateParagraphStyle"]
    assert heading["range"] == {"startIndex": 1, "endIndex": 7}
    bullet = requests[2]["createParagraphBullets"]
    # "নমস্কার 😀\n" = 7 Bengali code units + space + emoji (2 units) + newline = 11
    assert bullet["range"]["startIndex"] == 7 + 11
    assert requests[3]["createParagraphBullets"]["bulletPreset"].startswith("NUMBERED")


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def test_gmail_payload_parsing():
    payload = {
        "mimeType": "multipart/mixed",
        "headers": [{"name": "From", "value": "Rahim <rahim@x.com>"}, {"name": "Subject", "value": "Hi"}],
        "parts": [
            {"mimeType": "multipart/alternative", "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("plain body ✓")}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>html</p>")}},
            ]},
            {"mimeType": "application/pdf", "filename": "cv.pdf", "body": {"size": 1234, "attachmentId": "a1"}},
        ],
    }
    plain, html, attachments = [], [], []
    _walk(payload, plain, html, attachments)
    assert plain == ["plain body ✓"] and html == ["<p>html</p>"]
    assert attachments == [{"filename": "cv.pdf", "mime_type": "application/pdf", "size": 1234}]
    summary = summarize_message({"id": "m1", "threadId": "t1", "payload": payload, "labelIds": ["INBOX", "UNREAD"], "snippet": "s"})
    assert summary["from"] == "Rahim <rahim@x.com>" and summary["unread"] is True


def test_owner_pin_and_password_rules():
    from sora.__main__ import password_problem

    assert password_problem("482913") is None
    assert password_problem("90817263") is None
    for weak in ["12345", "123456", "654321", "000000", "111111", "short"]:
        assert password_problem(weak), weak
    assert password_problem("a long passphrase") is None


def test_access_log_redacts_oauth_code_and_ws_token():
    import logging

    from sora.__main__ import _RedactSecretsInAccessLog

    def fmt(path: str) -> str:
        record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                                   ("127.0.0.1:5", "GET", path, "1.1", 200), None)
        _RedactSecretsInAccessLog().filter(record)
        return record.getMessage()

    assert "4/0AX" not in fmt("/oauth/google/callback?state=s&code=4/0AXsecret")
    assert "/oauth/google/callback?<redacted>" in fmt("/oauth/google/callback?state=s&code=4/0AXsecret")
    assert "sora_tok" not in fmt("/ws?token=sora_tok")
    assert "/api/conversations?limit=5" in fmt("/api/conversations?limit=5")


def test_speakable_strips_markdown():
    assert speakable("**Hi** see [this](https://x.com) and https://y.com\n- one\n- two") == "Hi see this and one two"


def test_owner_instructions_and_tone_reach_the_system_prompt():
    from sora.agent.prompts import build_system_prompt

    prompt = build_system_prompt(
        voice=False, status_lines=[], memories=[], instructions="Call me Yeasir.\nKeep it short.", tone="Formal"
    )
    assert "- Call me Yeasir.\n- Keep it short." in prompt
    assert "আপনি" in prompt  # the formal tone note
    assert prompt.index("## The owner's instructions") < prompt.index("Local time:")  # before the changing context


def test_app_wav_recordings_are_read_without_a_decoder():
    import io
    import struct
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(struct.pack("<4h", 0, 16384, -16384, 32767))
    audio = _decode_audio(buf.getvalue())
    assert audio.dtype.name == "float32"
    assert list(audio) == [0.0, 0.5, -0.5, 32767 / 32768]


def test_stt_ready_follows_the_provider(monkeypatch):
    from sora.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "stt_provider", "none")
    assert stt_ready() is False
    monkeypatch.setattr(s, "stt_provider", "groq")
    monkeypatch.setattr(s, "stt_api_key", "")
    assert stt_ready() is False
    monkeypatch.setattr(s, "stt_api_key", "x")
    assert stt_ready() is True


def test_notice_board_parsing():
    from sora.services.notices import parse_list

    html = """
    <a href="https://green.edu.bd/notice-details/holiday-a"><h1>Holiday A</h1> GUB Date: 06-Sep-26</a>
    <a href="/notice-details/exam-b">Exam B GUB Date: 12-Oct-26</a>
    <a class="news-list-item" href="https://green.edu.bd/notice-details/old-c"><small> GUB | 23-Feb-25</small><h1>Old C</h1></a>
    <a href="https://green.edu.bd/notice-details/exam-b">Exam B</a>
    <a href="https://green.edu.bd/about">About</a>
    """
    items = parse_list(html, "https://green.edu.bd/notice")
    assert [n["id"] for n in items] == ["exam-b", "holiday-a", "old-c"]
    assert items[0]["title"] == "Exam B" and items[0]["url"] == "https://green.edu.bd/notice-details/exam-b"
    assert items[0]["date"].strftime("%Y-%m-%d") == "2026-10-12"
    assert items[2]["title"] == "Old C" and items[1]["title"] == "Holiday A"
