import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../core/api.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/overlays.dart';
import '../widgets/sora_widgets.dart';
import '../widgets/screenshot_view.dart';
import '../widgets/shot_actions.dart';
import 'desktop_kit.dart';

/// Details panel → the phone: battery, network, storage, sound and model (refreshed every 30 s),
/// and Screenshot (shown here to copy, crop or save), Ring (find my phone), Lock and Mute.
/// [phone] is the online Android device from `/api/devices`; [pc] the PC agent, which puts a
/// screenshot on this PC's clipboard.
class PhoneSection extends StatefulWidget {
  const PhoneSection({super.key, required this.api, required this.phone, required this.pc});

  final SoraApi api;
  final Map<String, dynamic>? phone;
  final Map<String, dynamic>? pc;

  @override
  State<PhoneSection> createState() => _PhoneSectionState();
}

class _PhoneSectionState extends State<PhoneSection> {
  Timer? _poll;
  Map<String, dynamic>? _status;
  bool _ringing = false;
  String? _busy; // the action running now

  String? get _id => widget.phone?['id'] as String?;

  @override
  void initState() {
    super.initState();
    _load();
    _poll = Timer.periodic(const Duration(seconds: 30), (_) => _load());
  }

  @override
  void didUpdateWidget(PhoneSection old) {
    super.didUpdateWidget(old);
    if (old.phone?['id'] != widget.phone?['id']) _load();
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final id = _id;
    if (id == null) return;
    try {
      final r = await widget.api.deviceCommand(id, 'status');
      if (mounted && r is String) setState(() => _status = Map<String, dynamic>.from(jsonDecode(r) as Map));
    } catch (_) {}
  }

  /// Runs a phone action; its result, or null after a toast saying why not.
  Future<Object?> _run(String action, [Map<String, dynamic> params = const {}]) async {
    final id = _id;
    if (id == null) return null;
    setState(() => _busy = action);
    try {
      return await widget.api.deviceCommand(id, action, params) ?? true;
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.status == 409 ? S.of(context).phoneOff : e.message);
    } catch (e) {
      if (mounted) showToast(context, e.toString());
    } finally {
      if (mounted) setState(() => _busy = null);
    }
    return null;
  }

  Future<void> _screenshot() async {
    final r = await _run('screenshot', {'send': true});
    if (r is! String || !mounted) return;
    try {
      final b64 = (jsonDecode(r) as Map)['png_base64'] as String;
      final s = S.of(context);
      await showScreenshot(
        context,
        png: base64Decode(b64),
        title: s.phoneScreenshot,
        actions: pcShotActions(s, widget.api, widget.pc, name: 'phone'),
      );
    } catch (_) {
      if (mounted) showToast(context, S.of(context).genericError);
    }
  }

  Future<void> _ring() async {
    final s = S.of(context);
    final stop = _ringing;
    final r = await _run('ring', stop ? {'target': 'stop'} : {'seconds': 30});
    if (r == null || !mounted) return;
    setState(() => _ringing = !stop);
    if (!stop) {
      showToast(context, s.ringing);
      Timer(const Duration(seconds: 30), () {
        if (mounted) setState(() => _ringing = false);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final phone = widget.phone;
    final st = _status;
    if (phone == null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          MonoLabel(s.fromPhone),
          const SizedBox(height: 8),
          DashedBox(child: Text(s.phoneOff, style: SoraType.ui(13, color: p.dim, height: 1.45))),
        ],
      );
    }
    final battery = st?['battery'] as num?;
    final charging = st?['charging'] == true;
    Widget fact(IconData icon, String text) => Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          LIcon(icon, size: 16, color: p.dim),
          const SizedBox(width: 8),
          Expanded(child: Text(text, maxLines: 1, overflow: TextOverflow.ellipsis, style: SoraType.ui(12.5, color: p.ink))),
        ],
      ),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Container(width: 6, height: 6, decoration: BoxDecoration(color: p.ok, shape: BoxShape.circle)),
            const SizedBox(width: 6),
            Expanded(child: MonoLabel('${phone['name'] ?? s.fromPhone}')),
          ],
        ),
        const SizedBox(height: 8),
        if (st != null)
          Glass(
            radius: 14,
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 4),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (battery != null)
                  fact(
                    charging ? Symbols.battery_charging_full_rounded : _batteryIcon(battery),
                    '${s.num(battery)}%${charging ? ' · ${s.charging}' : ''}',
                  ),
                fact(
                  st['network'] == 'wifi'
                      ? Symbols.wifi_rounded
                      : st['network'] == 'mobile'
                      ? Symbols.signal_cellular_alt_rounded
                      : Symbols.signal_disconnected_rounded,
                  st['network'] == 'wifi' ? 'Wi-Fi' : (st['network'] == 'mobile' ? 'Mobile data' : '—'),
                ),
                if (st['storage_free_gb'] != null)
                  fact(Symbols.storage_rounded, s.storageFree(s.num(st['storage_free_gb']), s.num(st['storage_total_gb']))),
                fact(
                  st['ringer'] == 'silent'
                      ? Symbols.notifications_off_rounded
                      : st['ringer'] == 'vibrate'
                      ? Symbols.vibration_rounded
                      : Symbols.notifications_active_rounded,
                  st['ringer'] == 'silent' ? s.ringerSilent : (st['ringer'] == 'vibrate' ? s.ringerVibrate : s.ringerNormal),
                ),
                fact(Symbols.smartphone_rounded, '${st['model']} · Android ${st['android']}'),
              ],
            ),
          ),
        const SizedBox(height: 8),
        GridView.count(
          crossAxisCount: 2,
          mainAxisSpacing: 8,
          crossAxisSpacing: 8,
          childAspectRatio: 130 / 52,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          padding: EdgeInsets.zero,
          children: [
            _button(Symbols.screenshot_rounded, s.screenshot, 'screenshot', _screenshot),
            _button(
              _ringing ? Symbols.notifications_off_rounded : Symbols.ring_volume_rounded,
              _ringing ? s.stopRing : s.ring,
              'ring',
              _ring,
            ),
            _button(Symbols.lock_rounded, s.lock, 'lock', () => _run('lock')),
            _button(Symbols.volume_off_rounded, s.mute, 'volume', () => _run('volume', {'target': 'mute'})),
          ],
        ),
      ],
    );
  }

  static IconData _batteryIcon(num level) => level >= 90
      ? Symbols.battery_full_rounded
      : level >= 50
      ? Symbols.battery_5_bar_rounded
      : level >= 20
      ? Symbols.battery_3_bar_rounded
      : Symbols.battery_1_bar_rounded;

  Widget _button(IconData icon, String label, String action, VoidCallback onTap) {
    final p = SoraPalette.of(context);
    return Hover(
      onTap: _busy == null ? onTap : null,
      builder: (_, hover) => AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: soraCard(p, radius: 14).copyWith(color: hover ? p.surf2 : p.surf),
        child: Row(
          children: [
            if (_busy == action) Spinner(size: 17, color: p.acc) else LIcon(icon, size: 19, color: p.acc),
            const SizedBox(width: 8),
            Expanded(child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: SoraType.ui(13, color: p.ink))),
          ],
        ),
      ),
    );
  }
}
