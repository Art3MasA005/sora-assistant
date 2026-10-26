# Client API

This is what the Android and Windows apps need. The full, always-current list of endpoints is at `GET /docs` (Swagger) on a running server. This page covers the parts Swagger can't show: the streaming events, the approval flow and the WebSocket protocol.

## Authentication

```http
POST /api/auth/login
{"password": "...", "device_name": "Pixel 8", "device_kind": "android"}   // android | windows | pc_agent | cli
→ {"token": "sora_...", "device_id": "..."}
```

Store the token securely, e.g. in Android Keystore via `flutter_secure_storage`. Send it as `Authorization: Bearer <token>` on every call. Each device gets its own token. `DELETE /api/devices/{id}` revokes a token. After five wrong passwords, logins are locked out for a growing amount of time.

After logging in on Android, register the push token with `PUT /api/devices/me/push-token {"fcm_token": "..."}`.

## Chat

```http
POST /api/chat
{"message": "আমার আজকের important email গুলো বলো", "conversation_id": null, "voice": false, "stream": true}
```

The reply is a **Server-Sent Events** stream. Every event looks like `event: <type>` followed by `data: <json>`:

| type | data | client should |
|---|---|---|
| `conversation` | `{id, title}` | remember `id` and send it with the next message |
| `delta` | `{text}` | append the text to the bubble being typed |
| `message` | `{id, content}` | finalize the bubble (one per LLM round) |
| `tool_start` | `{id, name, args}` | show a small "Checking Gmail…" chip |
| `tool_result` | `{id, name, ok, preview}` | mark that chip done or failed |
| `confirmation_required` | `{action_id, tool, summary, args}` | show an approval card, see below |
| `action_resolved` | `{action_id, status}` | update the card (`confirmed`, `rejected` or `failed`) |
| `client_action` | `{action, params}` | **phone only**: perform it, see Phone actions |
| `attachment` | `{kind: "image", url}` | show the image (`GET url` with the bearer token) |
| `done` | `{conversation_id, status}` | end of turn; `status` is `complete` or `awaiting_confirmation` |
| `error` | `{message}` | show the error; the turn has ended |

Use `"stream": false` to get a single JSON object instead: `{conversation_id, reply, status, events}`.

With `"voice": true`, the reply comes back short and without markdown, ready to be spoken. On Android, speech-to-text and text-to-speech both run on the device, so voice is just chat with `voice: true`.

## Approvals

Some actions wait for your approval: sending or replying to email, moving mail to trash, deleting events or knowledge, SMS, calendar invites, and risky PC commands. For these, Sora emits `confirmation_required` and ends the turn with `status: awaiting_confirmation`.

You can approve or decline in either of two ways:

1. **Buttons:** `POST /api/actions/{action_id}` with `{"approve": true}` or `{"approve": false}`. The response is an SSE stream that continues the conversation.
2. **Speech or text:** send the next chat message. A short clear yes ("হ্যাঁ", "haan", "ok", "pathao", "yes") approves. A short clear no ("না", "cancel", "thak") declines. Anything else declines the pending action and is treated as a new request.

`GET /api/actions/pending` lists everything still waiting, which is useful after the app restarts.

## Connect buttons (Google services)

The Connections screen shows one row per service, each with its own **Connect** button.

```http
GET /api/connections
→ [{"provider": "google", "configured": true, "connected": true, "account_email": "me@gmail.com",
    "services": [{"id": "gmail", "label": "Gmail", "description": "...", "granted": true, "enabled": true, "connected": true},
                 {"id": "sheets", ...}, ...]}]
```

Service ids are `gmail`, `calendar`, `drive`, `docs`, `sheets`, `slides`, `tasks` and `contacts`.

- **Connect one service:** call `POST /api/connections/google/start` with `{"services": ["sheets"]}`, then open the returned `auth_url` in the browser. Google asks only for that service's permission. Services connected earlier stay connected. The server pushes `connection_updated` on the WebSocket when the connection is done.
- **Connect everything:** send the same request with an empty body.
- **Switch a service off or on:** `PATCH /api/connections/google/services/{id}` with `{"enabled": false}`. Sora stops using it, but the Google permission is kept, so turning it back on needs no new consent.
- **Disconnect completely:** `DELETE /api/connections/google`. This revokes access at Google.

In the consent screen, Google can let the owner untick individual permissions. The `granted` flag always reflects what Google actually gave, so the UI should use `connected` to decide which rows show as connected.

## WebSocket: `/ws`

Connect with the `Authorization: Bearer <token>` header. Clients that can't set headers can pass `?token=<token>` instead. Keep the socket open while the app is in the foreground.

Server → client:

```jsonc
{"type": "hello", "device_id": "...", "name": "..."}
{"type": "notification", "notification": {"id", "kind", "title", "body", "importance", "data", "read", "created_at"}}
{"type": "connection_updated", "connection": {...}}        // Google connected or disconnected
{"type": "device_status", "device_id", "name", "online"}
{"type": "phone_notification", "notification": {"id", "key", "app", "package", "title", "text", "replyable", "device", "at"}}  // to the Windows app
{"type": "command", "id": "...", "action": "...", "params": {...}}
{"type": "ping"}
```

Client → server:

```jsonc
{"type": "result", "id": "<command id>", "ok": true, "data": ...}   // or "ok": false, "error": "..."
{"type": "pong"}
{"type": "status", "battery": 18, "charging": false}               // the phone, when its battery changes (routines)
{"type": "phone_notification", "key", "app", "package", "title", "text", "replyable"}  // the phone, for each kept notification
{"type": "pc_event", "event": "download_done", "name", "size"}     // the PC agent: becomes a notification on the phone
{"type": "pc_event", "event": "training_done", "command", "metrics"}
{"type": "pc_event", "event": "vscode_command_done", "command", "exit_code", "seconds", "tail", "window"}  // also vscode_task_done ("task")
{"type": "pc_event", "event": "claude_done", "folder", "ok", "summary", "edited", "denied", "session_id", "cost_usd"}
```

The Windows app answers a `command` at once with `"ok": false` (it is meant for the PC agent, which isn't running then).

Close code `4401` means the token is invalid. `4001` means the device was revoked.

**Speaking notifications:** a `notification` with `importance: "high"` that arrives while the app is open can be read aloud with on-device TTS.

## Phone actions

Sora can ask the phone to do things in three ways:

- In the chat stream, as a `client_action` event, when the request came from this phone.
- Over the WebSocket, as a `command` event. Reply to it with a `result` message.
- As an FCM data message with `client_action` and `params` when the app isn't connected.

| action | params | Android implementation hint |
|---|---|---|
| `open_app` | `target` (app name) | find the package by label in `PackageManager`, then `getLaunchIntentForPackage` |
| `open_url` | `target` | `ACTION_VIEW` |
| `call` | `target` (number or name) | `ACTION_DIAL`, so the owner taps to call |
| `send_sms` | `target`, `text` | already approved; `SmsManager` or `ACTION_SENDTO` |
| `set_alarm` | `time` (HH:MM), `text` | `AlarmClock.ACTION_SET_ALARM` |
| `set_timer` | `seconds` | `AlarmClock.ACTION_SET_TIMER` |
| `flashlight` | `on` | `CameraManager.setTorchMode` |
| `navigate` | `target` | `google.navigation:q=<target>` |
| `play_music` | `target` | `MediaStore.INTENT_ACTION_MEDIA_PLAY_FROM_SEARCH` |
| `open_settings` | `target` (wifi, bluetooth…) | `Settings.ACTION_*` |
| `reply_notification` | `target` (the notification's key), `text` | already approved; send through the notification's own Reply (RemoteInput) |
| `whatsapp_send` | `target` (number or name), `text` | already approved; open `wa.me/<number>?text=…` in WhatsApp, then tap Send (accessibility) |
| `say` | `text`, `audio_mp3_base64` | a routine's result, said aloud: play the MP3 (the server's voice). Answer an error on silent or in a call, so the server tries the PC |

## Other endpoints

| Area | Endpoints |
|---|---|
| Conversations | `GET /api/conversations`, `GET/PATCH/DELETE /api/conversations/{id}` |
| Google | see [Connect buttons](#connect-buttons-google-services) |
| Knowledge (RAG) | `GET /api/knowledge`, `GET /api/knowledge/search?q=`, `POST /api/knowledge/notes`, `POST /api/knowledge/url`, `POST /api/knowledge/upload` (multipart: pdf, docx, txt, md, html), `GET/PATCH/DELETE /api/knowledge/{id}` |
| Memories | `GET/POST /api/memories`, `PATCH/DELETE /api/memories/{id}` |
| Notifications | `GET /api/notifications?unread=true`, `POST /api/notifications/{id}/read`, `POST /api/notifications/read-all` |
| Reminders | `GET/POST /api/reminders`, `PATCH/DELETE /api/reminders/{id}` |
| Phone notifications | `GET /api/phone-notifications` (`{toast, items}`, newest first, the last 100, kept in memory only), `PUT /api/phone-notifications/settings` (`{toast}`: the PC agent shows each as a Windows toast), `DELETE /api/phone-notifications` |
| Routines | `GET /api/routines` (each with `trigger`, `when` in words, `next_run_at`, `last_status` ok/error/waiting/missed/unchanged and `last_result`), `PATCH /api/routines/{id}` (`{enabled, speak}`), `DELETE /api/routines/{id}`, `POST /api/routines/{id}/run` (runs now; the result comes as a notification. A page watch, trigger `page_change`, looks at its page now instead and runs only if it changed: `unchanged` otherwise), `GET /api/routines/{id}/runs` (the last 10). Routines are created and changed in the chat, where the owner approves them. A run's notification has `kind: "routine"` and `data: {routine_id, conversation_id, action_ids?}`; with `action_ids` it is waiting for an approval in that conversation. |
| Email rules | `GET/POST /api/email-rules`, `DELETE /api/email-rules/{id}` |
| Devices | `GET /api/devices`, `PATCH/DELETE /api/devices/{id}`, `POST /api/devices/{id}/command` (run a PC action directly, e.g. from a "Lock PC" button; `hey_sora` with `value` 1/0 switches "Hey Sora" on the PC, without a value it reports `{enabled, available}`) |
| Voice (Windows) | `POST /api/voice/transcribe` (multipart `audio`), `POST /api/voice/speak` → MP3, `POST /api/voice/turn` (audio in, reply text plus MP3 out) |
| System | `GET /api/health` (`name: "sora"` is how the apps recognise the server when they look for it on the Wi-Fi), `GET /api/files/{name}`, `GET/PUT /api/system/autostart` (`{enabled}`: start the server and PC agent with Windows) |
