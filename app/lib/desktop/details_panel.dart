import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../chat/chat_activity.dart';
import '../chat/chat_models.dart';
import '../core/api.dart';
import '../core/live_events.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/sora_widgets.dart';
import '../widgets/overlays.dart';
import 'clipboard_section.dart';
import 'desktop_kit.dart';
import 'phone_notifications_section.dart';
import 'phone_section.dart';

/// The 300px Details panel beside Chat and Voice: actions waiting for a yes/no, Sora's latest tool
/// runs, the phone (status, screenshot, ring…), its notifications (when [live] is given: the owner
/// can switch them off in Settings) and the clipboard shared with it. [pc] is the online PC agent (a
/// row from `/api/devices`, or null): it puts screenshots on this PC's clipboard.
class DetailsPanel extends StatelessWidget {
  const DetailsPanel({
    super.key,
    required this.activity,
    required this.api,
    required this.pc,
    required this.phone,
    required this.onHide,
    this.live,
  });

  final ChatActivity activity;
  final SoraApi api;
  final Map<String, dynamic>? pc;

  /// The online phone (a row from `/api/devices`), or null.
  final Map<String, dynamic>? phone;
  final VoidCallback onHide;

  /// The live line the phone's notifications come over; null: that section is off.
  final LiveEvents? live;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    return SizedBox(
      width: 300,
      child: ListenableBuilder(
        listenable: activity,
        builder: (context, _) => ListView(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 16),
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    s.details,
                    style: SoraType.ui(14.5, weight: FontWeight.w600, color: p.ink),
                  ),
                ),
                PanelToggle(icon: Symbols.right_panel_close_rounded, tooltip: s.hidePanel, onTap: onHide),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(child: MonoLabel(s.waitingForYou)),
                MonoLabel(soraNum(context, activity.pending.length)),
              ],
            ),
            const SizedBox(height: 8),
            if (activity.pending.isEmpty)
              DashedBox(
                child: Text(s.nothingWaiting, style: SoraType.ui(13, color: p.dim)),
              )
            else
              ScrollBox(
                children: [
                  // newest first, like the sections below
                  for (final a in activity.pending.reversed)
                    Rise(
                      key: ValueKey(a.id),
                      offset: 8,
                      child: Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: _PendingCard(approval: a, onDecide: (yes) => activity.decide(a, yes)),
                      ),
                    ),
                ],
              ),
            const SizedBox(height: 18),
            MonoLabel(s.activity),
            const SizedBox(height: 6),
            if (activity.tools.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 7),
                child: Text(s.activityEmpty, style: SoraType.ui(13, color: p.dim, height: 1.45)),
              )
            else
              ScrollBox(children: [for (final t in activity.tools) _ActivityRow(tool: t)]),
            const SizedBox(height: 18),
            PhoneSection(api: api, phone: phone, pc: pc),
            const SizedBox(height: 18),
            if (live case final live?) ...[PhoneNotificationsSection(api: api, events: live.events), const SizedBox(height: 18)],
            ClipboardSection(api: api),
          ],
        ),
      ),
    );
  }
}

/// The 56px rail the panel collapses to: show, and the count of actions waiting.
class DetailsRail extends StatelessWidget {
  const DetailsRail({super.key, required this.activity, required this.onShow});

  final ChatActivity activity;
  final VoidCallback onShow;

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    return SizedBox(
      width: 56,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 14),
        child: ListenableBuilder(
          listenable: activity,
          builder: (context, _) => Column(
            children: [
              PanelToggle(icon: Symbols.right_panel_open_rounded, tooltip: s.showPanel, onTap: onShow),
              if (activity.pending.isNotEmpty) ...[const SizedBox(height: 8), PillBadge(count: activity.pending.length)],
            ],
          ),
        ),
      ),
    );
  }
}

class _PendingCard extends StatelessWidget {
  const _PendingCard({required this.approval, required this.onDecide});

  final Approval approval;
  final ValueChanged<bool> onDecide;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final view = ApprovalView.of(approval, s);
    final sub = view.fields.isNotEmpty ? view.fields.first.$2 : view.service;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: soraCard(p),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: p.accSoft,
                  borderRadius: BorderRadius.circular(9),
                  border: Border.all(color: p.accLine),
                ),
                alignment: Alignment.center,
                child: LIcon(view.icon, size: 16, color: p.acc, fill: true),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      view.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: SoraType.ui(13.5, weight: FontWeight.w600, color: p.ink, height: 1.3),
                    ),
                    Text(
                      sub,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: SoraType.ui(12, color: p.dim, height: 1.3),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                flex: 10,
                child: Hover(
                  onTap: () => onDecide(false),
                  builder: (_, hover) => Container(
                    height: 34,
                    decoration: BoxDecoration(
                      color: hover ? p.surf2 : p.glass2,
                      borderRadius: BorderRadius.circular(11),
                      border: Border.all(color: p.line),
                    ),
                    alignment: Alignment.center,
                    child: Text(
                      s.no,
                      style: SoraType.ui(13, weight: FontWeight.w500, color: p.ink),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                flex: 14,
                child: Hover(
                  onTap: () => onDecide(true),
                  builder: (_, hover) => AnimatedOpacity(
                    duration: const Duration(milliseconds: 150),
                    opacity: hover ? .88 : 1,
                    child: Container(
                      height: 34,
                      decoration: BoxDecoration(color: p.ink, borderRadius: BorderRadius.circular(11)),
                      alignment: Alignment.center,
                      child: Text(
                        s.yes,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: SoraType.ui(13, weight: FontWeight.w600, color: p.bg),
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ActivityRow extends StatelessWidget {
  const _ActivityRow({required this.tool});

  final ToolChipData tool;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 7),
      child: Row(
        children: [
          Container(
            width: 26,
            height: 26,
            decoration: BoxDecoration(
              color: p.surf,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: p.line),
            ),
            alignment: Alignment.center,
            child: LIcon(tool.icon, size: 15, color: p.acc),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              tool.label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: SoraType.ui(13, color: p.ink),
            ),
          ),
          switch (tool.state) {
            ToolState.run => Spinner(size: 15, color: p.acc),
            ToolState.ok => LIcon(Symbols.check_circle_rounded, size: 15, color: p.ok, fill: true),
            ToolState.fail => LIcon(Symbols.error_rounded, size: 15, color: p.err, fill: true),
          },
        ],
      ),
    );
  }
}
