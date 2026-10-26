# Sora — notes for Claude

Sora is a personal AI assistant for one owner. It has three parts:

- a FastAPI backend (`backend/sora`)
- a Windows PC agent (`pc_agent/`)
- one Flutter app (`app/`) that runs on Android and on Windows

The owner talks to it in Bangla, English or a mix of both.

## The owner's rules

- **Reply to the owner in Bengali script.** Code, commands, file names and commit messages stay in English.
- **Commits and PRs carry no Claude attribution.** No `Co-Authored-By: Claude` lines and no "Generated with Claude Code" footer.
- **Never commit secrets.** That covers `.env`, `data/`, tokens and keys. Never print a token, PIN or key either. Check whether one is set with a true/false, not by showing it.
- **Ask before pushing anything except your own working branch.** Don't push to `main`, and don't force-push.
- **Report honestly.** Say exactly what you ran and what you could not test. Most features need the owner's Windows PC or Android phone (see "Testing").

## Performance is a requirement, not a nice-to-have

The owner wants both apps fast and smooth, and the phone light on battery. A feature that makes either slower is not finished.

**Phone**
- Background work goes in the existing `SoraLink`, inside the accessibility service. Don't add a new foreground service, notification or Flutter engine for it.
- Be event-driven: callbacks, broadcasts, `ContentObserver`, WebSocket messages. No polling loops.
- No wake locks.
- Network: batch it, and send small payloads over the open WebSocket rather than new HTTP requests.
- Never block the main thread.
- Think twice before adding a dependency (APK size, start-up time).

**PC agent**
- Idle CPU stays near 0%. Prefer Windows events (`ReadDirectoryChangesW`, window hooks).
- Where polling can't be avoided, make each check cheap and space it out (seconds, not milliseconds).

**Backend**
- Nothing blocking on the event loop. Use `asyncio.to_thread` for disk, subprocesses and CPU work.
- Schedulers sleep until the next due time instead of ticking.
- Index anything that gets queried often.
- Cap and expire what is kept in memory.

**Flutter (both apps)**
- Keep 60 fps.
- Use `ListView.builder` for long lists.
- Rebuild the smallest subtree: `ValueListenableBuilder` / `ListenableBuilder` instead of a whole-screen `setState`.
- Give images a decode size (`cacheWidth`).
- No work in `build()` that can be cached. Follow the UI rules below.

**In the PR**
- For anything that runs in the background, write what it costs while idle and while busy (CPU, battery, network).
- Name anything you couldn't measure in the cloud, so it gets measured on the real PC and phone.

## What to work on

`docs/automation-roadmap.md` lists the automation work in the agreed order. Its "How to build each item" section says, for each one:

- how it should be built
- what needs the owner's approval
- when it counts as done

Follow it. If you have to deviate, say why in the PR. Do one item per branch or PR. When an item is done, move it to "Exists today" in that file.

## Layout

| Path | What it is |
|---|---|
| `backend/sora/agent/tools/` | Tools the LLM can call. `device_tools.py` has `pc_action`, `phone_action` and `pc_look_at_screen`. The Google tools, assistant tools and knowledge tools live next to it. |
| `backend/sora/api/` | REST and WebSocket routes. `ws.py` is the live line to the apps and agents. |
| `backend/sora/services/` | Background pieces: email watcher, reminders, clipboard sync, `announce.py` (UDP "Sora is on"), `power.py` (turning Sora off), `app_language.py`. |
| `backend/sora/services/hub.py` | Connected devices. `hub.command(device_id, action, params)` sends a command and waits for the result. |
| `pc_agent/windows_actions.py` | What the PC can do: the `ACTIONS` dict. Runs on Windows only. |
| `app/packages/sora_phone/android/.../SoraPhonePlugin.java` | What the phone can do: the `run()` switch. |
| `app/packages/sora_phone/android/.../SoraLink.java` | The phone's background WebSocket, inside the accessibility service. |
| `app/lib/` | The Flutter app. `desktop/` is Windows only, `shell/` is the phone shell, `widgets/` is shared, and `l10n/strings.dart` holds every string in English and Bangla. |

## Adding a device action

- **Phone action.** Add it in four places:
  1. a case in `SoraPhonePlugin.run()`
  2. the name in `PhoneActionName` in `device_tools.py`
  3. a description in `PhoneActionArgs` in the same file
  4. `PHONE_ONLY`, if it should run on the phone even when the owner asks from the PC

  New Android permissions go in the plugin's `AndroidManifest.xml`.
- **PC action.** Add the function and its entry in `pc_agent/windows_actions.py` `ACTIONS`. Add the name and description in `PcActionName` / `PcActionArgs`. Slow actions also go in `PC_TIMEOUTS` (backend) and `SLOW_ACTIONS` (agent). Risky actions go in `PC_DANGEROUS`, so the owner is asked first.
- **Older builds.** A phone or PC agent that doesn't know an action answers with an error. Keep backend messages helpful for that case.

## Testing

**In the cloud (Linux):**

```bash
bash scripts/cloud_setup.sh                       # once per machine: PostgreSQL + pgvector, .venv, .env
cd backend && ../.venv/bin/python -m pytest -q    # all backend tests
.venv/bin/python -m pytest -q pc_agent/tests      # the PC agent's logic (Windows calls stubbed)
```

- Add tests in `backend/tests/` for new backend behaviour. Stub device commands and the LLM; `conftest.py` has `FakeLLM`.
- If Flutter is installed, run `cd app && flutter analyze lib packages/sora_phone/lib`. Dart code is formatted at width 140.
- These can't run in the cloud, so say so instead of guessing:
  - the Windows app
  - the PC agent's Windows calls (ctypes and PowerShell)
  - the Android phone and the mic
  - APK and installer builds

  The owner tests those on their own PC and phone afterwards.

**On the owner's PC:** the local Claude session pulls the branch, runs the tests, builds `app-release.apk` and `Sora-Setup-<version>.exe` (the version is in `app/pubspec.yaml` and `app/windows/installer/sora.iss`), and tries the change on the real devices.

## UI rules learned the hard way (Flutter)

- **Blur.** `Glass` blurs the backdrop only when `strong` or `blur: true` is set, and only for things that float over moving content (sheets, menus, the chat composer).
  - Never put a backdrop blur inside anything that fades (`FadeTransition`, `Opacity`, `Rise`). It samples nothing there and flashes dark.
- **Hover and press colours.** Fade them to `color.withAlpha(0)`, never to `Colors.transparent`. That is black at zero alpha, so the fade passes through grey.
- **Animating opacity.** Use `FadeTransition` / `AnimatedOpacity`, not `Opacity` rebuilt inside an `AnimatedBuilder`.
- **Tickers.** Stop any ticker you aren't using. A repeating `AnimationController` keeps the app redrawing every frame.
- **Rebuilds.** Call `setState` only when the value actually changed. The shells cache `ChatScreen` and the current page, so polling doesn't rebuild the conversation.
- **Screen transitions.** Screens change through `ScreenStack` (cross-fade). On Windows a screen sits on `WindowBackdrop`.
- **Side columns.** They fold with `FoldingPanel` and come and go with `SlideAway`.

## Style

- Match the code around you: comment density, naming, idioms.
- Comments explain *why*.
- Strings go in `S` (`l10n/strings.dart`) with both languages.
