import 'package:flutter_test/flutter_test.dart';
import 'package:sora/chat/chat_models.dart';
import 'package:sora/l10n/strings.dart';

Approval _approval(String tool, Map<String, dynamic> args, [String summary = '']) =>
    Approval({'action_id': '1', 'tool': tool, 'summary': summary, 'args': args});

void main() {
  test('VS Code and Claude Code show under their own names', () {
    expect(toolLabel('vscode'), 'VS Code');
    expect(toolLabel('claude_code'), 'Claude Code');
  });

  test('a terminal command shows what will run, and where', () {
    final v = ApprovalView.of(
      _approval('vscode', {'action': 'terminal_run', 'text': 'python train.py --epochs 300', 'window': 'thesis', 'name': 'Sora'}),
      S.en,
    );
    expect((v.service, v.title, v.body), ('VS Code', 'Run in the VS Code terminal', 'python train.py --epochs 300'));
    expect(v.fields, [('Window', 'thesis'), ('Terminal', 'Sora')]);
    final bn = ApprovalView.of(_approval('vscode', {'action': 'git_commit', 'text': 'Fix lr'}), S.bn);
    expect((bn.title, bn.body), ('Git commit করা', 'Fix lr'));
  });

  test('a Claude Code job shows the project, the job and what else it may do', () {
    final v = ApprovalView.of(
      _approval('claude_code', {
        'action': 'start',
        'project': 'thesis',
        'prompt': 'fix the failing tests',
        'allow': ['Bash(python -m pytest *)'],
      }),
      S.bn,
    );
    expect(v.service, 'Claude Code');
    expect(v.title, 'Claude Code-কে কাজ দেওয়া');
    expect(v.fields, [('প্রজেক্ট', 'thesis'), ('আরও অনুমতি', 'Bash(python -m pytest *)')]);
    expect(v.body, 'fix the failing tests\n\nপ্রজেক্টের ফাইল বদলাতে পারবে।');
    expect(ApprovalView.of(_approval('claude_code', {'action': 'continue', 'project': 'x'}), S.en).title, 'Let Claude Code carry on');
  });

  test('anything without its own card uses the server summary', () {
    final v = ApprovalView.of(_approval('vscode', {'action': 'terminals'}, 'VS Code: terminals'), S.en);
    expect((v.service, v.title), ('VS Code', 'VS Code: terminals'));
  });

  test('every new string has both languages', () {
    for (final get in <String Function(S)>[
      (s) => s.vsRun,
      (s) => s.vsTask,
      (s) => s.vsDebug,
      (s) => s.vsStop,
      (s) => s.vsCloseTerminal,
      (s) => s.vsWrite,
      (s) => s.vsEdit,
      (s) => s.vsRename,
      (s) => s.vsDelete,
      (s) => s.vsCommand,
      (s) => s.vsSetting,
      (s) => s.vsInstallExt,
      (s) => s.vsOpen,
      (s) => s.gitPush,
      (s) => s.gitPull,
      (s) => s.gitBranch,
      (s) => s.claudeStart,
      (s) => s.claudeContinue,
      (s) => s.claudeMayEdit,
    ]) {
      expect(get(S.bn), isNot(get(S.en)));
    }
  });
}
