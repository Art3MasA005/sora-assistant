"""The agent loop: LLM ↔ tools, streamed as events, with owner approval for risky actions.

Events (dicts with a "type"):
  conversation          {id, title}
  delta                 {text}                         streamed assistant text
  message               {id, content}                  assistant text for one LLM round, complete
  tool_start            {id, name, args}
  tool_result           {id, name, ok, preview}
  client_action         {action, params}               the requesting phone should do this
  attachment            {kind, url}
  confirmation_required {action_id, tool, summary, args, reason}
  action_resolved       {action_id, status}
  done                  {conversation_id, status: complete | awaiting_confirmation}
  error                 {message}
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select, update

from sora.agent.prompts import build_system_prompt, classify_reply
from sora.agent.tools import Registry, ToolContext, registry as default_registry
from sora.agent.tools.base import ToolArgsError, action_key
from sora.config import get_settings
from sora.db import session_scope
from sora.google.oauth import SERVICES, enabled_services, service_status
from sora.kv import kv_get
from sora.llm.client import ChatModel, ChatResult, LLMError, StreamDelta, get_llm
from sora.models import Conversation, Device, Message, PendingAction, Person
from sora.services import people, rag
from sora.textutil import has_bengali, reply_language
from sora.timeutil import now_local
from sora.services.hub import hub

log = logging.getLogger(__name__)

Emit = Callable[[dict], Awaitable[None]]

HISTORY_LIMIT = 60
OLD_TOOL_RESULT_CHARS = 1500


@dataclass
class Origin:
    device_id: uuid.UUID | None = None
    kind: str | None = None  # android | windows | cli | routine | ...
    voice: bool = False
    # A routine's steps the owner approved when creating it ("tool" or "tool:action"): they run without asking.
    allowed: frozenset[str] = frozenset()
    # The message carries third-party text (the email that started a routine): the chat counts as tainted.
    untrusted_input: bool = False
    # Reply in this language rather than the message's: a routine's prompt decides, not the email it quotes.
    language: str | None = None


class Agent:
    def __init__(self, llm: ChatModel | None = None, tool_registry: Registry | None = None) -> None:
        self._llm = llm
        self.registry = tool_registry or default_registry
        self._locks: defaultdict[uuid.UUID, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._background: set[asyncio.Task] = set()

    @property
    def llm(self) -> ChatModel:
        return self._llm or get_llm()

    # ------------------------------------------------------------ public API

    def chat(self, text: str, conversation_id: uuid.UUID | None = None, origin: Origin | None = None) -> AsyncIterator[dict]:
        origin = origin or Origin()
        return self._stream(lambda emit: self._chat(emit, text, conversation_id, origin))

    def resolve(self, action_id: uuid.UUID, approve: bool, origin: Origin | None = None) -> AsyncIterator[dict]:
        origin = origin or Origin()
        return self._stream(lambda emit: self._resolve_action(emit, action_id, approve, origin))

    # ------------------------------------------------------------ streaming plumbing

    async def _stream(self, work: Callable[[Emit], Awaitable[None]]) -> AsyncIterator[dict]:
        """Run `work` as its own task so it finishes (and saves state) even if the client disconnects."""
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        async def emit(event: dict) -> None:
            await queue.put(event)

        async def runner() -> None:
            try:
                await work(emit)
            except LLMError as exc:
                await emit({"type": "error", "message": str(exc)})
            except Exception as exc:
                log.exception("agent turn failed")
                await emit({"type": "error", "message": f"Internal error: {type(exc).__name__}: {exc}"})
            finally:
                await queue.put(None)

        task = asyncio.create_task(runner())
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        while (event := await queue.get()) is not None:
            yield event

    # ------------------------------------------------------------ turns

    async def _chat(self, emit: Emit, text: str, conversation_id: uuid.UUID | None, origin: Origin) -> None:
        text = text.strip()
        if not text:
            raise ValueError("empty message")
        async with session_scope() as session:
            conv = await session.get(Conversation, conversation_id) if conversation_id else None
            if conv is None:
                conv = Conversation(title=text[:60] + ("…" if len(text) > 60 else ""))
                if conversation_id:
                    conv.id = conversation_id
                session.add(conv)
                await session.flush()
            conv_id, title = conv.id, conv.title
        await emit({"type": "conversation", "id": str(conv_id), "title": title})

        async with self._locks[conv_id]:
            pending = await self._pending(conv_id)
            if pending:
                decision = classify_reply(text)
                reason = None if decision is not None else "the owner sent a different message instead of approving"
                for action in pending:
                    await self._resolve_one(emit, action, bool(decision), origin, reason)
            meta = {"device_kind": origin.kind, "voice": origin.voice}
            if origin.untrusted_input:
                meta["untrusted"] = True
            if origin.language:
                meta["reply_language"] = origin.language
            await self._save(conv_id, "user", text, meta=meta)
            await self._loop(emit, conv_id, origin)

    async def _resolve_action(self, emit: Emit, action_id: uuid.UUID, approve: bool, origin: Origin) -> None:
        async with session_scope() as session:
            action = await session.get(PendingAction, action_id)
            if action is None:
                raise ValueError("unknown action")
            conv_id = action.conversation_id
        await emit({"type": "conversation", "id": str(conv_id)})
        async with self._locks[conv_id]:
            async with session_scope() as session:
                action = await session.get(PendingAction, action_id)
            if action is None or action.status != "pending":
                await emit({"type": "error", "message": "This action was already handled."})
                await emit({"type": "done", "conversation_id": str(conv_id), "status": "complete"})
                return
            await self._resolve_one(emit, action, approve, origin, None)
            if await self._pending(conv_id):
                await emit({"type": "done", "conversation_id": str(conv_id), "status": "awaiting_confirmation"})
                return
            await self._loop(emit, conv_id, origin)

    # ------------------------------------------------------------ core loop

    async def _loop(self, emit: Emit, conv_id: uuid.UUID, origin: Origin) -> None:
        available = await self._available_integrations(origin)
        tools = self.registry.schemas(available)
        max_rounds = get_settings().llm_max_tool_rounds
        ctx = ToolContext(conv_id, origin.device_id, origin.kind, origin.voice, emit)
        ctx.user_text = await self._last_user_text(conv_id)

        rounds = 0
        # A tool doing a job step by step (the browser) may raise the limit for this turn: ctx.extras["max_rounds"].
        while rounds < max(max_rounds, ctx.extras.get("max_rounds", 0)):
            rounds += 1
            messages = await self._build_messages(conv_id, origin, available)
            result: ChatResult | None = None
            async for item in self.llm.stream(messages, tools or None):
                if isinstance(item, StreamDelta):
                    await emit({"type": "delta", "text": item.text})
                else:
                    result = item
            if result is None:
                raise LLMError("the model returned nothing")

            saved = await self._save(
                conv_id,
                "assistant",
                result.content or None,
                tool_calls=[tc.to_message() for tc in result.tool_calls] or None,
                meta={"model": result.model, "usage": result.usage},
            )
            if result.content:
                await emit({"type": "message", "id": saved, "content": result.content})
            if not result.tool_calls:
                await emit({"type": "done", "conversation_id": str(conv_id), "status": "complete"})
                return

            awaiting: list[PendingAction] = []
            reasons: dict = {}
            quiet_round = True  # every call a quick action that worked: the turn ends without a reply
            ctx.tainted = await self._tainted(conv_id)
            for call in result.tool_calls:
                tool = self.registry.get(call.name)
                if tool is None or (tool.needs and tool.needs not in available):
                    quiet_round = False
                    await self._save_tool(conv_id, call.id, call.name, f"Error: there is no tool named {call.name}.")
                    continue
                try:
                    args = self.registry.parse_args(tool, call.arguments)
                except ToolArgsError as exc:
                    quiet_round = False
                    await self._save_tool(conv_id, call.id, call.name, f"Error: {exc}. Fix the arguments and retry.")
                    await emit({"type": "tool_result", "id": call.id, "name": call.name, "ok": False, "preview": str(exc)})
                    continue
                if tool.needs_confirmation(args, ctx) and action_key(tool.name, args) not in origin.allowed:
                    async with session_scope() as session:
                        action = PendingAction(
                            conversation_id=conv_id,
                            tool_call_id=call.id,
                            tool_name=call.name,
                            arguments=args.model_dump(mode="json"),
                            summary=tool.describe(args),
                        )
                        session.add(action)
                        await session.flush()
                    # "tainted": only asking because third-party content is in the chat (the app says so)
                    reasons[action.id] = None if tool.always_confirms(args) else "tainted"
                    awaiting.append(action)
                    continue
                await emit({"type": "tool_start", "id": call.id, "name": call.name, "args": args.model_dump(mode="json")})
                outcome = await self.registry.run(tool, args, ctx)
                quiet_round = quiet_round and outcome.ok and tool.is_quiet(args)
                await self._save_tool(conv_id, call.id, call.name, outcome.content)
                await emit(
                    {"type": "tool_result", "id": call.id, "name": call.name, "ok": outcome.ok, "preview": outcome.content[:300]}
                )

            if awaiting:
                for action in awaiting:
                    await emit(
                        {
                            "type": "confirmation_required",
                            "action_id": str(action.id),
                            "tool": action.tool_name,
                            "summary": action.summary,
                            "args": action.arguments,
                            "reason": reasons.get(action.id),
                        }
                    )
                await emit({"type": "done", "conversation_id": str(conv_id), "status": "awaiting_confirmation"})
                return
            if quiet_round:
                # Opened the app, turned the volume up...: done, nothing to say (and no extra model call).
                await emit({"type": "done", "conversation_id": str(conv_id), "status": "complete"})
                return

        note = "I've taken many steps on this already, so I paused. Tell me if I should keep going."
        saved = await self._save(conv_id, "assistant", note)
        await emit({"type": "message", "id": saved, "content": note})
        await emit({"type": "done", "conversation_id": str(conv_id), "status": "complete"})

    async def _resolve_one(
        self, emit: Emit, action: PendingAction, approve: bool, origin: Origin, reason: str | None
    ) -> None:
        tool = self.registry.get(action.tool_name)
        status, result = "rejected", None
        if approve and tool is not None:
            ctx = ToolContext(action.conversation_id, origin.device_id, origin.kind, origin.voice, emit)
            # The request itself, not the "yes": "shutdown my PC" from the phone must still reach the PC.
            ctx.user_text = await self._last_user_text(action.conversation_id)
            await emit({"type": "tool_start", "id": action.tool_call_id, "name": action.tool_name, "args": action.arguments})
            try:
                args = self.registry.parse_args(tool, action.arguments)
                outcome = await self.registry.run(tool, args, ctx)
                content, ok = outcome.content, outcome.ok
            except ToolArgsError as exc:
                content, ok = f"Error: {exc}", False
            status, result = ("confirmed" if ok else "failed"), content[:2000]
            await emit({"type": "tool_result", "id": action.tool_call_id, "name": action.tool_name, "ok": ok, "preview": content[:300]})
        else:
            content = f"Not executed: {reason or 'the owner declined this action'}."
        await self._save_tool(action.conversation_id, action.tool_call_id, action.tool_name, content)
        async with session_scope() as session:
            await session.execute(
                update(PendingAction)
                .where(PendingAction.id == action.id)
                .values(status=status, result=result, resolved_at=datetime.now(UTC))
            )
        await emit({"type": "action_resolved", "action_id": str(action.id), "status": status})

    # ------------------------------------------------------------ context

    async def _available_integrations(self, origin: Origin) -> set[str]:
        async with session_scope() as session:
            available = await enabled_services(session)  # gmail, calendar, sheets... as connected
            kinds = set(
                (await session.execute(select(Device.kind).where(Device.revoked.is_(False)))).scalars()
            )
        if kinds & {"pc_agent", "windows"}:
            available.add("pc")
        if "android" in kinds or origin.kind == "android":
            available.add("phone")
        return available

    async def _status_lines(self, available: set[str], origin: Origin) -> list[str]:
        lines: list[str] = []
        async with session_scope() as session:
            google, granted, disabled = await service_status(session)
            with_birthday = list((await session.execute(select(Person).where(Person.birthday.is_not(None)))).scalars())
        on = [SERVICES[n]["label"] for n in SERVICES if n in granted - disabled]
        off = [SERVICES[n]["label"] for n in SERVICES if n not in granted - disabled]
        if google is None:
            lines.append("Google is NOT connected. For Gmail/Calendar/Drive/Sheets... requests, ask the owner to "
                         "tap Connect next to that service in the app.")
        elif google.status != "active":
            lines.append("Google access expired. Ask the owner to tap Connect again in the app.")
        else:
            lines.append(f"Google account {google.account_email}. Connected: {', '.join(on) or 'none'}.")
            if off:
                lines.append(f"Not connected: {', '.join(off)}. If the owner asks for one of these, tell them to "
                             "tap Connect next to it in the app.")
        if soon := people.upcoming_birthdays(with_birthday, now_local().date()):
            when = {0: "today", 1: "tomorrow"}
            lines.append("Birthdays coming up (from People): " + "; ".join(
                f"{p.name}{f' ({p.relation})' if p.relation else ''} {when.get(d, f'in {d} days')}" for p, d in soon))
        online = [f"{c.name} ({c.kind})" for c in hub.online()]
        lines.append("Devices online: " + (", ".join(online) if online else "none"))
        if origin.kind == "routine":
            lines.append("Nobody is chatting: this is one of the owner's routines, running on its own. Do what it asks "
                         "with your tools, then give the result in 1-3 short plain sentences (it becomes a notification "
                         "and may be read aloud). Don't ask questions; if something is missing, say what. If it asks to hear "
                         "only when something happened and nothing did, reply with just: (nothing)")
        elif origin.kind:
            lines.append(f"The owner is talking to you from their {origin.kind} {'by voice' if origin.voice else 'by text'}.")
        return lines

    async def _build_messages(self, conv_id: uuid.UUID, origin: Origin, available: set[str]) -> list[dict]:
        async with session_scope() as session:
            rows = list(
                (
                    await session.execute(
                        select(Message).where(Message.conversation_id == conv_id).order_by(Message.id.desc()).limit(HISTORY_LIMIT)
                    )
                ).scalars()
            )[::-1]
            last_row = next((m for m in reversed(rows) if m.role == "user"), None)
            last_user = (last_row.content if last_row else "") or ""
            # A routine names its reply language (its prompt's, not that of the email it quotes).
            language = (last_row.meta or {}).get("reply_language") if last_row else None
            memories = [m.content for m in await rag.memories_for_prompt(session, last_user)] if last_user else []
            instructions = await kv_get(session, "custom_instructions", "") or ""
            tone = await kv_get(session, "reply_tone", "Warm") or "Warm"

        # Start at a user message so tool results are never separated from their call.
        while rows and rows[0].role != "user":
            rows.pop(0)
        user_positions = [i for i, m in enumerate(rows) if m.role == "user"]
        recent_from = user_positions[-2] if len(user_positions) >= 2 else 0

        messages: list[dict] = [
            {
                "role": "system",
                "content": build_system_prompt(
                    voice=origin.voice,
                    status_lines=await self._status_lines(available, origin),
                    memories=memories,
                    instructions=instructions,
                    tone=tone,
                    last_user=last_user,
                    language=language,
                ),
            }
        ]
        answered: set[str] = {m.tool_call_id for m in rows if m.role == "tool" and m.tool_call_id}
        for i, m in enumerate(rows):
            if m.role == "user":
                messages.append({"role": "user", "content": m.content or ""})
            elif m.role == "assistant":
                msg: dict = {"role": "assistant", "content": m.content or ""}
                if m.tool_calls:
                    msg["tool_calls"] = m.tool_calls
                    msg["content"] = m.content or None  # some providers reject "" next to tool_calls
                messages.append(msg)
                # Repair: a call with no stored result (e.g. a crash mid-turn) would make the API reject the history.
                for call in m.tool_calls or []:
                    if call["id"] not in answered:
                        messages.append({"role": "tool", "tool_call_id": call["id"], "content": "Error: no result (interrupted)."})
            elif m.role == "tool":
                content = m.content or ""
                if i < recent_from and len(content) > OLD_TOOL_RESULT_CHARS:
                    content = content[:OLD_TOOL_RESULT_CHARS] + "\n...[older result shortened]"
                messages.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": content})
        # Banglish in, Banglish out is the model's habit; a note right on the message beats the
        # system prompt (the note is only sent, never stored).
        if last_user and not has_bengali(last_user) and (language or reply_language(last_user)) == "Bangla":
            last = next((m for m in reversed(messages) if m["role"] == "user"), None)
            if last is not None:
                last["content"] += "\n\n[Reply in Bangla written in Bangla script (বাংলা অক্ষর), not in English letters.]"
        return messages

    # ------------------------------------------------------------ persistence

    async def _last_user_text(self, conv_id: uuid.UUID) -> str:
        async with session_scope() as session:
            text = (
                await session.execute(
                    select(Message.content)
                    .where(Message.conversation_id == conv_id, Message.role == "user")
                    .order_by(Message.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        return text or ""

    async def _tainted(self, conv_id: uuid.UUID) -> bool:
        """Has third-party content (email, file, web page...) entered this conversation?"""
        untrusted = [t.name for t in self.registry.tools.values() if t.untrusted]
        async with session_scope() as session:
            hit = await session.execute(
                select(Message.id)
                .where(
                    Message.conversation_id == conv_id,
                    or_(
                        and_(Message.role == "tool", Message.name.in_(untrusted)),
                        # a routine started by an email carries that email in its first message
                        and_(Message.role == "user", Message.meta["untrusted"].astext == "true"),
                    ),
                )
                .limit(1)
            )
            return hit.first() is not None

    async def _pending(self, conv_id: uuid.UUID) -> list[PendingAction]:
        async with session_scope() as session:
            return list(
                (
                    await session.execute(
                        select(PendingAction)
                        .where(PendingAction.conversation_id == conv_id, PendingAction.status == "pending")
                        .order_by(PendingAction.created_at)
                    )
                ).scalars()
            )

    async def _save(
        self, conv_id: uuid.UUID, role: str, content: str | None, *, tool_calls: list[dict] | None = None,
        meta: dict | None = None,
    ) -> int:
        async with session_scope() as session:
            msg = Message(conversation_id=conv_id, role=role, content=content, tool_calls=tool_calls, meta=meta or {})
            session.add(msg)
            await session.execute(
                update(Conversation).where(Conversation.id == conv_id).values(updated_at=datetime.now(UTC))
            )
            await session.flush()
            return msg.id

    async def _save_tool(self, conv_id: uuid.UUID, call_id: str, name: str, content: str) -> None:
        async with session_scope() as session:
            session.add(Message(conversation_id=conv_id, role="tool", content=content, tool_call_id=call_id, name=name, meta={}))


_agent: Agent | None = None


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = Agent()
    return _agent
