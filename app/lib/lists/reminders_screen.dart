import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../core/api.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/list_kit.dart';
import '../widgets/sora_widgets.dart';
import '../widgets/overlays.dart';

/// Reminders: scheduled first, then done / cancelled; tap the circle to mark done; more menu for
/// Mark done / Cancel / Delete; "New reminder" sheet with quick times and repeat.
class RemindersScreen extends StatefulWidget {
  const RemindersScreen({super.key, required this.api, required this.onBack});

  final SoraApi api;
  final VoidCallback onBack;

  @override
  State<RemindersScreen> createState() => _RemindersScreenState();
}

class _RemindersScreenState extends State<RemindersScreen> {
  List<Map<String, dynamic>>? _items;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final list = [for (final r in await widget.api.reminders()) Map<String, dynamic>.from(r as Map)];
      int rank(Map r) => r['status'] == 'scheduled' ? 0 : 1;
      list.sort((a, b) {
        final byStatus = rank(a) - rank(b);
        if (byStatus != 0) return byStatus;
        final c = (a['due_at'] as String).compareTo(b['due_at'] as String);
        return rank(a) == 0 ? c : -c; // upcoming soonest first, finished most recent first
      });
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

  Future<void> _setStatus(Map<String, dynamic> r, String status) async {
    final old = r['status'];
    setState(() => r['status'] = status);
    if (!await guard(context, () => widget.api.patchReminder(r['id'] as String, status: status))) {
      setState(() => r['status'] = old);
    }
  }

  Future<void> _more(Map<String, dynamic> r) => showActionSheet(
    context,
    title: r['text'] as String? ?? '',
    items: [
      SheetItem(
        icon: Symbols.check_circle_rounded,
        label: S.of(context).markDone,
        onTap: () {
          Navigator.pop(context);
          _setStatus(r, 'done');
        },
      ),
      SheetItem(
        icon: Symbols.block_rounded,
        label: S.of(context).cancelRem,
        onTap: () {
          Navigator.pop(context);
          _setStatus(r, 'cancelled');
        },
      ),
      SheetItem(
        icon: Symbols.delete_rounded,
        label: S.of(context).del,
        danger: true,
        onTap: () async {
          Navigator.pop(context);
          if (await guard(context, () => widget.api.deleteReminder(r['id'] as String))) _load();
        },
      ),
    ],
  );

  Future<void> _add() async {
    final s = S.of(context);
    final now = DateTime.now();
    DateTime at(DateTime d, int h, int m) => DateTime(d.year, d.month, d.day, h, m);
    final tonight = now.isBefore(at(now, 20, 30)) ? at(now, 21, 0) : at(now.add(const Duration(days: 1)), 21, 0);
    final morning = at(now.add(const Duration(days: 1)), 8, 0);
    final soon = DateTime(now.year, now.month, now.day, now.hour + 1, (now.minute ~/ 15) * 15);
    final r = await showTextSheet(
      context,
      title: s.newRem,
      hint: s.remPh,
      minLines: 2,
      a: SheetChoice<Object?>([(soon, s.when(soon)), (tonight, s.when(tonight)), (morning, s.when(morning)), ('pick', s.pickTime)], tonight),
      b: SheetChoice<Object?>([('none', s.noneRepeat), ('daily', s.daily), ('weekly', s.weekly)], 'none'),
    );
    if (r == null || !mounted) return;
    var due = r.a is DateTime ? r.a as DateTime : null;
    if (due == null) {
      final day = await showDatePicker(context: context, firstDate: now, lastDate: now.add(const Duration(days: 365 * 2)), initialDate: now);
      if (day == null || !mounted) return;
      final time = await showTimePicker(context: context, initialTime: TimeOfDay.fromDateTime(tonight));
      if (time == null || !mounted) return;
      due = at(day, time.hour, time.minute);
    }
    if (await guard(context, () => widget.api.addReminder(r.text, due!, r.b as String? ?? 'none'))) _load();
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final items = _items;

    Widget row(Map<String, dynamic> r) {
      final status = r['status'] as String? ?? 'scheduled';
      final done = status == 'done', cancelled = status == 'cancelled';
      final due = DateTime.tryParse(r['due_at'] as String? ?? '')?.toLocal();
      final repeat = r['repeat'] as String? ?? 'none';
      final (label, fg, bg) = done
          ? (s.doneS, p.ok, p.ok.withValues(alpha: .12))
          : cancelled
          ? (s.cancelledS, p.dim, p.surf2)
          : (s.scheduled, p.acc, p.accSoft);
      return Rise(
        child: ListRow(
          padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              GestureDetector(
                onTap: cancelled ? null : () => _setStatus(r, done ? 'scheduled' : 'done'),
                child: Container(
                  width: 24,
                  height: 24,
                  margin: const EdgeInsets.only(top: 1),
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: done ? p.ok : p.ok.withAlpha(0),
                    border: done ? null : Border.all(color: p.faint, width: 1.5),
                  ),
                  child: done ? const Center(child: LIcon(Symbols.check_rounded, size: 16, color: Colors.white, weight: 600)) : null,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      r['text'] as String? ?? '',
                      style: SoraType.ui(15, weight: FontWeight.w500, color: done || cancelled ? p.dim : p.ink).copyWith(
                        decoration: done || cancelled ? TextDecoration.lineThrough : null,
                        decorationColor: p.dim,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Wrap(
                      spacing: 8,
                      runSpacing: 2,
                      children: [
                        Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            LIcon(Symbols.schedule_rounded, size: 15, color: p.dim),
                            const SizedBox(width: 4),
                            Text(due == null ? '' : s.when(due), style: SoraType.ui(12.5, color: p.dim)),
                          ],
                        ),
                        if (repeat != 'none')
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              LIcon(Symbols.repeat_rounded, size: 15, color: p.dim),
                              const SizedBox(width: 3),
                              Text(repeat == 'daily' ? s.daily : s.weekly, style: SoraType.ui(12.5, color: p.dim)),
                            ],
                          ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Tag(label, color: fg, bg: bg),
              Transform.translate(
                offset: const Offset(0, -4),
                child: GestureDetector(
                  onTap: () => _more(r),
                  behavior: HitTestBehavior.opaque,
                  child: SizedBox(width: 30, height: 30, child: Center(child: LIcon(Symbols.more_vert_rounded, size: 20, color: p.dim))),
                ),
              ),
            ],
          ),
        ),
      );
    }

    return ListScreen(
      title: s.reminders,
      onBack: widget.onBack,
      onRefresh: _load,
      action: HeaderAction(icon: Symbols.add_rounded, label: s.newRem, onTap: _add),
      children: [
        if (_failed && items == null)
          EmptyState(icon: Symbols.cloud_off_rounded, text: s.loadFailed)
        else if (items == null)
          Padding(padding: const EdgeInsets.all(48), child: Center(child: Spinner(size: 22, color: p.acc)))
        else if (items.isEmpty)
          EmptyState(icon: Symbols.alarm_rounded, text: s.emptyRem)
        else
          for (final r in items) row(r),
      ],
    );
  }
}
