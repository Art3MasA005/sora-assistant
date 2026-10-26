// Sora Bridge: lets Sora work in this VS Code window for the owner, through the Sora PC agent.
//
// - The PC agent listens on 127.0.0.1 and writes its port and a token to vscode-bridge.json
//   (%LOCALAPPDATA%\Sora on Windows, ~/.sora elsewhere). Each VS Code window connects, says which
//   folders it has open, and answers the agent's requests: newline-separated JSON over the socket.
// - Nothing polls: the file is watched, and a lost connection is retried with a growing pause.
// - Files Sora changes must be inside this window's folders. Changes go through WorkspaceEdit, so
//   Ctrl+Z undoes them.
// - Terminal commands are seen through VS Code's shell integration (exit code and output). The
//   output of each terminal's latest command is kept, cut to KEEP characters.

'use strict';

const vscode = require('vscode');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const crypto = require('crypto');

const WIN = process.platform === 'win32';
const KEEP = 20000; // characters of output kept per terminal
const MAX_LINE = 8 * 1024 * 1024;
const MAX_READ = 2 * 1024 * 1024; // bytes: bigger files are not read
const EXCLUDE = '**/{node_modules,.git,.venv,venv,__pycache__,.dart_tool,build,dist,.next,.idea,.gradle}/**';
const NO_FOLDER = "this VS Code window has no folder open; open a project first";

let link = null;
let windowId = crypto.randomBytes(6).toString('hex');

// ---------------------------------------------------------------- the line to the PC agent

function bridgeFile() {
  if (process.env.SORA_BRIDGE_FILE) return process.env.SORA_BRIDGE_FILE;
  if (WIN) return path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'), 'Sora', 'vscode-bridge.json');
  return path.join(os.homedir(), '.sora', 'vscode-bridge.json');
}

class Link {
  constructor(version) {
    this.version = version;
    this.socket = null;
    this.pause = 2000;
    this.timer = null;
    this.watcher = null;
    this.stopped = false;
  }

  start() {
    const file = bridgeFile();
    try {
      fs.mkdirSync(path.dirname(file), { recursive: true });
      // The agent rewrites the file when it starts: connect again then.
      this.watcher = fs.watch(path.dirname(file), (_event, name) => {
        if (!name || name === path.basename(file)) this.soon(300);
      });
    } catch (err) {
      console.warn('Sora Bridge: cannot watch', file, err);
    }
    this.connect();
  }

  soon(ms) {
    if (this.stopped) return;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.connect(), ms);
  }

  connect() {
    if (this.stopped || this.socket) return;
    let info;
    try {
      info = JSON.parse(fs.readFileSync(bridgeFile(), 'utf8'));
    } catch {
      return; // the agent isn't running: the watcher calls again when it starts
    }
    const socket = net.connect({ host: '127.0.0.1', port: info.port });
    this.socket = socket;
    let buffer = '';
    socket.setEncoding('utf8');
    socket.setNoDelay(true);
    socket.on('connect', () => {
      this.pause = 2000;
      this.send({ type: 'hello', token: info.token, window: windowInfo(), version: this.version, vscode: vscode.version, ops: Object.keys(OPS) });
    });
    socket.on('data', (chunk) => {
      buffer += chunk;
      if (buffer.length > MAX_LINE) {
        socket.destroy();
        return;
      }
      let end;
      while ((end = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, end);
        buffer = buffer.slice(end + 1);
        if (line.trim()) this.received(line);
      }
    });
    socket.on('error', () => {});
    socket.on('close', () => {
      this.socket = null;
      if (this.stopped) return;
      this.soon(this.pause);
      this.pause = Math.min(60000, this.pause * 2);
    });
  }

  received(line) {
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      return;
    }
    if (msg.type === 'request') handle(msg);
  }

  send(msg) {
    if (!this.socket || this.socket.destroyed) return false;
    this.socket.write(JSON.stringify(msg) + '\n');
    return true;
  }

  stop() {
    this.stopped = true;
    clearTimeout(this.timer);
    if (this.watcher) this.watcher.close();
    if (this.socket) this.socket.destroy();
  }
}

function windowInfo() {
  return {
    id: windowId,
    name: vscode.workspace.name || '',
    folders: (vscode.workspace.workspaceFolders || []).map((f) => ({ name: f.name, path: f.uri.scheme === 'file' ? f.uri.fsPath : f.uri.toString() })),
    focused: vscode.window.state.focused,
    remote: vscode.env.remoteName || null,
  };
}

async function handle(msg) {
  const op = OPS[msg.action];
  try {
    if (!op) throw new Error(`this Sora Bridge has no '${msg.action}' (update the extension)`);
    const data = await op(msg.params || {});
    link.send({ type: 'response', id: msg.id, ok: true, data: data === undefined ? null : data });
  } catch (err) {
    link.send({ type: 'response', id: msg.id, ok: false, error: String((err && err.message) || err) });
  }
}

function event(name, fields) {
  if (link) link.send({ type: 'event', event: name, window: windowInfo().folders.map((f) => f.name).join(', '), ...fields });
}

// ---------------------------------------------------------------- paths inside this window's folders

function folders() {
  const list = vscode.workspace.workspaceFolders || [];
  if (!list.length) throw new Error(NO_FOLDER);
  return list;
}

function inside(child, parent) {
  const norm = (s) => (WIN ? s.toLowerCase() : s).replace(/\/+$/, '');
  const c = norm(child);
  const p = norm(parent);
  return c === p || c.startsWith(p + '/');
}

/** A path from Sora: relative to the (first) folder, "folder/rest" in a multi-folder window, or absolute. */
function target(raw) {
  const list = folders();
  const p = String(raw || '').trim();
  if (!p) throw new Error('give a file path');
  let uri;
  if (/^[a-zA-Z]:[\\/]/.test(p) || p.startsWith('/') || p.startsWith('\\\\')) {
    uri = vscode.Uri.file(p);
  } else {
    const parts = p.replace(/\\/g, '/').split('/').filter((s) => s && s !== '.');
    let folder = list[0];
    if (list.length > 1 && parts.length > 1) {
      const named = list.find((f) => f.name.toLowerCase() === parts[0].toLowerCase());
      if (named) {
        folder = named;
        parts.shift();
      }
    }
    uri = vscode.Uri.joinPath(folder.uri, ...parts); // joinPath resolves "..": checked below
  }
  // Uri.file keeps "..": "C:/project/../secret" would pass the check below and still reach C:/secret.
  uri = uri.with({ path: path.posix.normalize(uri.path) });
  if (!list.some((f) => f.uri.scheme === uri.scheme && inside(uri.path, f.uri.path))) {
    throw new Error(`${p} is outside this window's folders (${list.map((f) => f.name).join(', ')}), so Sora won't touch it`);
  }
  return uri;
}

function rel(uri) {
  return vscode.workspace.asRelativePath(uri, (vscode.workspace.workspaceFolders || []).length > 1);
}

async function exists(uri) {
  try {
    return await vscode.workspace.fs.stat(uri);
  } catch {
    return null;
  }
}

function isRoot(uri) {
  return folders().some((f) => f.uri.scheme === uri.scheme && inside(f.uri.path, uri.path));
}

// ---------------------------------------------------------------- files

async function openFile(p) {
  const uri = target(p.path);
  if (!(await exists(uri))) throw new Error(`${p.path} does not exist`);
  const doc = await vscode.workspace.openTextDocument(uri);
  const line = Math.max(0, Math.min(doc.lineCount - 1, (Number(p.line) || 1) - 1));
  const at = new vscode.Position(line, 0);
  await vscode.window.showTextDocument(doc, { preview: false, selection: new vscode.Range(at, at) });
  return { opened: rel(uri), line: line + 1, lines: doc.lineCount };
}

async function readFile(p) {
  const uri = target(p.path);
  const stat = await exists(uri);
  if (!stat) throw new Error(`${p.path} does not exist`);
  if (stat.type & vscode.FileType.Directory) return { folder: rel(uri), files: await listDir(uri) };
  if (stat.size > MAX_READ) throw new Error(`${p.path} is ${Math.round(stat.size / 1024)} KB: too big to read`);
  const doc = await vscode.workspace.openTextDocument(uri); // includes changes not saved yet
  const first = Math.max(1, Number(p.line) || 1);
  const last = Math.min(doc.lineCount, Number(p.end_line) || first + 399);
  const lines = [];
  for (let i = first - 1; i < last; i++) lines.push(`${String(i + 1).padStart(5)}| ${doc.lineAt(i).text}`);
  let text = lines.join('\n');
  const cut = text.length > 24000;
  if (cut) text = text.slice(0, 24000);
  return { path: rel(uri), lines: doc.lineCount, from: first, to: last, unsaved: doc.isDirty, text, more: cut || last < doc.lineCount };
}

async function listDir(uri) {
  const entries = await vscode.workspace.fs.readDirectory(uri);
  return entries
    .map(([name, type]) => (type & vscode.FileType.Directory ? name + '/' : name))
    .sort()
    .slice(0, 300);
}

async function save(doc) {
  if (doc.isDirty && !(await doc.save())) throw new Error(`could not save ${rel(doc.uri)}`);
}

async function writeFile(p) {
  const uri = target(p.path);
  const text = String(p.text ?? '');
  const stat = await exists(uri);
  const edit = new vscode.WorkspaceEdit();
  if (stat) {
    if (stat.type & vscode.FileType.Directory) throw new Error(`${p.path} is a folder`);
    if (Number(p.value) !== 1) throw new Error(`${p.path} already exists: call again with value=1 to replace all of it, or use edit to change a part`);
    const doc = await vscode.workspace.openTextDocument(uri);
    edit.replace(uri, doc.validateRange(new vscode.Range(0, 0, doc.lineCount, 0)), text);
  } else {
    edit.createFile(uri, { ignoreIfExists: true });
    edit.insert(uri, new vscode.Position(0, 0), text);
  }
  if (!(await vscode.workspace.applyEdit(edit))) throw new Error(`VS Code refused to write ${p.path}`);
  const doc = await vscode.workspace.openTextDocument(uri);
  await save(doc);
  await vscode.window.showTextDocument(doc, { preview: false, preserveFocus: true });
  return { [stat ? 'replaced' : 'created']: rel(uri), lines: doc.lineCount };
}

async function editFile(p) {
  const uri = target(p.path);
  if (!(await exists(uri))) throw new Error(`${p.path} does not exist`);
  const old = String(p.text ?? '');
  if (!old) throw new Error('give text= the exact text to change (read the file first)');
  const doc = await vscode.workspace.openTextDocument(uri);
  const all = doc.getText();
  const at = [];
  for (let i = all.indexOf(old); i >= 0; i = all.indexOf(old, i + old.length)) at.push(i);
  if (!at.length) throw new Error(`that text is not in ${p.path} (it must match exactly, spaces too): read the file again`);
  if (at.length > 1 && Number(p.value) !== 1) throw new Error(`that text is in ${p.path} ${at.length} times: give more of it, or value=1 to change all`);
  const edit = new vscode.WorkspaceEdit();
  for (const i of at) edit.replace(uri, new vscode.Range(doc.positionAt(i), doc.positionAt(i + old.length)), String(p.new_text ?? ''));
  if (!(await vscode.workspace.applyEdit(edit))) throw new Error(`VS Code refused to change ${p.path}`);
  await save(doc);
  return { changed: rel(uri), places: at.length, line: doc.positionAt(at[0]).line + 1 };
}

async function renameFile(p) {
  const from = target(p.path);
  const to = target(p.text);
  if (!(await exists(from))) throw new Error(`${p.path} does not exist`);
  if (await exists(to)) throw new Error(`${p.text} already exists`);
  if (isRoot(from)) throw new Error('that is a whole project folder');
  const edit = new vscode.WorkspaceEdit();
  edit.renameFile(from, to, { overwrite: false });
  if (!(await vscode.workspace.applyEdit(edit))) throw new Error('VS Code refused to rename it');
  return { renamed: rel(from), to: rel(to) };
}

async function deleteFile(p) {
  const uri = target(p.path);
  if (!(await exists(uri))) throw new Error(`${p.path} does not exist`);
  if (isRoot(uri)) throw new Error("that is a whole project folder: Sora doesn't delete those");
  try {
    await vscode.workspace.fs.delete(uri, { recursive: true, useTrash: true });
  } catch (err) {
    // A remote folder (WSL, SSH) may have no bin: then nothing is deleted for good.
    if (/trash/i.test(String(err && err.message))) throw new Error("this folder has no Recycle Bin (a remote folder), so Sora won't delete it");
    throw err;
  }
  return { deleted: rel(uri), to: 'the Recycle Bin' };
}

async function listFiles(p) {
  folders();
  const found = await vscode.workspace.findFiles(p.text || '**/*', EXCLUDE, 2000);
  const names = found.map(rel).sort();
  return { count: names.length, files: names.slice(0, 300), more: names.length > 300 };
}

async function search(p) {
  folders();
  const query = String(p.text || '');
  if (!query) throw new Error('give text= what to look for');
  let match;
  if (Number(p.value) === 1) {
    const re = new RegExp(query, 'i');
    match = (line) => re.test(line);
  } else {
    const needle = query.toLowerCase();
    match = (line) => line.toLowerCase().includes(needle);
  }
  const files = await vscode.workspace.findFiles(p.path || '**/*', EXCLUDE, 5000);
  const hits = [];
  let scanned = 0;
  for (const uri of files) {
    if (hits.length >= 100) break;
    const stat = await exists(uri);
    if (!stat || stat.size > 1024 * 1024) continue;
    const bytes = await vscode.workspace.fs.readFile(uri);
    if (bytes.subarray(0, 8000).includes(0)) continue; // binary
    scanned++;
    const lines = Buffer.from(bytes).toString('utf8').split(/\r?\n/);
    for (let i = 0; i < lines.length && hits.length < 100; i++) {
      if (match(lines[i])) hits.push({ path: rel(uri), line: i + 1, text: lines[i].trim().slice(0, 200) });
    }
  }
  return { matches: hits, files_searched: scanned, more: hits.length >= 100 };
}

async function saveAll() {
  const dirty = vscode.workspace.textDocuments.filter((d) => d.isDirty).map((d) => rel(d.uri));
  await vscode.workspace.saveAll(false);
  return { saved: dirty };
}

function editorState() {
  const ed = vscode.window.activeTextEditor;
  const tabs = vscode.window.tabGroups.all.flatMap((g) => g.tabs).map((t) => (t.input && t.input.uri ? rel(t.input.uri) : t.label));
  return {
    active: ed
      ? {
          path: rel(ed.document.uri),
          language: ed.document.languageId,
          line: ed.selection.active.line + 1,
          selected: ed.document.getText(ed.selection).slice(0, 6000),
          unsaved: ed.document.isDirty,
        }
      : null,
    open_tabs: tabs.slice(0, 40),
    unsaved: vscode.workspace.textDocuments.filter((d) => d.isDirty && d.uri.scheme !== 'output').map((d) => rel(d.uri)),
    folders: windowInfo().folders,
  };
}

function problems(p) {
  const want = p.path ? target(p.path) : null;
  const items = [];
  let errors = 0;
  let warnings = 0;
  for (const [uri, list] of vscode.languages.getDiagnostics()) {
    if (want && uri.toString() !== want.toString()) continue;
    for (const d of list) {
      if (d.severity > vscode.DiagnosticSeverity.Warning) continue;
      if (d.severity === vscode.DiagnosticSeverity.Error) errors++;
      else warnings++;
      items.push({
        path: rel(uri),
        line: d.range.start.line + 1,
        severity: d.severity === vscode.DiagnosticSeverity.Error ? 'error' : 'warning',
        message: d.message.slice(0, 300),
        source: d.source || '',
      });
    }
  }
  items.sort((a, b) => (a.severity === b.severity ? a.path.localeCompare(b.path) || a.line - b.line : a.severity === 'error' ? -1 : 1));
  return { errors, warnings, items: items.slice(0, 60) };
}

// ---------------------------------------------------------------- terminals

const runs = new Map(); // terminal -> what its latest command printed
const sora = new WeakMap(); // executions Sora started -> { reported }
const waiting = new Map(); // execution -> resolve()

/** Terminal output without colours and cursor moves; a line redrawn with \r keeps its last state. */
function clean(text) {
  return text
    .replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, '')
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/\x1b[@-_]/g, '')
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map((line) => line.slice(line.lastIndexOf('\r') + 1))
    .join('\n');
}

function tail(text, n) {
  const out = clean(text).trimEnd();
  return out.length > n ? '…' + out.slice(-n) : out;
}

function record(terminal) {
  let r = runs.get(terminal);
  if (!r) runs.set(terminal, (r = { out: '', command: '', running: false, started: 0, ended: 0, exit: undefined }));
  return r;
}

function watchTerminals(context) {
  context.subscriptions.push(
    vscode.window.onDidStartTerminalShellExecution(async (e) => {
      const r = record(e.terminal);
      Object.assign(r, { out: '', command: e.execution.commandLine.value, running: true, started: Date.now(), ended: 0, exit: undefined, execution: e.execution });
      try {
        for await (const chunk of e.execution.read()) {
          if (r.execution !== e.execution) break; // a newer command took over
          r.out = (r.out + chunk).slice(-KEEP);
        }
      } catch {
        // the terminal went away
      }
    }),
    vscode.window.onDidEndTerminalShellExecution((e) => {
      const r = record(e.terminal);
      if (r.execution === e.execution) Object.assign(r, { running: false, ended: Date.now(), exit: e.exitCode });
      const done = waiting.get(e.execution);
      if (done) done();
      // Wait a moment: the last output arrives just after the end event.
      setTimeout(() => finished(e.terminal, e.execution, r), 300);
    }),
    vscode.window.onDidCloseTerminal((t) => runs.delete(t)),
  );
}

function finished(terminal, execution, r) {
  const mine = sora.get(execution);
  const seconds = Math.round(((r.ended || Date.now()) - r.started) / 1000);
  const long = vscode.workspace.getConfiguration('sora').get('longCommandMinutes', 3);
  if ((mine && !mine.reported) || (!mine && long > 0 && seconds >= long * 60)) {
    event('command_done', {
      terminal: terminal.name,
      command: execution.commandLine.value.slice(0, 200),
      exit_code: r.exit ?? null,
      seconds,
      tail: tail(r.out, 600).split('\n').slice(-6).join('\n'),
      by_sora: Boolean(mine),
    });
  }
}

function findTerminal(name, { create = false } = {}) {
  const all = vscode.window.terminals;
  if (name) {
    const n = String(name).toLowerCase();
    const found = all.find((t) => t.name.toLowerCase() === n) || all.find((t) => t.name.toLowerCase().includes(n));
    if (found) return found;
    if (!create) throw new Error(`no terminal named ${name} (open: ${all.map((t) => t.name).join(', ') || 'none'})`);
  } else if (!create) {
    const active = vscode.window.activeTerminal || all[all.length - 1];
    if (!active) throw new Error('no terminal is open');
    return active;
  }
  return null;
}

function newTerminal(name) {
  const cwd = (vscode.workspace.workspaceFolders || [])[0];
  return vscode.window.createTerminal({ name: name || 'Sora', cwd: cwd ? cwd.uri : undefined });
}

function shellIntegration(terminal, ms) {
  if (terminal.shellIntegration) return Promise.resolve(terminal.shellIntegration);
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      sub.dispose();
      resolve(terminal.shellIntegration || null);
    }, ms);
    const sub = vscode.window.onDidChangeTerminalShellIntegration((e) => {
      if (e.terminal === terminal) {
        clearTimeout(timer);
        sub.dispose();
        resolve(e.shellIntegration);
      }
    });
  });
}

async function terminalRun(p) {
  const command = String(p.text || '').trim();
  if (!command) throw new Error('give text= the command to run');
  if (command.length > 4000) throw new Error('that command is too long');
  let terminal = findTerminal(p.name, { create: true });
  if (terminal && runs.get(terminal)?.running) {
    if (p.name) throw new Error(`terminal ${terminal.name} is still running: ${runs.get(terminal).command} (stop it first, or use another terminal)`);
    terminal = null;
  }
  if (!terminal) {
    const sorts = vscode.window.terminals.filter((t) => t.name.startsWith('Sora'));
    terminal = sorts.find((t) => !runs.get(t)?.running) || newTerminal(p.name || (sorts.length ? `Sora ${sorts.length + 1}` : 'Sora'));
  }
  terminal.show(true);
  const fresh = !terminal.shellIntegration;
  const si = await shellIntegration(terminal, 6000);
  // A command sent the moment a new shell reports in can be missed by shell integration: let it settle.
  if (si && fresh) await new Promise((resolve) => setTimeout(resolve, 500));
  if (!si) {
    terminal.sendText(command, true);
    return { terminal: terminal.name, sent: true, note: "this terminal has no shell integration, so Sora can't see the result; look at the screen or use terminal_read later" };
  }
  const execution = si.executeCommand(command);
  const mine = { reported: false };
  sora.set(execution, mine);
  const wait = Math.max(0, Math.min(Number(p.wait ?? 30), 120)) * 1000;
  const ended = await new Promise((resolve) => {
    const timer = setTimeout(() => {
      waiting.delete(execution);
      resolve(false);
    }, wait);
    waiting.set(execution, () => {
      clearTimeout(timer);
      waiting.delete(execution);
      resolve(true);
    });
  });
  const r = record(terminal);
  if (!ended) {
    return { terminal: terminal.name, running: true, seconds: Math.round(wait / 1000), output_so_far: tail(r.out, 2000), note: 'still running: the owner gets a notification when it ends' };
  }
  mine.reported = true;
  await new Promise((resolve) => setTimeout(resolve, 300)); // the last output
  return { terminal: terminal.name, exit_code: r.exit ?? null, seconds: Math.round((r.ended - r.started) / 1000), output: tail(r.out, 6000) };
}

function terminalRead(p) {
  const terminal = findTerminal(p.name);
  const r = runs.get(terminal);
  if (!r) return { terminal: terminal.name, note: 'nothing seen in this terminal yet (no command since VS Code started, or no shell integration)' };
  return {
    terminal: terminal.name,
    command: r.command,
    running: r.running,
    exit_code: r.running ? null : r.exit ?? null,
    seconds: Math.round(((r.running ? Date.now() : r.ended) - r.started) / 1000),
    output: tail(r.out, Math.min(Number(p.value) || 8000, KEEP)),
  };
}

function terminals() {
  return vscode.window.terminals.map((t) => {
    const r = runs.get(t);
    return { name: t.name, running: r ? r.running : null, command: r ? r.command : null, active: t === vscode.window.activeTerminal };
  });
}

function terminalStop(p) {
  const terminal = findTerminal(p.name);
  terminal.sendText('\u0003', false); // Ctrl+C
  return { stopped: terminal.name, command: runs.get(terminal)?.command || null };
}

function terminalNew(p) {
  const terminal = newTerminal(p.name);
  terminal.show(false);
  return { terminal: terminal.name };
}

function terminalClose(p) {
  const terminal = findTerminal(p.name);
  const name = terminal.name;
  terminal.dispose();
  return { closed: name };
}

// ---------------------------------------------------------------- git (VS Code's own Git extension)

const STATUS = [
  'modified (staged)', 'added (staged)', 'deleted (staged)', 'renamed (staged)', 'copied (staged)', 'modified', 'deleted',
  'untracked', 'ignored', 'intent to add', 'intent to rename', 'type changed', 'added by us', 'added by them',
  'deleted by us', 'deleted by them', 'both added', 'both deleted', 'both modified (conflict)',
];

async function repo(p) {
  const ext = vscode.extensions.getExtension('vscode.git');
  if (!ext) throw new Error('the Git extension is switched off in VS Code');
  const api = (ext.isActive ? ext.exports : await ext.activate()).getAPI(1);
  const want = p.path ? target(p.path) : folders()[0].uri;
  const found = api.repositories
    .filter((r) => inside(want.path, r.rootUri.path) || inside(r.rootUri.path, want.path))
    .sort((a, b) => b.rootUri.path.length - a.rootUri.path.length);
  if (!found.length) throw new Error('no git repository in this project');
  return found[0];
}

async function gitStatus(p) {
  const r = await repo(p);
  const s = r.state;
  const list = (changes) => changes.slice(0, 100).map((c) => ({ path: rel(c.uri), status: STATUS[c.status] || String(c.status) }));
  return {
    branch: s.HEAD ? s.HEAD.name || s.HEAD.commit : null,
    upstream: s.HEAD && s.HEAD.upstream ? `${s.HEAD.upstream.remote}/${s.HEAD.upstream.name}` : null,
    ahead: s.HEAD ? s.HEAD.ahead : null,
    behind: s.HEAD ? s.HEAD.behind : null,
    staged: list(s.indexChanges),
    changed: list(s.workingTreeChanges),
    untracked: list(s.untrackedChanges || []),
    conflicts: list(s.mergeChanges),
  };
}

async function gitDiff(p) {
  const r = await repo(p);
  const staged = Number(p.value) === 1;
  let text;
  if (p.path) {
    const uri = target(p.path);
    text = staged ? await r.diffIndexWithHEAD(uri.fsPath) : await r.diffWithHEAD(uri.fsPath);
  } else {
    text = await r.diff(staged);
  }
  text = String(text || '');
  return { staged, diff: text.length > 20000 ? text.slice(0, 20000) + '\n… (cut)' : text || '(no changes)' };
}

async function gitCommit(p) {
  const r = await repo(p);
  const message = String(p.text || '').trim();
  if (!message) throw new Error('give text= the commit message');
  const s = r.state;
  let files = s.indexChanges.length;
  if (!files) {
    // Nothing staged: commit everything changed, new files too (what "Commit All" does).
    const all = [...s.workingTreeChanges, ...(s.untrackedChanges || [])].map((c) => c.uri.fsPath);
    if (!all.length) throw new Error('nothing to commit');
    await r.add(all);
    files = all.length;
  }
  await r.commit(message);
  return { committed: files, branch: r.state.HEAD ? r.state.HEAD.name : null, commit: r.state.HEAD ? r.state.HEAD.commit : null, message };
}

async function gitPush(p) {
  const r = await repo(p);
  const head = r.state.HEAD;
  if (!head || !head.name) throw new Error('not on a branch');
  if (head.upstream) await r.push();
  else await r.push('origin', head.name, true);
  return { pushed: head.name };
}

async function gitPull(p) {
  const r = await repo(p);
  await r.pull();
  return { pulled: r.state.HEAD ? r.state.HEAD.name : null, behind: r.state.HEAD ? r.state.HEAD.behind : null };
}

async function gitBranch(p) {
  const r = await repo(p);
  const name = String(p.name || '').trim();
  if (!name) {
    const refs = typeof r.getBranches === 'function' ? await r.getBranches({ remote: false }) : [];
    return { current: r.state.HEAD ? r.state.HEAD.name : null, branches: refs.map((b) => b.name).filter(Boolean).slice(0, 50) };
  }
  if (Number(p.value) === 1) await r.createBranch(name, true);
  else await r.checkout(name);
  return { branch: name, created: Number(p.value) === 1 };
}

async function gitLog(p) {
  const r = await repo(p);
  const commits = await r.log({ maxEntries: Math.min(Number(p.value) || 10, 50) });
  return commits.map((c) => ({ commit: c.hash.slice(0, 8), message: c.message.split('\n')[0].slice(0, 200), author: c.authorName, date: c.authorDate }));
}

// ---------------------------------------------------------------- tasks, debugging, commands, settings, extensions

async function listTasks() {
  const tasks = await vscode.tasks.fetchTasks();
  const launch = [];
  for (const f of vscode.workspace.workspaceFolders || []) {
    for (const c of vscode.workspace.getConfiguration('launch', f.uri).get('configurations') || []) launch.push(c.name);
  }
  return { tasks: tasks.map((t) => ({ name: t.name, source: t.source })).slice(0, 80), debug_configs: launch };
}

async function taskRun(p) {
  const name = String(p.name || '').trim().toLowerCase();
  const tasks = await vscode.tasks.fetchTasks();
  const task = tasks.find((t) => t.name.toLowerCase() === name) || tasks.find((t) => t.name.toLowerCase().includes(name));
  if (!name || !task) throw new Error(`no task named ${p.name || '?'} (tasks: ${tasks.map((t) => t.name).slice(0, 20).join(', ') || 'none'})`);
  const execution = await vscode.tasks.executeTask(task);
  const started = Date.now();
  const wait = Math.max(0, Math.min(Number(p.wait ?? 30), 120)) * 1000;
  const exit = await new Promise((resolve) => {
    let timer = null;
    const sub = vscode.tasks.onDidEndTaskProcess((e) => {
      if (e.execution !== execution) return;
      if (timer) {
        clearTimeout(timer);
        sub.dispose();
        resolve({ code: e.exitCode });
      } else {
        sub.dispose();
        event('task_done', { task: task.name, exit_code: e.exitCode ?? null, seconds: Math.round((Date.now() - started) / 1000) });
      }
    });
    timer = setTimeout(() => {
      timer = null; // from now on the end goes to the phone
      resolve(null);
    }, wait);
  });
  if (!exit) return { task: task.name, running: true, note: 'still running: the owner gets a notification when it ends' };
  return { task: task.name, exit_code: exit.code ?? null, seconds: Math.round((Date.now() - started) / 1000) };
}

async function debugStart(p) {
  const folder = folders()[0];
  const configs = vscode.workspace.getConfiguration('launch', folder.uri).get('configurations') || [];
  const name = p.name ? configs.find((c) => c.name.toLowerCase().includes(String(p.name).toLowerCase())) : configs[0];
  if (p.name && !name) throw new Error(`no debug configuration named ${p.name} (there are: ${configs.map((c) => c.name).join(', ') || 'none'})`);
  const ok = await vscode.debug.startDebugging(folder, name ? name.name : undefined);
  if (!ok) throw new Error('debugging did not start');
  return { debugging: name ? name.name : 'the default for the open file' };
}

async function debugStop() {
  const session = vscode.debug.activeDebugSession;
  await vscode.debug.stopDebugging();
  return { stopped: session ? session.name : null };
}

async function runCommand(p) {
  const id = String(p.name || '').trim();
  if (!id) throw new Error('give name= the command id');
  let args = [];
  if (p.text) {
    try {
      args = JSON.parse(p.text);
    } catch {
      throw new Error('text= must be the arguments as a JSON list');
    }
    if (!Array.isArray(args)) args = [args];
  }
  const result = await vscode.commands.executeCommand(id, ...args);
  let shown = null;
  try {
    shown = result === undefined ? null : JSON.parse(JSON.stringify(result));
    if (JSON.stringify(shown).length > 4000) shown = '(a long result)';
  } catch {
    shown = String(result).slice(0, 200);
  }
  return { ran: id, result: shown };
}

async function findCommands(p) {
  const words = String(p.text || '').toLowerCase().split(/\s+/).filter(Boolean);
  const all = await vscode.commands.getCommands(true);
  const found = all.filter((id) => words.every((w) => id.toLowerCase().includes(w)));
  return { commands: found.slice(0, 60), more: found.length > 60 };
}

async function setting(p) {
  const key = String(p.name || '').trim();
  if (!key) throw new Error('give name= the setting, e.g. editor.fontSize');
  const config = vscode.workspace.getConfiguration();
  if (p.text === undefined || p.text === null || p.text === '') return { setting: key, value: config.get(key) ?? null };
  let value;
  try {
    value = JSON.parse(p.text);
  } catch {
    value = String(p.text);
  }
  await config.update(key, value, vscode.ConfigurationTarget.Global);
  return { setting: key, value };
}

function extensions() {
  return vscode.extensions.all
    .filter((e) => !e.packageJSON.isBuiltin && !e.id.startsWith('vscode.'))
    .map((e) => ({ id: e.id, name: e.packageJSON.displayName || e.packageJSON.name, version: e.packageJSON.version, active: e.isActive }))
    .sort((a, b) => a.id.localeCompare(b.id));
}

async function installExtension(p) {
  const id = String(p.name || '').trim();
  if (!/^[\w-]+\.[\w.-]+$/.test(id)) throw new Error('give name= the extension id, e.g. ms-python.python');
  await vscode.commands.executeCommand('workbench.extensions.installExtension', id);
  return { installed: id };
}

const OPS = {
  info: async () => ({ ...windowInfo(), editor: editorState(), terminals: terminals() }),
  open_file: openFile,
  read_file: readFile,
  write_file: writeFile,
  edit: editFile,
  rename: renameFile,
  delete: deleteFile,
  files: listFiles,
  search,
  save: saveAll,
  editor: async () => editorState(),
  problems: async (p) => problems(p),
  terminals: async () => terminals(),
  terminal_run: terminalRun,
  terminal_read: async (p) => terminalRead(p),
  terminal_stop: async (p) => terminalStop(p),
  terminal_new: async (p) => terminalNew(p),
  terminal_close: async (p) => terminalClose(p),
  git_status: gitStatus,
  git_diff: gitDiff,
  git_commit: gitCommit,
  git_push: gitPush,
  git_pull: gitPull,
  git_branch: gitBranch,
  git_log: gitLog,
  tasks: listTasks,
  task_run: taskRun,
  debug_start: debugStart,
  debug_stop: debugStop,
  command: runCommand,
  commands: findCommands,
  setting,
  extensions: async () => extensions(),
  extension_install: installExtension,
};

// ---------------------------------------------------------------- start and stop

function activate(context) {
  link = new Link(context.extension.packageJSON.version);
  watchTerminals(context);
  const tell = () => link.send({ type: 'state', window: windowInfo() });
  context.subscriptions.push(
    vscode.window.onDidChangeWindowState((s) => {
      if ('focused' in s) tell();
    }),
    vscode.workspace.onDidChangeWorkspaceFolders(tell),
    { dispose: () => link.stop() },
  );
  link.start();
  return { ops: Object.keys(OPS), windowId: () => windowId };
}

function deactivate() {
  if (link) link.stop();
}

module.exports = { activate, deactivate, _test: { clean, tail, inside, OPS } };
