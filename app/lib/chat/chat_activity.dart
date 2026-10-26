import 'package:flutter/foundation.dart';
import 'package:flutter/scheduler.dart';

import 'chat_models.dart';

/// What the desktop Details panel shows about the open chat: actions waiting for the owner's yes/no
/// and the latest tool runs. The chat screen publishes after every change; the panel listens.
class ChatActivity extends ChangeNotifier {
  List<Approval> pending = const [];

  /// Tool runs, newest first (one entry per service per reply, like the chips).
  List<ToolChipData> tools = const [];

  /// The open conversation's title (the sidebar refreshes its Recent list when a new chat gets one).
  String? title;

  void Function(Approval approval, bool approve)? _decide;

  void decide(Approval approval, bool approve) => _decide?.call(approval, approve);

  void publish(List<ChatMessage> messages, void Function(Approval, bool) decide, {String? title}) {
    _decide = decide;
    final pend = [
      for (final a in messages.expand((m) => m.approvals))
        if (a.status == ApprovalStatus.pending) a,
    ];
    final runs = [for (final m in messages) ...m.tools.values].reversed.take(30).toList();
    if (listEquals(pend, pending) && _sameRuns(runs) && title == this.title) return;
    this.title = title;
    pending = pend;
    tools = runs;
    _states = [for (final t in runs) t.state];
    // The chat can publish while it is being built (its first load starts in initState); the panel
    // is a sibling, so it hears about it after the frame.
    final binding = SchedulerBinding.instance;
    if (binding.schedulerPhase == SchedulerPhase.persistentCallbacks) {
      binding.addPostFrameCallback((_) => notifyListeners());
    } else {
      notifyListeners();
    }
  }

  List<ToolState> _states = const [];

  bool _sameRuns(List<ToolChipData> runs) => listEquals(runs, tools) && listEquals([for (final t in runs) t.state], _states);
}
