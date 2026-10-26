import 'package:flutter/widgets.dart';
import 'package:intl/intl.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../l10n/strings.dart';

/// What the owner sees while a tool runs, instead of the tool's internal name.
String toolLabel(String name) => _service(name).$1;

IconData toolIcon(String name) => _service(name).$2;

/// Service label and icon for a tool name (`gmail_search` → Gmail / mail), as in the design's `TOOLS`.
(String, IconData) _service(String name) {
  const known = <String, (String, IconData)>{
    'gmail': ('Gmail', Symbols.mail_rounded),
    'calendar': ('Calendar', Symbols.calendar_month_rounded),
    'drive': ('Drive', Symbols.add_to_drive_rounded),
    'docs': ('Docs', Symbols.description_rounded),
    'sheets': ('Sheets', Symbols.table_chart_rounded),
    'slides': ('Slides', Symbols.slideshow_rounded),
    'tasks': ('Tasks', Symbols.task_alt_rounded),
    'contacts': ('Contacts', Symbols.contacts_rounded),
    'memory': ('Memory', Symbols.psychology_rounded),
    'knowledge': ('Notes', Symbols.menu_book_rounded),
    'reminder': ('Reminder', Symbols.alarm_rounded),
    'routine': ('Routines', Symbols.event_repeat_rounded),
    'pc': ('PC', Symbols.computer_rounded),
    'phone': ('Phone', Symbols.smartphone_rounded),
    'web': ('Web', Symbols.public_rounded),
    'browser': ('Browser', Symbols.travel_explore_rounded),
    'vscode': ('VS Code', Symbols.code_blocks_rounded),
    'claude': ('Claude Code', Symbols.smart_toy_rounded),
    'email': ('Email rules', Symbols.rule_rounded),
    'notifications': ('Notifications', Symbols.notifications_rounded),
    'devices': ('Devices', Symbols.devices_rounded),
  };
  return known[name.split('_').first] ?? (name, Symbols.build_rounded);
}

enum ToolState { run, ok, fail }

/// One service chip under a Sora message. Several calls to the same service share one chip.
class ToolChipData {
  ToolChipData(this.label, this.icon);

  final String label;
  final IconData icon;
  int running = 0, ok = 0, failed = 0;

  ToolState get state => running > 0 ? ToolState.run : (ok == 0 && failed > 0 ? ToolState.fail : ToolState.ok);
}

enum ApprovalStatus { pending, busy, done, cancelled, failed }

/// An action waiting for the owner's yes/no (`confirmation_required`).
class Approval {
  Approval(this.action);

  final Map<String, dynamic> action;
  ApprovalStatus status = ApprovalStatus.pending;
  bool expanded = false;

  String get id => action['action_id'] as String;
  String get tool => action['tool'] as String? ?? '';
  Map<String, dynamic> get args => Map<String, dynamic>.from(action['args'] as Map? ?? const {});
  String get summary => action['summary'] as String? ?? '';

  /// True when Sora only asks because content from an email (or other outside source) is in the chat.
  bool get tainted => action['reason'] == 'tainted';
}

/// The card's look for one action: header icon + service, a title, field rows and an optional body.
class ApprovalView {
  ApprovalView({required this.icon, required this.service, required this.title, this.fields = const [], this.body});

  final IconData icon;
  final String service, title;
  final List<(String, String)> fields;
  final String? body;

  factory ApprovalView.of(Approval a, S s) {
    final args = a.args;
    String? str(String k) {
      final v = args[k];
      if (v == null) return null;
      final t = v is List ? v.join(', ') : v.toString();
      return t.trim().isEmpty ? null : t;
    }

    final fields = <(String, String)>[];
    void add(String label, String? value) {
      if (value != null) fields.add((s.field(label), value));
    }

    switch (a.tool) {
      case 'gmail_send':
        add('To', str('to'));
        add('Cc', str('cc'));
        add('Subject', str('subject'));
        return ApprovalView(icon: Symbols.mail_rounded, service: 'Gmail', title: s.sendEmail, fields: fields, body: str('body'));
      case 'gmail_reply':
        return ApprovalView(icon: Symbols.reply_rounded, service: 'Gmail', title: s.replyEmail, body: str('body'));
      case 'gmail_modify':
        add('Emails', s.num((args['message_ids'] as List?)?.length ?? 1));
        return ApprovalView(icon: Symbols.delete_rounded, service: 'Gmail', title: s.trashEmail, fields: fields);
      case 'calendar_create_event':
        add('Title', str('summary'));
        add('When', _when(str('start'), str('end'), s));
        add('Where', str('location'));
        add('Guests', str('attendees'));
        return ApprovalView(icon: Symbols.calendar_month_rounded, service: 'Calendar', title: s.createInvite, fields: fields, body: str('description'));
      case 'calendar_update_event':
        add('Event', str('summary') ?? str('event_id'));
        add('When', _when(str('start'), str('end'), s));
        add('Guests', str('attendees'));
        return ApprovalView(icon: Symbols.edit_calendar_rounded, service: 'Calendar', title: s.updateEvent, fields: fields);
      case 'calendar_delete_event':
        add('Event', str('summary') ?? str('event_id'));
        return ApprovalView(icon: Symbols.event_busy_rounded, service: 'Calendar', title: s.deleteEvent, fields: fields);
      case 'pc_action':
        final action = str('action') ?? '';
        add('PC', str('device'));
        add('Command', [action.replaceAll('_', ' '), ?str('target')].join(' · '));
        return ApprovalView(icon: Symbols.computer_rounded, service: 'PC', title: s.pcAction(action), fields: fields, body: str('text'));
      case 'phone_action':
        final action = str('action') ?? '';
        switch (action) {
          case 'send_sms':
            add('To', str('target'));
            return ApprovalView(icon: Symbols.sms_rounded, service: 'Phone', title: s.sendSms, fields: fields, body: str('text'));
          case 'call':
            add('To', str('target'));
            return ApprovalView(icon: Symbols.call_rounded, service: 'Phone', title: s.makeCall, fields: fields);
          case 'open_url':
            add('Link', str('target'));
            return ApprovalView(icon: Symbols.open_in_new_rounded, service: 'Phone', title: s.openLink, fields: fields);
          case 'reply_notification':
            // The target may be the notification's key: the server's summary names the person ("reply to Ammu (WhatsApp)").
            final to = RegExp(r'reply to (.+?): ').firstMatch(a.summary)?.group(1) ?? str('target');
            add('To', to);
            return ApprovalView(icon: Symbols.reply_rounded, service: 'Phone', title: s.replyNotif, fields: fields, body: str('text'));
          case 'whatsapp_send':
            add('To', str('target'));
            return ApprovalView(icon: Symbols.chat_rounded, service: 'WhatsApp', title: s.sendWhatsapp, fields: fields, body: str('text'));
          default:
            add('Command', [action.replaceAll('_', ' '), ?str('target')].join(' · '));
            return ApprovalView(icon: Symbols.smartphone_rounded, service: 'Phone', title: s.phoneAction(action), fields: fields);
        }
      case 'sheets_write':
        add('Sheet', str('spreadsheet_id'));
        add('Rows', s.num((args['rows'] as List?)?.length ?? 0));
        return ApprovalView(icon: Symbols.table_chart_rounded, service: 'Sheets', title: s.writeSheet, fields: fields);
      case 'docs_append':
        return ApprovalView(icon: Symbols.description_rounded, service: 'Docs', title: s.addToDoc, body: str('content'));
      case 'knowledge_delete':
        add('Title', str('title') ?? str('document_id'));
        return ApprovalView(icon: Symbols.menu_book_rounded, service: 'Knowledge', title: s.deleteKnowledge, fields: fields);
      case 'memory_save' || 'memory_update':
        return ApprovalView(icon: Symbols.psychology_rounded, service: 'Memory', title: s.saveMemory, body: str('fact'));
      case 'web_fetch' || 'knowledge_add_url':
        add('Link', str('url'));
        return ApprovalView(icon: Symbols.public_rounded, service: 'Web', title: s.openWebPage, fields: fields);
      case 'browser':
        switch (str('action')) {
          case 'click':
            return ApprovalView(
              icon: Symbols.ads_click_rounded,
              service: 'Browser',
              title: s.browserPress(str('text') ?? ''),
              body: s.browserCommits,
            );
          case 'fill':
            return ApprovalView(icon: Symbols.keyboard_rounded, service: 'Browser', title: s.browserType, body: str('text'));
          case 'download':
            add('Link', str('target'));
            return ApprovalView(icon: Symbols.download_rounded, service: 'Browser', title: s.downloadFile, fields: fields);
          default:
            add('Link', str('target'));
            return ApprovalView(icon: Symbols.travel_explore_rounded, service: 'Browser', title: s.openWebPage, fields: fields);
        }
      case 'vscode':
        add('Window', str('window'));
        const vs = 'VS Code';
        switch (str('action')) {
          case 'terminal_run':
            add('Terminal', str('name'));
            return ApprovalView(icon: Symbols.terminal_rounded, service: vs, title: s.vsRun, fields: fields, body: str('text'));
          case 'task_run':
            add('Task', str('name'));
            return ApprovalView(icon: Symbols.play_circle_rounded, service: vs, title: s.vsTask, fields: fields);
          case 'debug_start':
            add('Task', str('name'));
            return ApprovalView(icon: Symbols.bug_report_rounded, service: vs, title: s.vsDebug, fields: fields);
          case 'terminal_stop' || 'terminal_close':
            add('Terminal', str('name'));
            final stop = str('action') == 'terminal_stop';
            return ApprovalView(
              icon: stop ? Symbols.stop_circle_rounded : Symbols.close_rounded,
              service: vs,
              title: stop ? s.vsStop : s.vsCloseTerminal,
              fields: fields,
            );
          case 'git_commit':
            return ApprovalView(icon: Symbols.commit_rounded, service: vs, title: s.gitCommit, fields: fields, body: str('text'));
          case 'git_push' || 'git_pull' || 'git_branch':
            add('Item', str('name'));
            final title = switch (str('action')) {
              'git_push' => s.gitPush,
              'git_pull' => s.gitPull,
              _ => s.gitBranch,
            };
            return ApprovalView(icon: Symbols.cloud_upload_rounded, service: vs, title: title, fields: fields);
          case 'write_file' || 'edit':
            add('File', str('path'));
            final write = str('action') == 'write_file';
            return ApprovalView(
              icon: Symbols.edit_document_rounded,
              service: vs,
              title: write ? s.vsWrite : s.vsEdit,
              fields: fields,
              body: write ? str('text') : str('new_text'),
            );
          case 'rename':
            add('File', str('path'));
            add('To', str('text'));
            return ApprovalView(icon: Symbols.drive_file_rename_outline_rounded, service: vs, title: s.vsRename, fields: fields);
          case 'delete':
            add('File', str('path'));
            return ApprovalView(icon: Symbols.delete_rounded, service: vs, title: s.vsDelete, fields: fields);
          case 'command':
            add('Command', str('name'));
            return ApprovalView(icon: Symbols.code_rounded, service: vs, title: s.vsCommand, fields: fields, body: str('text'));
          case 'setting':
            add('Setting', str('name'));
            return ApprovalView(icon: Symbols.settings_rounded, service: vs, title: s.vsSetting, fields: fields, body: str('text'));
          case 'extension_install':
            add('Item', str('name'));
            return ApprovalView(icon: Symbols.extension_rounded, service: vs, title: s.vsInstallExt, fields: fields);
          case 'open' || 'new_window':
            add('Project', str('path'));
            return ApprovalView(icon: Symbols.folder_open_rounded, service: vs, title: s.vsOpen, fields: fields);
        }
      case 'claude_code':
        add('Project', str('project'));
        add('Also allowed', str('allow'));
        return ApprovalView(
          icon: Symbols.smart_toy_rounded,
          service: 'Claude Code',
          title: str('action') == 'continue' ? s.claudeContinue : s.claudeStart,
          fields: fields,
          body: [?str('prompt'), s.claudeMayEdit].join('\n\n'),
        );
    }
    // Anything else: the server's own description, first line as the title.
    final lines = a.summary.trim().split('\n');
    final rest = lines.skip(1).join('\n').trim();
    return ApprovalView(
      icon: toolIcon(a.tool),
      service: toolLabel(a.tool),
      title: lines.first,
      body: rest.isEmpty ? null : rest,
    );
  }

  /// "Fri, Oct 18 · 3:30 – 4:30 pm" from ISO strings; falls back to the raw text.
  static String? _when(String? start, String? end, S s) {
    if (start == null) return null;
    final a = DateTime.tryParse(start);
    if (a == null) return start;
    final loc = s.code;
    final allDay = !start.contains('T');
    final day = DateFormat('EEE, MMM d', loc).format(a);
    if (allDay) return day;
    final t = DateFormat('h:mm a', loc);
    final b = end == null ? null : DateTime.tryParse(end);
    return '$day · ${t.format(a)}${b != null ? ' – ${t.format(b)}' : ''}';
  }
}

/// One chat entry: the owner's text, or one Sora turn (tool chips, reply, approvals, error).
class ChatMessage {
  ChatMessage.user(String text) : fromUser = true, prompt = null, committed = text;
  ChatMessage.sora({this.prompt}) : fromUser = false, committed = '';

  static int _ids = 0;
  final int id = _ids++;
  final bool fromUser;

  /// For Sora turns: the owner message that produced it (used by Regenerate).
  final String? prompt;

  /// Finished text from earlier LLM rounds plus the round being streamed.
  String committed;
  String live = '';
  String get text => [committed, live].where((t) => t.trim().isNotEmpty).join('\n\n');
  set text(String v) {
    committed = v;
    live = '';
  }

  final Map<String, ToolChipData> tools = {};
  final List<Approval> approvals = [];
  String? error;
  bool working = false;
  String? feedback; // 'up' | 'down'

  bool get typing => working && text.isEmpty && tools.isEmpty;
  bool get done => !working;

  void toolStarted(String name) {
    final label = toolLabel(name);
    (tools[label] ??= ToolChipData(label, toolIcon(name))).running++;
  }

  void toolFinished(String name, bool ok) {
    final chip = tools[toolLabel(name)];
    if (chip == null) return;
    if (chip.running > 0) chip.running--;
    ok ? chip.ok++ : chip.failed++;
  }
}
