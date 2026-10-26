# Automation roadmap

Agreed on 2026-10-21. What phone, PC and web automation Sora has, what is missing, and the order to build it in. Nothing below the "Exists today" section is built yet.

## Order

1. **Real web search.** Done: see "Exists today".
2. **Routines and triggers.** Done: see "Exists today".
3. **Phone notifications.** Done: see "Exists today".
4. **PC.** Done: see "Exists today".
5. **Browser automation.** Done: see "Exists today".
6. **VS Code and Claude Code** (agreed with the owner on 2026-10-20). Done: see "Exists today".

## How to build each item

Every item must also meet the performance rules in `CLAUDE.md`. Anything that runs in the background has to be event-driven and cost next to nothing while idle. Each item is done only when:

- the backend tests pass, with new tests for the new behaviour
- `flutter analyze` is clean, if the app changed
- every string exists in both English and Bangla
- the PR says what could not be tested in the cloud

## Other phone items

| Item | Notes |
|---|---|
| Incoming call on the PC, answer or reject there | needs `ANSWER_PHONE_CALLS` |
| Missed calls and SMS; OTP codes to the PC clipboard | needs `READ_SMS` and call log access |
| Phone screen understanding | a phone version of `pc_look_at_screen` (screenshot + vision); easy |
| Phone UI automation: tap, type, scroll | via accessibility; hard and unreliable |
| DND / silent, brightness | needs notification policy access and `WRITE_SETTINGS` |
| File transfer | Android share target "Sora → PC" for images, files and text |
| Wi-Fi / Bluetooth / hotspot | Android 10+ only lets an app open the settings panels |

## Other PC items

"Computer use": multi-step tasks that combine vision with clicking. This is hard. Reading the screen already works.

## Exists today

- **Phone**:
  - apps: open/close app, URL, web/YouTube search, `youtube_play`, media, volume, torch, navigate, `play_music`, `open_settings`
  - calls and SMS: matched to contacts by sound, with a SIM choice
  - alarms and timers: set and cancel
  - screen and device: screenshot, lock, ring, status
  - clipboard: both ways, images included; `save_image`
  - notifications on the PC: chosen apps (WhatsApp, Messenger, Telegram, SMS by default) go over SoraLink to the Details panel and, if wanted, a Windows toast; kept in memory only (the last 100). `phone_notifications_recent` answers "what came on WhatsApp?"; `reply_notification` answers through the notification's own Reply and `whatsapp_send` sends a new WhatsApp message, both after the owner approves
- **Routines**: Sora runs the owner's prompt on its own.
  - when: at a time (chosen weekdays), every N minutes (15 or more), an email arrives, a phone notification arrives, the phone battery drops below N%, the phone or PC comes online or goes offline, the PC wakes up, a web page changes
  - page watches: on their schedule the page is fetched (or read by the PC's browser, for a CSS part or a JavaScript site), with no LLM; the routine runs only when the watched part changed (stored hash), with a short diff; three failed checks in a row are told once
  - steps that need approval run only if the routine pre-approved them; otherwise the run waits for the owner in a notification
  - the result comes as a notification and is said aloud on the device the owner last used (silent routines: notification only)
  - made and changed in the chat; the Routines screen (phone and PC) switches them on/off, runs them now and shows the last result
- **PC**:
  - apps and files: open/close app, URL, path, `search_files`, Store search/install/uninstall, `installed_apps`
  - media and volume
  - power: lock, sleep, shutdown, restart, log off
  - screen: screenshot, `pc_look_at_screen`
  - system: notify, clipboard, processes, `system_info`, `run_command`
  - Sora: `training_status`, `hey_sora`
  - windows: list, focus, minimize, maximize, snap left/right; `type_text` (any language) and `hotkey`
  - files in the owner's folders only: copy, move, rename, delete (to the Recycle Bin), zip, unzip, `tidy_downloads`; nothing is replaced without the owner's yes
  - to the phone on its own: a finished download, a finished training run
  - settings: brightness, Wi-Fi, Bluetooth, dark mode
- **Browser** on the PC (Playwright, the installed Chrome or Edge, its own profile in `data/browser-profile` so the owner logs in once; headless unless the owner wants to watch; closes itself after 5 idle minutes):
  - `browser` tool: open, read (the page's text and up to 80 buttons, links and fields with stable ids), click, fill, screenshot (shown in the chat), download (into Downloads, which the download watcher reports)
  - 15 steps per request; a click that submits, pays, buys, posts or sends asks first, and the PC agent refuses it unless approved with the button's own text; passwords are never typed
  - page text is untrusted: once it is in the chat, open, fill and download ask first
- **VS Code** on the PC, through the Sora Bridge extension (`vscode_ext/`, installed and updated by the PC agent itself; each VS Code window connects to the agent over 127.0.0.1 with a token):
  - windows and projects: the open windows, VS Code's recent projects, open a project (by name), a new window
  - files, only inside the window's folders: open, read (with line numbers, unsaved changes too), write, edit (exact text), rename, delete (to the Recycle Bin), list, search; the open file and selection; save all
  - problems (errors and warnings); terminals: run a command and get its exit code and output (shell integration), read a terminal's latest output, stop (Ctrl+C), new, close; a command Sora started that outlives the request, or any command that runs 3 minutes or more, tells the phone when it ends
  - git (VS Code's Git): status, diff, log, commit, push, pull, branches; tasks (exit code, the phone told if long) and debugging; VS Code commands, settings and extensions
  - only serious steps ask first (the owner's rule): deleting, `git push`, and a terminal command that deletes, turns off, kills, wipes or pushes (`agent/tools/risk.py`); running code, committing, settings and installing just happen, and ask only once an email or a web page is in the chat; 25 steps per request
- **Claude Code** on the PC: `claude_code` hands a coding job in a project to `claude -p` (a job that only edits files just starts; one allowed to do more asks). It may edit the project's files; anything else it needs is refused and listed, so Sora asks and continues the same session with exactly that allowed. A long job ends with a notification with its summary; `open_in_vscode` continues the session in a VS Code terminal.
- **Web**:
  - `web_search`: Sora searches and reads the results itself (title, URL, snippet; third-party text, so marked untrusted). Brave or Tavily with `WEB_SEARCH_API_KEY`, DuckDuckGo without a key and as the fallback; results cached for 5 minutes. The phone/PC `web_search` actions still only open a search in the browser.
  - `web_fetch`, `university_notices`.
