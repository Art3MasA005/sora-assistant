"""Command line: python -m sora <command>

  setup           first-time setup: encryption key, database tables, owner password
  serve           run the API server
  migrate         apply database migrations
  set-password    change the owner password
  create-device   make a token for a device (e.g. the PC agent) without logging in
  chat            talk to Sora in the terminal
  connect-google  open Google's permission page to connect Gmail, Calendar, Drive...
  reindex         rebuild knowledge-base chunks and embeddings
  poll-email      run one email check now
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import sys
import uuid

from sora.config import ENV_FILE, ROOT_DIR, get_settings


def run_async(coro):
    # psycopg's async driver needs the selector event loop on Windows.
    if sys.platform == "win32":
        return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(coro)


class _RedactSecretsInAccessLog(logging.Filter):
    """OAuth callbacks carry an auth code and WebSocket URLs may carry a device token: keep both out of logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and "?" in args[2]:
            path, _, _query = args[2].partition("?")
            if path.startswith(("/oauth/", "/ws")):
                record.args = (*args[:2], f"{path}?<redacted>", *args[3:])
        return True


def _setup_logging() -> None:
    logging.basicConfig(
        level=get_settings().log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- commands


def cmd_migrate(_args=None) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT_DIR / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT_DIR / "backend" / "alembic"))
    command.upgrade(cfg, "head")
    print("Database is up to date.")


def _append_env(key: str, value: str) -> None:
    existing = ENV_FILE.read_text(encoding="utf-8-sig") if ENV_FILE.exists() else ""
    sep = "" if not existing or existing.endswith("\n") else "\n"
    ENV_FILE.write_text(f"{existing}{sep}{key}={value}\n", encoding="utf-8")


async def _set_password(password: str) -> None:
    from sora.db import session_scope
    from sora.kv import kv_set
    from sora.security import hash_password

    async with session_scope() as session:
        await kv_set(session, "owner_password_hash", hash_password(password))


async def _password_is_set() -> bool:
    from sora.db import session_scope
    from sora.kv import kv_get

    async with session_scope() as session:
        return bool(await kv_get(session, "owner_password_hash"))


def password_problem(secret: str) -> str | None:
    """None if the owner secret is acceptable. A PIN is fine because logins lock out after 5 misses
    and each device logs in only once (then keeps its own token)."""
    if secret.isdigit():
        if len(secret) < 6:
            return "A PIN needs at least 6 digits."
        if len(set(secret)) == 1 or secret in "01234567890" or secret in "09876543210":
            return "That PIN is too easy to guess (repeated or sequential digits)."
        return None
    if len(secret) < 10:
        return "A password needs at least 10 characters (or use a PIN of 6+ digits)."
    return None


def _ask_password(visible: bool = False) -> str:
    # Hidden input can hang in some embedded terminals; --visible falls back to plain input().
    ask = input if visible else getpass.getpass
    hint = "" if visible else " (typing is hidden: type it and press Enter)"
    while True:
        first = ask(f"New owner PIN (6+ digits) or password (10+ characters){hint}: ").strip().lstrip("﻿")
        problem = password_problem(first)
        if problem:
            print(problem)
            continue
        if ask("Repeat it: ").strip().lstrip("﻿") != first:
            print("They don't match.")
            continue
        if visible:
            print("\033[2J\033[H", end="")  # clear the screen so the PIN doesn't stay visible
        return first


def cmd_setup(args) -> None:
    from sora.security import generate_encryption_key

    s = get_settings()
    if not s.database_url:
        sys.exit("DATABASE_URL is missing in .env")
    if not s.encryption_key:
        _append_env("ENCRYPTION_KEY", generate_encryption_key())
        get_settings.cache_clear()
        print("Generated ENCRYPTION_KEY in .env (back it up: without it stored Google tokens can't be read).")
    cmd_migrate()
    if args.reset_password or not run_async(_password_is_set()):
        run_async(_set_password(_ask_password(args.visible)))
        print("Owner password saved.")
    else:
        print("Owner password already set (use `set-password` to change it).")
    print("\nSetup done. Start the server with:  python -m sora serve")


def cmd_set_password(args) -> None:
    run_async(_set_password(_ask_password(args.visible)))
    print("Owner password changed. Existing device tokens keep working; revoke them in the app if needed.")


async def _create_device(name: str, kind: str) -> str:
    from sora.db import session_scope
    from sora.models import Device
    from sora.security import hash_token, new_device_token

    token = new_device_token()
    async with session_scope() as session:
        session.add(Device(name=name, kind=kind, token_hash=hash_token(token)))
    return token


def cmd_create_device(args) -> None:
    token = run_async(_create_device(args.name, args.kind))
    print(f"Token for '{args.name}' ({args.kind}). It is shown only once:\n\n{token}\n")
    if args.save_as:
        _append_env(args.save_as, token)
        print(f"Also saved to .env as {args.save_as}.")


def cmd_serve(args) -> None:
    import uvicorn

    s = get_settings()
    _setup_logging()
    config = uvicorn.Config(
        "sora.main:app",
        host=args.host or s.host,
        port=args.port or s.port,
        log_level=s.log_level.lower(),
        ws_max_size=32 * 1024 * 1024,  # screenshots from the PC agent
        proxy_headers=True,
    )
    # After uvicorn.Config, which (re)configures its loggers.
    logging.getLogger("uvicorn.access").addFilter(_RedactSecretsInAccessLog())
    from sora.services import power

    server = uvicorn.Server(config)
    power.attach(server)  # so the Windows app can turn Sora off
    run_async(server.serve())


async def _chat_loop(voice: bool) -> None:
    from sora.agent.runner import Origin, get_agent
    from sora.db import dispose_engine

    agent = get_agent()
    conversation_id = None
    origin = Origin(kind="cli", voice=voice)
    print("Sora terminal chat. Empty line or Ctrl+C to quit.\n")
    try:
        while True:
            try:
                text = await asyncio.to_thread(input, "you> ")
            except EOFError:
                break
            if not text.strip():
                break
            pending, conv = await _print_events(agent.chat(text, conversation_id, origin))
            conversation_id = conv or conversation_id
            # Ask about each action in turn; resolving the last one lets the agent continue.
            while pending:
                p = pending.pop(0)
                print(f"\n  ⚠ Sora wants to: {p['summary']}")
                answer = (await asyncio.to_thread(input, "  approve? [y/N] ")).strip().lower()
                more, _ = await _print_events(agent.resolve(uuid.UUID(p["action_id"]), answer in {"y", "yes"}, origin))
                pending.extend(more)
    except KeyboardInterrupt:
        pass
    finally:
        await dispose_engine()


async def _print_events(events) -> tuple[list[dict], uuid.UUID | None]:
    pending: list[dict] = []
    conversation_id = None
    print("sora> ", end="", flush=True)
    async for event in events:
        t = event["type"]
        if t == "conversation":
            conversation_id = uuid.UUID(event["id"])
        elif t == "delta":
            print(event["text"], end="", flush=True)
        elif t == "tool_start":
            print(f"\n  ⚙ {event['name']}({_short(event['args'])})", flush=True)
        elif t == "tool_result":
            print(f"  {'✓' if event['ok'] else '✗'} {event['preview'][:160]}", flush=True)
        elif t == "confirmation_required":
            pending.append(event)
        elif t == "error":
            print(f"\n  [error] {event['message']}", flush=True)
    print()
    return pending, conversation_id


def _short(args: dict) -> str:
    text = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return text if len(text) < 120 else text[:117] + "..."


def cmd_chat(args) -> None:
    logging.basicConfig(level=logging.WARNING)
    run_async(_chat_loop(args.voice))


async def _reindex() -> int:
    from sora.db import dispose_engine, session_scope
    from sora.services.rag import reindex_all

    async with session_scope() as session:
        count = await reindex_all(session)
    await dispose_engine()
    return count


def cmd_reindex(_args) -> None:
    print(f"Reindexed {run_async(_reindex())} document(s) and all memories.")


async def _google_auth_url(services: list[str]) -> str:
    from sora.db import dispose_engine, session_scope
    from sora.google.oauth import build_auth_url

    try:
        async with session_scope() as session:
            return await build_auth_url(session, services or None)
    finally:
        await dispose_engine()


def cmd_connect_google(args) -> None:
    import webbrowser

    import httpx

    from sora.google.oauth import OAuthError

    s = get_settings()
    try:
        httpx.get(f"http://127.0.0.1:{s.port}/api/health", timeout=3)
    except httpx.HTTPError:
        sys.exit("The server isn't running. Start it first in another terminal:  python -m sora serve")
    try:
        url = run_async(_google_auth_url([name.lower() for name in args.services]))
    except OAuthError as exc:
        sys.exit(str(exc))
    print("Opening Google's permission page in your browser. If it doesn't open, copy this link:\n")
    print(url + "\n")
    print(f"After you approve, Google sends you back to {s.google_redirect}")
    webbrowser.open(url)


async def _poll() -> int:
    from sora.db import dispose_engine
    from sora.services.email_watcher import poll_once

    try:
        return await poll_once()
    finally:
        await dispose_engine()


def cmd_poll_email(_args) -> None:
    _setup_logging()
    print(f"Processed {run_async(_poll())} new email(s).")


def main(argv: list[str] | None = None) -> None:
    _utf8_console()
    parser = argparse.ArgumentParser(prog="python -m sora", description="Sora personal assistant backend")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", help="first-time setup")
    p.add_argument("--reset-password", action="store_true")
    p.add_argument("--visible", action="store_true", help="show what you type (if hidden input hangs)")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("serve", help="run the API server")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.set_defaults(func=cmd_serve)

    sub.add_parser("migrate", help="apply database migrations").set_defaults(func=cmd_migrate)
    p = sub.add_parser("set-password", help="set or change the owner PIN/password")
    p.add_argument("--visible", action="store_true", help="show what you type (if hidden input hangs)")
    p.set_defaults(func=cmd_set_password)

    p = sub.add_parser("create-device", help="create a device token")
    p.add_argument("--name", required=True)
    p.add_argument("--kind", choices=["android", "windows", "pc_agent", "cli"], default="pc_agent")
    p.add_argument("--save-as", help="also append the token to .env under this variable name")
    p.set_defaults(func=cmd_create_device)

    p = sub.add_parser("chat", help="terminal chat")
    p.add_argument("--voice", action="store_true", help="ask for short spoken-style replies")
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("connect-google", help="open the Google permission page (server must be running)")
    p.add_argument("services", nargs="*", help="gmail calendar drive docs sheets slides tasks contacts (default: all)")
    p.set_defaults(func=cmd_connect_google)
    sub.add_parser("reindex", help="rebuild RAG chunks and embeddings").set_defaults(func=cmd_reindex)
    sub.add_parser("poll-email", help="check Gmail once").set_defaults(func=cmd_poll_email)

    args = parser.parse_args(argv)
    from sora.wsl_db import ensure_postgres

    ensure_postgres()
    args.func(args)


if __name__ == "__main__":
    main()
