# Sora Bridge (VS Code extension)

Lets Sora work in VS Code for its owner: open projects, read and edit files, run terminal commands and see
their exit code and output, read problems, use git, run tasks and debug, change settings. Sora reaches it
through the Sora PC agent on the same computer; nothing listens on the network.

- **Install:** the PC agent does it on start (`code --install-extension`, from this folder packed as a
  `.vsix`), and again whenever this version changes. Reload open windows once.
- **Connection:** the agent writes its port and a fresh token to `%LOCALAPPDATA%\Sora\vscode-bridge.json`;
  each window connects to `127.0.0.1` with that token. The file is watched, so a restarted agent is found
  again. Nothing polls.
- **Limits:** files Sora changes must be inside the window's folders; changes go through VS Code's own
  edits, so Ctrl+Z undoes them; deleting goes to the Recycle Bin or doesn't happen.
- **Setting:** `sora.longCommandMinutes` (default 3): a terminal command that ran at least this long tells
  the phone when it ends. 0: only commands Sora started.

Plain JavaScript with no dependencies and no build step. Tests: `pc_agent/tests/test_vscode_e2e.py` runs it
in a real VS Code (code-server).
