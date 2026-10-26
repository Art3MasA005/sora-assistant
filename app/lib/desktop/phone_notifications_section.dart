import 'dart:async';

import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../core/api.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/overlays.dart';
import '../widgets/sora_widgets.dart';
import 'desktop_kit.dart';

/// Details panel → Phone notifications: what came on the phone lately (WhatsApp, Messenger, SMS…),
/// newest first. Loaded once, then each new one arrives in [events] (the live line: no polling).
class PhoneNotificationsSection extends StatefulWidget {
  const PhoneNotificationsSection({super.key, required this.api, required this.events});

  final SoraApi api;
  final Stream<Map<String, dynamic>> events;

  @override
  State<PhoneNotificationsSection> createState() => _PhoneNotificationsSectionState();
}

class _PhoneNotificationsSectionState extends State<PhoneNotificationsSection> {
  static const _shown = 30; // three show; the rest are a scroll away
  StreamSubscription<Map<String, dynamic>>? _sub;
  List<Map<String, dynamic>> _items = [];

  @override
  void initState() {
    super.initState();
    _load();
    _sub = widget.events.where((e) => e['type'] == 'phone_notification').listen((e) {
      final n = Map<String, dynamic>.from(e['notification'] as Map);
      if (mounted) setState(() => _items = [n, ..._items.take(_shown - 1)]);
    });
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final r = await widget.api.phoneNotifications();
      final items = [for (final i in (r['items'] as List).take(_shown)) Map<String, dynamic>.from(i as Map)];
      if (mounted) setState(() => _items = items);
    } catch (_) {}
  }

  Future<void> _clear() async {
    final before = _items;
    setState(() => _items = []);
    try {
      await widget.api.clearPhoneNotifications();
    } catch (_) {
      if (mounted) setState(() => _items = before);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(child: MonoLabel(s.phoneNotifs)),
            if (_items.isNotEmpty)
              Hover(
                onTap: _clear,
                builder: (_, hover) => Text(
                  s.clear,
                  style: SoraType.ui(12, weight: FontWeight.w500, color: hover ? p.err : p.dim),
                ),
              ),
          ],
        ),
        const SizedBox(height: 8),
        if (_items.isEmpty)
          DashedBox(
            child: Text(s.phoneNotifsEmpty, style: SoraType.ui(13, color: p.dim, height: 1.45)),
          )
        else
          ScrollBox(
            children: [
              // keyed: a new one fades in at the top, the others keep their place
              for (final n in _items)
                Rise(
                  key: ValueKey(n['id']),
                  offset: 6,
                  child: Padding(padding: const EdgeInsets.only(bottom: 8), child: _item(n, p, s)),
                ),
            ],
          ),
      ],
    );
  }

  Widget _item(Map<String, dynamic> n, SoraPalette p, S s) {
    final at = DateTime.tryParse(n['at'] as String? ?? '')?.toLocal();
    final title = n['title'] as String? ?? '';
    final text = n['text'] as String? ?? '';
    return Glass(
      radius: 14,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (title.isNotEmpty)
            Text(
              title,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: SoraType.ui(13.5, weight: FontWeight.w600, color: p.ink),
            ),
          if (text.isNotEmpty)
            Text(
              text,
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: SoraType.ui(13, color: p.ink, height: 1.4),
            ),
          const SizedBox(height: 6),
          Row(
            children: [
              LIcon(Symbols.smartphone_rounded, size: 13, color: p.dim),
              const SizedBox(width: 4),
              Flexible(
                child: Text(
                  '${n['app'] ?? ''} · ${s.ago(at)}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: SoraType.ui(11.5, color: p.dim),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
