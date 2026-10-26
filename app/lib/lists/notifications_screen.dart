import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../core/api.dart';
import '../desktop/desktop_kit.dart';
import '../shell/layout.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/list_kit.dart';
import '../widgets/sora_widgets.dart';
import '../widgets/overlays.dart';

/// Notifications (unread count, important tag, read state) and the email rules card below them.
/// One goes with a swipe (phone) or the bin that shows on hover (PC); "Delete all" clears the list.
class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key, required this.api, required this.onBack, this.onUnreadChanged, this.onOpenChat});

  final SoraApi api;
  final VoidCallback onBack;
  final VoidCallback? onUnreadChanged;

  /// Opens a conversation: a routine that waits for an approval has its card there.
  final ValueChanged<String>? onOpenChat;

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  List<Map<String, dynamic>>? _items;
  List<Map<String, dynamic>> _rules = [];
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final results = await Future.wait([widget.api.notifications(), widget.api.emailRules()]);
      if (!mounted) return;
      setState(() {
        _items = [for (final n in results[0]) Map<String, dynamic>.from(n as Map)];
        _rules = [for (final r in results[1]) Map<String, dynamic>.from(r as Map)];
        _failed = false;
      });
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  Future<void> _open(Map<String, dynamic> n) async {
    final data = n['data'] as Map? ?? const {};
    final waiting = n['kind'] == 'routine' && data['action_ids'] is List && data['conversation_id'] is String;
    if (n['read'] != true) {
      setState(() => n['read'] = true);
      await guard(context, () => widget.api.markRead(n['id'] as String));
      widget.onUnreadChanged?.call();
    }
    if (waiting && mounted) widget.onOpenChat?.call(data['conversation_id'] as String);
  }

  Future<void> _markAll() async {
    if (await guard(context, widget.api.markAllRead)) {
      setState(() {
        for (final n in _items ?? <Map<String, dynamic>>[]) {
          n['read'] = true;
        }
      });
      widget.onUnreadChanged?.call();
    }
  }

  Future<void> _delete(Map<String, dynamic> n) async {
    final items = _items;
    if (items == null) return;
    final at = items.indexOf(n);
    setState(() => items.remove(n));
    try {
      await widget.api.deleteNotification(n['id'] as String);
    } catch (_) {
      if (!mounted) return;
      setState(() => items.insert(at.clamp(0, items.length), n));
      showToast(context, S.of(context).couldntChange);
      return;
    }
    if (n['read'] != true) widget.onUnreadChanged?.call();
  }

  Future<void> _deleteAll() async {
    final s = S.of(context);
    final ok = await showConfirmSheet(context, title: s.deleteAllNotif, text: s.deleteAllNotifQ, confirm: s.del, danger: true);
    if (!ok || !mounted) return;
    if (await guard(context, widget.api.deleteAllNotifications)) {
      setState(() => _items = []);
      widget.onUnreadChanged?.call();
    }
  }

  Future<void> _addRule() async {
    final s = S.of(context);
    final r = await showTextSheet(context, title: s.ruleTitle, hint: s.rulePh, minLines: 2);
    if (r != null && mounted && await guard(context, () => widget.api.addEmailRule(r.text))) _load();
  }

  static IconData _icon(String? kind) => switch (kind) {
    'email' => Symbols.mail_rounded,
    'reminder' => Symbols.alarm_rounded,
    'routine' => Symbols.event_repeat_rounded,
    'device' => Symbols.computer_rounded,
    'system' => Symbols.link_rounded,
    _ => Symbols.notifications_rounded,
  };

  String _time(String? iso, S s) {
    final t = DateTime.tryParse(iso ?? '')?.toLocal();
    if (t == null) return '';
    final now = DateTime.now();
    if (t.year == now.year && t.month == now.month && t.day == now.day) return DateFormat('h:mm', s.code).format(t);
    return s.ago(t);
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final items = _items;
    final unread = items?.where((n) => n['read'] != true).length ?? 0;

    final desk = SoraLayout.isDesktop(context);

    Widget row(Map<String, dynamic> n) {
      final high = n['importance'] == 'high', read = n['read'] == true;
      final body = (n['body'] as String? ?? '').trim();
      final card = ListRow(
          onTap: () => _open(n),
          padding: const EdgeInsets.all(12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              high
                  ? IconTile(icon: _icon(n['kind'] as String?), bg: p.errSoft, color: p.err, iconSize: 20)
                  : IconTile(icon: _icon(n['kind'] as String?), color: p.dim, iconSize: 20),
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
                            n['title'] as String? ?? '',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: SoraType.ui(15, weight: read ? FontWeight.w500 : FontWeight.w600, color: read ? p.dim : p.ink),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(_time(n['created_at'] as String?, s), style: SoraType.ui(12, color: p.dim)),
                      ],
                    ),
                    if (body.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(body, style: SoraType.ui(13.5, color: p.dim, height: 1.45)),
                    ],
                    if (high) ...[const SizedBox(height: 6), Tag(s.important, color: p.err, bg: p.errSoft, size: 11)],
                  ],
                ),
              ),
              if (!read) ...[
                const SizedBox(width: 8),
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Container(width: 8, height: 8, decoration: BoxDecoration(color: p.acc, shape: BoxShape.circle)),
                ),
              ],
            ],
          ),
        );
      return Rise(
        key: ValueKey(n['id']),
        child: desk
            ? _HoverDelete(tooltip: s.del, onDelete: () => _delete(n), child: card)
            : Dismissible(
                key: ValueKey('swipe-${n['id']}'),
                direction: DismissDirection.endToStart,
                onDismissed: (_) => _delete(n),
                background: Container(
                  margin: const EdgeInsets.symmetric(horizontal: 8),
                  padding: const EdgeInsets.only(right: 22),
                  alignment: Alignment.centerRight,
                  decoration: BoxDecoration(color: p.errSoft, borderRadius: BorderRadius.circular(16)),
                  child: LIcon(Symbols.delete_rounded, size: 22, color: p.err),
                ),
                child: card,
              ),
      );
    }

    return ListScreen(
      title: s.notifications,
      onBack: widget.onBack,
      onRefresh: _load,
      action: unread > 0 ? HeaderAction(icon: Symbols.done_all_rounded, label: s.markAll, onTap: _markAll) : null,
      children: [
        if (_failed && items == null)
          EmptyState(icon: Symbols.cloud_off_rounded, text: s.loadFailed)
        else if (items == null)
          Padding(padding: const EdgeInsets.all(48), child: Center(child: Spinner(size: 22, color: p.acc)))
        else ...[
          if (items.isEmpty)
            EmptyState(icon: Symbols.notifications_rounded, text: s.emptyNotif)
          else ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 12, 6),
              child: Row(
                children: [
                  Expanded(child: Text(s.unread(unread), style: SoraType.ui(13, color: p.dim))),
                  Pressable(
                    onTap: _deleteAll,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          LIcon(Symbols.delete_sweep_rounded, size: 17, color: p.dim),
                          const SizedBox(width: 5),
                          Text(s.deleteAllNotif, style: SoraType.ui(13, weight: FontWeight.w500, color: p.dim)),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
            for (final n in items) row(n),
          ],
          Padding(padding: const EdgeInsets.fromLTRB(16, 18, 16, 0), child: _rulesCard(p, s)),
        ],
      ],
    );
  }

  Widget _rulesCard(SoraPalette p, S s) => Glass(
    radius: 18,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 14, 14, 4),
          child: Row(
            children: [
              LIcon(Symbols.rule_rounded, size: 18, color: p.acc),
              const SizedBox(width: 8),
              Text(s.rules, style: SoraType.ui(15, weight: FontWeight.w600, color: p.ink)),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 0, 14, 8),
          child: Text(s.rulesHint, style: SoraType.ui(12.5, color: p.dim)),
        ),
        for (final r in _rules)
          Container(
            padding: const EdgeInsets.fromLTRB(14, 10, 10, 10),
            decoration: BoxDecoration(border: Border(top: BorderSide(color: p.line))),
            child: Row(
              children: [
                Expanded(child: Text(r['rule'] as String? ?? '', style: SoraType.ui(14, color: p.ink, height: 1.45))),
                GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: () async {
                    if (await guard(context, () => widget.api.deleteEmailRule(r['id'] as String))) _load();
                  },
                  child: SizedBox(width: 32, height: 32, child: Center(child: LIcon(Symbols.delete_rounded, size: 19, color: p.dim))),
                ),
                const SizedBox(width: 10),
                SoraSwitch(
                  value: r['active'] == true,
                  onChanged: (v) async {
                    setState(() => r['active'] = v);
                    if (!await guard(context, () => widget.api.switchEmailRule(r['id'] as String, v))) {
                      setState(() => r['active'] = !v);
                    }
                  },
                ),
              ],
            ),
          ),
        GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: _addRule,
          child: Container(
            height: 46,
            decoration: BoxDecoration(border: Border(top: BorderSide(color: p.line))),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                LIcon(Symbols.add_rounded, size: 19, color: p.acc),
                const SizedBox(width: 6),
                Text(s.addRule, style: SoraType.ui(14, weight: FontWeight.w500, color: p.acc)),
              ],
            ),
          ),
        ),
      ],
    ),
  );
}

/// A notification on the PC: a bin at its right while the mouse is over it.
class _HoverDelete extends StatefulWidget {
  const _HoverDelete({required this.child, required this.onDelete, required this.tooltip});

  final Widget child;
  final VoidCallback onDelete;
  final String tooltip;

  @override
  State<_HoverDelete> createState() => _HoverDeleteState();
}

class _HoverDeleteState extends State<_HoverDelete> {
  bool _hover = false;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return MouseRegion(
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      child: Stack(
        children: [
          widget.child,
          Positioned(
            right: 16,
            bottom: 8,
            child: IgnorePointer(
              ignoring: !_hover,
              child: AnimatedOpacity(
                opacity: _hover ? 1 : 0,
                duration: const Duration(milliseconds: 120),
                child: Hover(
                  tooltip: widget.tooltip,
                  onTap: widget.onDelete,
                  builder: (_, over) => AnimatedContainer(
                    duration: const Duration(milliseconds: 120),
                    width: 32,
                    height: 32,
                    decoration: BoxDecoration(color: over ? p.errSoft : p.surf2, borderRadius: BorderRadius.circular(10)),
                    child: Center(child: LIcon(Symbols.delete_rounded, size: 18, color: over ? p.err : p.dim)),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
