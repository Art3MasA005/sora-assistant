import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../core/api.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/list_kit.dart';
import '../widgets/overlays.dart';
import '../widgets/sora_widgets.dart';

/// Routines: what Sora does on its own, each with its trigger, an on/off switch, the next run and how
/// the last one went. They are made and changed in the chat (where the owner approves them); here
/// they can be switched off, run now, made silent or deleted.
class RoutinesScreen extends StatefulWidget {
  const RoutinesScreen({super.key, required this.api, required this.onBack});

  final SoraApi api;
  final VoidCallback onBack;

  @override
  State<RoutinesScreen> createState() => _RoutinesScreenState();
}

class _RoutinesScreenState extends State<RoutinesScreen> {
  List<Map<String, dynamic>>? _items;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final list = [for (final r in await widget.api.routines()) Map<String, dynamic>.from(r as Map)];
      if (mounted) {
        setState(() {
          _items = list;
          _failed = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  Future<void> _delete(Map<String, dynamic> r) async {
    final s = S.of(context);
    final ok = await showConfirmSheet(context, title: s.deleteRoutine, text: s.deleteRoutineQ, confirm: s.del, danger: true);
    if (!ok || !mounted) return;
    if (await guard(context, () => widget.api.deleteRoutine(r['id'] as String))) {
      setState(() => _items?.remove(r));
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final items = _items;
    return ListScreen(
      title: s.routines,
      onBack: widget.onBack,
      onRefresh: _load,
      children: [
        if (_failed && items == null)
          EmptyState(icon: Symbols.cloud_off_rounded, text: s.loadFailed)
        else if (items == null)
          Padding(padding: const EdgeInsets.all(48), child: Center(child: Spinner(size: 22, color: p.acc)))
        else if (items.isEmpty)
          EmptyState(icon: Symbols.event_repeat_rounded, text: s.emptyRoutines)
        else ...[
          Padding(
            padding: const EdgeInsets.fromLTRB(18, 2, 18, 8),
            child: Text(s.routinesHint, style: SoraType.ui(12.5, color: p.dim)),
          ),
          for (final r in items) _RoutineRow(key: ValueKey(r['id']), api: widget.api, routine: r, onDelete: () => _delete(r)),
        ],
      ],
    );
  }
}

/// One routine. It keeps its own state, so its switch rebuilds this row only.
class _RoutineRow extends StatefulWidget {
  const _RoutineRow({super.key, required this.api, required this.routine, required this.onDelete});

  final SoraApi api;
  final Map<String, dynamic> routine;
  final VoidCallback onDelete;

  @override
  State<_RoutineRow> createState() => _RoutineRowState();
}

class _RoutineRowState extends State<_RoutineRow> {
  Map<String, dynamic> get r => widget.routine;

  Future<void> _patch({bool? enabled, bool? speak}) async {
    final before = Map<String, dynamic>.from(r);
    setState(() {
      if (enabled != null) r['enabled'] = enabled;
      if (speak != null) r['speak'] = speak;
    });
    try {
      final fresh = await widget.api.patchRoutine(r['id'] as String, enabled: enabled, speak: speak);
      if (mounted) setState(() => r.addAll(fresh)); // the server's next run time
    } catch (_) {
      if (!mounted) return;
      setState(() => r.addAll(before));
      showToast(context, S.of(context).couldntChange);
    }
  }

  Future<void> _run() async {
    if (await guard(context, () => widget.api.runRoutine(r['id'] as String)) && mounted) {
      // A page watch only looks at its page: the routine runs if it changed.
      final s = S.of(context);
      showToast(context, (r['trigger'] as Map?)?['type'] == 'page_change' ? s.checkStarted : s.runStarted);
    }
  }

  Future<void> _more() {
    final s = S.of(context);
    final speak = r['speak'] != false;
    return showActionSheet(
      context,
      title: r['name'] as String? ?? '',
      items: [
        SheetItem(
          icon: Symbols.play_arrow_rounded,
          label: s.runNow,
          onTap: () {
            Navigator.pop(context);
            _run();
          },
        ),
        SheetItem(
          icon: speak ? Symbols.volume_off_rounded : Symbols.volume_up_rounded,
          label: speak ? s.notifOnly : s.sayAloud,
          onTap: () {
            Navigator.pop(context);
            _patch(speak: !speak);
          },
        ),
        SheetItem(
          icon: Symbols.delete_rounded,
          label: s.del,
          danger: true,
          onTap: () {
            Navigator.pop(context);
            widget.onDelete();
          },
        ),
      ],
    );
  }

  static IconData _icon(Object? type) => switch (type) {
    'time' => Symbols.schedule_rounded,
    'interval' => Symbols.repeat_rounded,
    'email' => Symbols.mark_email_unread_rounded,
    'battery_below' => Symbols.battery_alert_rounded,
    'device_online' => Symbols.wifi_rounded,
    'device_offline' => Symbols.wifi_off_rounded,
    'pc_woke' => Symbols.light_mode_rounded,
    'phone_notification' => Symbols.notifications_active_rounded,
    'page_change' => Symbols.travel_explore_rounded,
    _ => Symbols.event_repeat_rounded,
  };

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final on = r['enabled'] != false;
    final trigger = Map<String, dynamic>.from(r['trigger'] as Map? ?? const {});
    final next = DateTime.tryParse(r['next_run_at'] as String? ?? '')?.toLocal();
    final last = DateTime.tryParse(r['last_run_at'] as String? ?? '')?.toLocal();
    final result = (r['last_result'] as String? ?? '').trim();
    final allowed = [for (final a in r['allowed_actions'] as List? ?? const []) '$a'];
    final status = switch (r['last_status']) {
      'ok' => (s.routineOk, p.ok, p.ok.withValues(alpha: .12)),
      'error' => (s.routineFailed, p.err, p.errSoft),
      'waiting' => (s.routineWaiting, p.amber, p.amberSoft),
      'missed' => (s.routineMissed, p.dim, p.surf2),
      'unchanged' => (s.routineUnchanged, p.dim, p.surf2),
      _ => null,
    };
    return Rise(
      child: ListRow(
        onTap: _more,
        padding: const EdgeInsets.fromLTRB(14, 12, 10, 12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            IconTile(icon: _icon(trigger['type']), size: 36, iconSize: 18, color: on ? p.acc : p.dim),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    r['name'] as String? ?? '',
                    style: SoraType.ui(15, weight: FontWeight.w500, color: on ? p.ink : p.dim),
                  ),
                  const SizedBox(height: 2),
                  Text(s.routineWhen(trigger), style: SoraType.ui(12.5, weight: FontWeight.w500, color: on ? p.acc : p.dim)),
                  const SizedBox(height: 4),
                  Text(
                    r['prompt'] as String? ?? '',
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: SoraType.ui(13, color: p.dim, height: 1.4),
                  ),
                  if (allowed.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(s.runsWithoutAsking(allowed.join(', ')), style: SoraType.ui(12, color: p.amber)),
                  ],
                  if ((on && next != null) || status != null) const SizedBox(height: 6),
                  Wrap(
                    spacing: 8,
                    runSpacing: 4,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      if (!on)
                        Tag(s.routineOff, color: p.dim, bg: p.surf2)
                      else if (next != null)
                        Text(s.routineNext(s.when(next)), style: SoraType.ui(12, color: p.dim)),
                      if (status != null) ...[
                        Tag(status.$1, color: status.$2, bg: status.$3),
                        if (last != null) Text(s.routineLast(s.when(last)), style: SoraType.ui(12, color: p.dim)),
                      ],
                    ],
                  ),
                  if (result.isNotEmpty && result != '(nothing)') ...[
                    const SizedBox(height: 4),
                    Text(result, maxLines: 2, overflow: TextOverflow.ellipsis, style: SoraType.ui(12.5, color: p.ink, height: 1.4)),
                  ],
                ],
              ),
            ),
            const SizedBox(width: 8),
            Column(
              children: [
                SoraSwitch(value: on, onChanged: (v) => _patch(enabled: v)),
                const SizedBox(height: 6),
                GestureDetector(
                  onTap: _more,
                  behavior: HitTestBehavior.opaque,
                  child: SizedBox(width: 30, height: 30, child: Center(child: LIcon(Symbols.more_vert_rounded, size: 20, color: p.dim))),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
