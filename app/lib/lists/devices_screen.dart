import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../core/api.dart';
import '../core/session.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/list_kit.dart';
import '../widgets/sora_widgets.dart';
import '../widgets/overlays.dart';
import 'pc_actions.dart';

/// Devices signed in to Sora. An online PC agent gets quick actions (Lock, Screenshot, Volume,
/// Sleep — which asks first); each device can be renamed or signed out.
class DevicesScreen extends StatefulWidget {
  const DevicesScreen({super.key, required this.api, required this.session, required this.onBack, this.events});

  final SoraApi api;
  final Session session;
  final VoidCallback onBack;

  /// What the server pushes (the Windows app's LiveEvents, the phone's LiveLink): a device coming or
  /// going reloads the list.
  final Stream<Map<String, dynamic>>? events;

  @override
  State<DevicesScreen> createState() => _DevicesScreenState();
}

class _DevicesScreenState extends State<DevicesScreen> {
  List<Map<String, dynamic>>? _items;
  bool _failed = false;
  StreamSubscription<Map<String, dynamic>>? _events;

  @override
  void initState() {
    super.initState();
    _load();
    _events = widget.events?.listen((e) {
      if (e['type'] == 'device_status') _load();
    });
  }

  @override
  void dispose() {
    _events?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final list = [for (final d in await widget.api.devices()) Map<String, dynamic>.from(d as Map)];
      list.sort((a, b) => (b['is_me'] == true ? 1 : 0) - (a['is_me'] == true ? 1 : 0));
      if (mounted && (_failed || jsonEncode(list) != jsonEncode(_items))) {
        setState(() {
          _items = list;
          _failed = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  Future<void> _more(Map<String, dynamic> d) {
    final s = S.of(context);
    final me = d['is_me'] == true;
    return showActionSheet(
      context,
      title: d['name'] as String? ?? '',
      items: [
        SheetItem(
          icon: Symbols.edit_rounded,
          label: s.rename,
          onTap: () async {
            Navigator.pop(context);
            final r = await showTextSheet(context, title: s.rename, initial: d['name'] as String? ?? '', minLines: 1);
            if (r != null && mounted && await guard(context, () => widget.api.renameDevice(d['id'] as String, r.text))) {
              if (me) await widget.session.signIn(widget.session.serverUrl!, widget.session.token!, device: r.text);
              _load();
            }
          },
        ),
        SheetItem(
          icon: Symbols.logout_rounded,
          label: s.signOutDev,
          danger: true,
          onTap: () async {
            Navigator.pop(context);
            final ok = await showConfirmSheet(
              context,
              title: '${s.signOutDev} · ${d['name']}',
              text: s.revokeQ,
              confirm: s.signOutDev,
              danger: true,
            );
            if (!ok || !mounted) return;
            if (await guard(context, () => widget.api.revokeDevice(d['id'] as String))) {
              if (me) {
                await widget.session.signOut();
              } else {
                _load();
              }
            }
          },
        ),
      ],
    );
  }

  static IconData _icon(String? kind) => switch (kind) {
    'android' => Symbols.smartphone_rounded,
    'windows' => Symbols.desktop_windows_rounded,
    _ => Symbols.terminal_rounded,
  };

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final items = _items;

    Widget card(Map<String, dynamic> d) {
      final online = d['online'] == true, me = d['is_me'] == true, pc = d['kind'] == 'pc_agent';
      final seen = DateTime.tryParse(d['last_seen_at'] as String? ?? '')?.toLocal();
      final kind = me ? '${s.deviceKind(d['kind'] as String? ?? '')} · ${s.thisDevice}' : s.deviceKind(d['kind'] as String? ?? '');
      final status = me ? s.activeNow : (online ? s.onlineS : (seen == null ? s.offline : s.lastSeen(s.ago(seen))));
      Widget quick(IconData icon, String label, VoidCallback onTap) => Expanded(
        child: Pressable(
          onTap: onTap,
          child: Glass(
            height: 60,
            radius: 12,
            fill: p.glass2,
            blur: false,
            padding: const EdgeInsets.symmetric(horizontal: 2),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                LIcon(icon, size: 20, color: p.ink),
                const SizedBox(height: 3),
                Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: SoraType.ui(11.5, color: p.ink),
                ),
              ],
            ),
          ),
        ),
      );
      return Rise(
        child: Glass(
          radius: 18,
          padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  IconTile(icon: _icon(d['kind'] as String?), fill: p.glass2, iconSize: 20),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          d['name'] as String? ?? '',
                          style: SoraType.ui(15, weight: FontWeight.w600, color: p.ink),
                        ),
                        Row(
                          children: [
                            Container(
                              width: 7,
                              height: 7,
                              decoration: BoxDecoration(color: online || me ? p.ok : p.faint, shape: BoxShape.circle),
                            ),
                            const SizedBox(width: 6),
                            Expanded(
                              child: Text(
                                '$kind · $status',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: SoraType.ui(12.5, color: p.dim),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  GestureDetector(
                    onTap: () => _more(d),
                    behavior: HitTestBehavior.opaque,
                    child: SizedBox(
                      width: 34,
                      height: 34,
                      child: Center(child: LIcon(Symbols.more_vert_rounded, size: 20, color: p.dim)),
                    ),
                  ),
                ],
              ),
              if (pc && online) ...[
                const SizedBox(height: 12),
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: Row(
                    children: [
                      quick(Symbols.lock_rounded, s.lock, () => pcLock(context, widget.api, d)),
                      const SizedBox(width: 6),
                      quick(Symbols.screenshot_monitor_rounded, s.screenshot, () => pcScreenshot(context, widget.api, d)),
                      const SizedBox(width: 6),
                      quick(Symbols.volume_up_rounded, s.volume, () => pcVolume(context, widget.api, d)),
                      const SizedBox(width: 6),
                      quick(Symbols.bedtime_rounded, s.sleep, () => pcSleep(context, widget.api, d)),
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
      );
    }

    return ListScreen(
      title: s.devices,
      onBack: widget.onBack,
      onRefresh: _load,
      children: [
        if (_failed && items == null)
          EmptyState(icon: Symbols.cloud_off_rounded, text: s.loadFailed)
        else if (items == null)
          Padding(
            padding: const EdgeInsets.all(48),
            child: Center(child: Spinner(size: 22, color: p.acc)),
          )
        else
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Column(
              children: [
                for (final (i, d) in items.indexed) ...[if (i > 0) const SizedBox(height: 10), card(d)],
              ],
            ),
          ),
      ],
    );
  }
}
