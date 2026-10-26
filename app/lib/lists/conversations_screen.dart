import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../core/api.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/list_kit.dart';
import '../widgets/sora_widgets.dart';
import '../widgets/markdown_lite.dart';
import '../widgets/overlays.dart';

/// Conversations: search, Pinned and Recent sections, and per-row Pin / Rename / Archive / Delete.
class ConversationsScreen extends StatefulWidget {
  const ConversationsScreen({super.key, required this.api, required this.onBack, required this.onOpen, required this.onNewChat, this.currentId});

  final SoraApi api;
  final VoidCallback onBack, onNewChat;
  final ValueChanged<String> onOpen;
  final String? currentId;

  @override
  State<ConversationsScreen> createState() => _ConversationsScreenState();
}

class _ConversationsScreenState extends State<ConversationsScreen> {
  List<Map<String, dynamic>>? _all;
  bool _failed = false;
  String _q = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final list = await widget.api.conversations();
      if (mounted) {
        setState(() {
          _all = [for (final c in list) Map<String, dynamic>.from(c as Map)];
          _failed = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  Future<void> _more(Map<String, dynamic> c) async {
    final s = S.of(context);
    final id = c['id'] as String, pinned = c['pinned'] == true;
    await showActionSheet(
      context,
      title: c['title'] as String? ?? '',
      items: [
        SheetItem(
          icon: Symbols.push_pin_rounded,
          label: pinned ? s.unpin : s.pinIt,
          onTap: () async {
            Navigator.pop(context);
            if (await guard(context, () => widget.api.patchConversation(id, pinned: !pinned))) _load();
          },
        ),
        SheetItem(
          icon: Symbols.edit_rounded,
          label: s.rename,
          onTap: () async {
            Navigator.pop(context);
            final r = await showTextSheet(context, title: s.rename, initial: c['title'] as String? ?? '', minLines: 1);
            if (r != null && mounted && await guard(context, () => widget.api.patchConversation(id, title: r.text))) _load();
          },
        ),
        SheetItem(
          icon: Symbols.archive_rounded,
          label: s.archive,
          onTap: () async {
            Navigator.pop(context);
            if (await guard(context, () => widget.api.patchConversation(id, archived: true))) {
              if (mounted) showToast(context, '${s.archive} ✓');
              _load();
            }
          },
        ),
        SheetItem(
          icon: Symbols.delete_rounded,
          label: s.del,
          danger: true,
          onTap: () async {
            Navigator.pop(context);
            if (await guard(context, () => widget.api.deleteConversation(id))) _load();
          },
        ),
      ],
    );
  }

  /// Sora's latest reply as plain text: no markdown markers or table pipes.
  static String _preview(Map<String, dynamic> c) =>
      stripMarkdown(c['preview'] as String? ?? '').replaceAll(RegExp(r'[|#*`]+|-{3,}'), ' ').replaceAll(RegExp(r'\s+'), ' ').trim();

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final all = _all;
    final q = _q.trim().toLowerCase();
    final shown = all?.where((c) => q.isEmpty || '${c['title']} ${c['preview']}'.toLowerCase().contains(q)).toList();
    final pins = shown?.where((c) => c['pinned'] == true).toList() ?? [];
    final rest = shown?.where((c) => c['pinned'] != true).toList() ?? [];

    Widget row(Map<String, dynamic> c) {
      final pinned = c['pinned'] == true;
      return Rise(
        child: ListRow(
          onTap: () => widget.onOpen(c['id'] as String),
          child: Row(
            children: [
              IconTile(icon: pinned ? Symbols.push_pin_rounded : Symbols.chat_bubble_rounded, fillIcon: pinned),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.baseline,
                      textBaseline: TextBaseline.alphabetic,
                      children: [
                        Expanded(
                          child: Text(
                            c['title'] as String? ?? s.newChat,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: SoraType.ui(15, weight: FontWeight.w500, color: p.ink),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(s.ago(DateTime.tryParse(c['updated_at'] as String? ?? '')?.toLocal()), style: SoraType.ui(12, color: p.dim)),
                      ],
                    ),
                    if (_preview(c).isNotEmpty)
                      Text(_preview(c), maxLines: 1, overflow: TextOverflow.ellipsis, style: SoraType.ui(13, color: p.dim)),
                  ],
                ),
              ),
              GestureDetector(
                onTap: () => _more(c),
                behavior: HitTestBehavior.opaque,
                child: SizedBox(width: 34, height: 34, child: Center(child: LIcon(Symbols.more_vert_rounded, size: 20, color: p.dim))),
              ),
            ],
          ),
        ),
      );
    }

    return ListScreen(
      title: s.conversations,
      onBack: widget.onBack,
      onRefresh: _load,
      action: HeaderAction(icon: Symbols.edit_square_rounded, label: s.newChat, onTap: widget.onNewChat),
      children: [
        if (_failed && all == null)
          EmptyState(icon: Symbols.cloud_off_rounded, text: s.loadFailed)
        else if (all == null)
          Padding(padding: const EdgeInsets.all(48), child: Center(child: Spinner(size: 22, color: p.acc)))
        else if (all.isEmpty)
          EmptyState(icon: Symbols.forum_rounded, text: s.emptyConv)
        else ...[
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
            child: SearchField(hint: s.searchConv, onChanged: (v) => setState(() => _q = v)),
          ),
          if (pins.isNotEmpty) ...[ListSection(s.pinned), for (final c in pins) row(c)],
          if (rest.isNotEmpty) ...[ListSection(s.recent), for (final c in rest) row(c)],
          if (q.isNotEmpty && pins.isEmpty && rest.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 30),
              child: Text(s.noMatch, textAlign: TextAlign.center, style: SoraType.ui(14, color: p.dim)),
            ),
        ],
      ],
    );
  }
}
