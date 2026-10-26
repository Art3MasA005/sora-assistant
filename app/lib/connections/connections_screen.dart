import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/list_kit.dart';
import '../widgets/sora_widgets.dart';
import '../widgets/overlays.dart';

/// Connections: the Google account card with "Connect all", then one row per service with its own
/// Connect button (Google asks for that service only) or an on/off switch once connected.
class ConnectionsScreen extends StatefulWidget {
  const ConnectionsScreen({super.key, required this.api, this.onBack});

  final SoraApi api;
  final VoidCallback? onBack;

  @override
  State<ConnectionsScreen> createState() => _ConnectionsScreenState();
}

class _ConnectionsScreenState extends State<ConnectionsScreen> with WidgetsBindingObserver {
  Map<String, dynamic>? _conn;
  bool _failed = false;

  /// Services waiting for the owner to finish in the browser.
  final _waiting = <String>{};
  final _busy = <String>{};

  static const _look = <String, (IconData, Color)>{
    'gmail': (Symbols.mail_rounded, Color(0xFFEA4335)),
    'calendar': (Symbols.calendar_month_rounded, Color(0xFF4285F4)),
    'drive': (Symbols.add_to_drive_rounded, Color(0xFF1FA463)),
    'docs': (Symbols.description_rounded, Color(0xFF4285F4)),
    'sheets': (Symbols.table_chart_rounded, Color(0xFF1FA463)),
    'slides': (Symbols.slideshow_rounded, Color(0xFFF4B400)),
    'tasks': (Symbols.task_alt_rounded, Color(0xFF4285F4)),
    'contacts': (Symbols.contacts_rounded, Color(0xFF4285F4)),
  };

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _load();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  // Back from the browser after approving at Google: refresh.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _load(afterGoogle: true);
  }

  Future<void> _load({bool afterGoogle = false}) async {
    try {
      final c = await widget.api.googleConnection();
      if (!mounted) return;
      final s = S.of(context);
      final before = _waiting.toSet();
      setState(() {
        _conn = c;
        _failed = false;
        if (afterGoogle) _waiting.clear();
      });
      for (final svc in (c['services'] as List).cast<Map>()) {
        if (before.contains(svc['id']) && svc['connected'] == true) showToast(context, s.isConnected(1).replaceFirst(RegExp('^\\S+ '), '${svc['label']} '));
      }
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  Future<void> _connect(List<String> services) async {
    final s = S.of(context);
    // An empty list asks Google for everything; show every service as waiting.
    final marked = services.isEmpty ? [for (final x in (_conn?['services'] as List? ?? const [])) (x as Map)['id'] as String] : services;
    setState(() => _waiting.addAll(marked));
    try {
      final url = await widget.api.startGoogle(services);
      final ok = await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
      if (!ok && mounted) {
        showToast(context, s.browserFailed);
        setState(() => _waiting.removeAll(marked));
      }
    } catch (e) {
      if (mounted) {
        showToast(context, e.toString());
        setState(() => _waiting.removeAll(marked));
      }
    }
  }

  Future<void> _toggle(String service, bool enabled) async {
    setState(() => _busy.add(service));
    try {
      final c = await widget.api.setServiceEnabled(service, enabled);
      if (mounted) setState(() => _conn = c);
    } catch (e) {
      if (mounted) showToast(context, e.toString());
    } finally {
      if (mounted) setState(() => _busy.remove(service));
    }
  }

  Future<void> _disconnect() async {
    final s = S.of(context);
    final ok = await showConfirmSheet(context, title: s.disconnectG, text: s.disconnectQ, confirm: s.disconnectG, danger: true);
    if (ok && mounted && await guard(context, widget.api.disconnectGoogle)) _load();
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final conn = _conn;
    final services = (conn?['services'] as List?)?.cast<Map>().map((m) => Map<String, dynamic>.from(m)).toList() ?? [];
    final configured = conn?['configured'] == true;
    final expired = conn != null && conn['status'] != null && conn['status'] != 'active';
    final count = services.where((x) => x['connected'] == true).length;
    final missing = services.where((x) => x['connected'] != true).map((x) => x['id'] as String).toList();

    return ListScreen(
      title: s.connections,
      onBack: widget.onBack ?? () => Navigator.of(context).maybePop(),
      onRefresh: _load,
      children: [
        if (_failed && conn == null)
          EmptyState(icon: Symbols.cloud_off_rounded, text: s.loadFailed)
        else if (conn == null)
          Padding(padding: const EdgeInsets.all(48), child: Center(child: Spinner(size: 22, color: p.acc)))
        else if (!configured)
          Padding(padding: const EdgeInsets.all(16), child: NoticeRow(text: s.googleNotConfigured, icon: Symbols.info_rounded, tint: p.amberSoft, color: p.amber))
        else ...[
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Glass(
              radius: 18,
              padding: const EdgeInsets.all(14),
              child: Row(
                children: [
                  Glass(
                    width: 40,
                    height: 40,
                    radius: 20,
                    fill: p.glass2,
                    blur: false,
                    child: Center(child: Text('G', style: SoraType.ui(18, weight: FontWeight.w700, color: const Color(0xFF4285F4)))),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Google · ${s.isConnected(count)}', style: SoraType.ui(14.5, weight: FontWeight.w600, color: p.ink)),
                        if (conn['account_email'] != null)
                          Text(
                            conn['account_email'] as String,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: SoraType.ui(12.5, color: p.dim),
                          ),
                      ],
                    ),
                  ),
                  if (missing.isNotEmpty || expired)
                    PillButton(label: s.connectAll, filled: true, onTap: () => _connect(expired ? [] : missing)),
                ],
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                LIcon(Symbols.info_rounded, size: 16, color: p.acc),
                const SizedBox(width: 8),
                Expanded(child: Text(s.connectionsHint, style: SoraType.ui(12.5, color: p.dim, height: 1.45))),
              ],
            ),
          ),
          for (final svc in services) _row(svc, expired, p, s),
          if (conn['connected'] == true || expired)
            Center(
              child: Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Pressable(
                  onTap: _disconnect,
                  child: Container(
                    height: 42,
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    decoration: BoxDecoration(borderRadius: BorderRadius.circular(21), border: Border.all(color: p.line)),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        LIcon(Symbols.link_off_rounded, size: 18, color: p.err),
                        const SizedBox(width: 6),
                        Text(s.disconnectG, style: SoraType.ui(14, weight: FontWeight.w500, color: p.err)),
                      ],
                    ),
                  ),
                ),
              ),
            ),
        ],
      ],
    );
  }

  Widget _row(Map<String, dynamic> svc, bool expired, SoraPalette p, S s) {
    final id = svc['id'] as String;
    final (icon, color) = _look[id] ?? (Symbols.extension_rounded, p.acc);
    final waiting = _waiting.contains(id);
    final connected = svc['connected'] == true && !expired;
    final wasGranted = svc['granted'] == true;
    final isExpired = expired && wasGranted;
    final Widget trailing;
    if (waiting) {
      trailing = Padding(padding: const EdgeInsets.fromLTRB(10, 6, 10, 0), child: Spinner(size: 22, color: p.acc));
    } else if (isExpired) {
      trailing = PillButton(label: s.reconnect, filled: true, color: p.amber, onTap: () => _connect([id]));
    } else if (connected) {
      trailing = Opacity(
        opacity: _busy.contains(id) ? .5 : 1,
        child: SoraSwitch(value: svc['enabled'] == true, onChanged: _busy.contains(id) ? null : (v) => _toggle(id, v)),
      );
    } else {
      trailing = PillButton(label: s.connectB, onTap: () => _connect([id]));
    }
    return Container(
      margin: const EdgeInsets.fromLTRB(8, 0, 8, 2),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: isExpired ? p.amberSoft : null,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: isExpired ? p.amberLine : p.amberLine.withAlpha(0)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          IconTile(icon: icon, color: color, iconSize: 21, fillIcon: true),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(s.serviceLabels[id] ?? svc['label'] as String? ?? id, style: SoraType.ui(14.5, weight: FontWeight.w600, color: p.ink)),
                const SizedBox(height: 2),
                Text(
                  s.serviceDescriptions[id] ?? svc['description'] as String? ?? '',
                  style: SoraType.ui(12.5, color: p.dim, height: 1.4),
                ),
                if (isExpired) Text(s.expiredAccess, style: SoraType.ui(12.5, weight: FontWeight.w500, color: p.amber, height: 1.4)),
                if (waiting) Text(s.waitingG, style: SoraType.ui(12.5, color: p.acc)),
                if (connected && !waiting)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Row(
                      children: [
                        LIcon(Symbols.check_circle_rounded, size: 14, color: p.ok, fill: true),
                        const SizedBox(width: 4),
                        Text(s.connectedL, style: SoraType.ui(12, weight: FontWeight.w500, color: p.ok)),
                      ],
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          Padding(padding: const EdgeInsets.only(top: 4), child: trailing),
        ],
      ),
    );
  }
}
