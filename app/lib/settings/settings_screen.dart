import 'dart:async';
import 'dart:io' show Platform;
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:permission_handler/permission_handler.dart';

import '../core/api.dart';
import '../core/clip_sync.dart';
import '../core/session.dart';
import '../desktop/tray.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/sora_widgets.dart';
import '../voice/speaker.dart';
import '../voice/wake_service.dart';
import '../voice/wake_trainer.dart';
import 'package:sora_phone/sora_phone.dart';
import '../widgets/list_kit.dart';
import '../widgets/overlays.dart';
import 'notification_apps.dart';

/// Settings: Appearance (theme, app language), Voice (recognition language, Sora's voice with a
/// preview, speed, reading notifications aloud, "Hey Sora" on the phone), PC (start with Windows,
/// "Hey Sora" on the PC), Connection (server, live status, device name), About (app and server
/// versions) and Sign out.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, required this.session, required this.api, required this.onBack, this.events});

  final Session session;
  final SoraApi api;
  final VoidCallback onBack;

  /// The server's live events: the PC agent coming online fills in "Hey Sora" on the PC.
  final Stream<Map<String, dynamic>>? events;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> with WidgetsBindingObserver {
  Map<String, dynamic>? _health;
  int? _ms;
  bool _failed = false;
  String _app = '';
  late final _speaker = Speaker(widget.api, widget.session);
  StreamSubscription<Map<String, dynamic>>? _events;
  Timer? _retry;
  int _retryIn = 2;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _load();
    _checkA11y();
    _events = widget.events?.listen((e) {
      if (e['type'] == 'device_status') _loadPcAgent();
    });
    _speaker.warmPreviews();
    PackageInfo.fromPlatform().then((i) {
      if (mounted) setState(() => _app = '${i.version} (${i.buildNumber})');
    });
  }

  /// Everything from the server at once. Opened while the server is still starting (the app starts
  /// it), every request fails: try again a little later, more slowly each time, until it answers.
  Future<void> _load() async {
    _retry?.cancel();
    final results = await Future.wait([_ping(), _loadPc()]);
    if (!mounted) return;
    if (results.every((ok) => ok)) {
      _retryIn = 2;
      return;
    }
    _retry = Timer(Duration(seconds: _retryIn), _load);
    _retryIn = math.min(_retryIn * 2, 30);
  }

  // Back from the phone's Accessibility settings: show whether Sora is on now.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _checkA11y();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _events?.cancel();
    _retry?.cancel();
    _speaker.dispose();
    super.dispose();
  }

  Future<bool> _ping() async {
    final watch = Stopwatch()..start();
    try {
      final h = await widget.api.health();
      if (mounted) {
        setState(() {
          _health = h;
          _ms = watch.elapsedMilliseconds;
          _failed = false;
        });
      }
      return true;
    } catch (_) {
      if (mounted && !_failed) setState(() => _failed = true);
      return false;
    }
  }

  bool? _a11y; // Sora's accessibility service is on (screenshots, lock, opening apps in the background)

  Future<void> _checkA11y() async {
    if (!WakeService.supported) return;
    final on = await SoraPhone.accessibilityEnabled();
    if (mounted) setState(() => _a11y = on);
    try {
      final link = await SoraPhone.linkSettings();
      if (mounted) setState(() => _link = link);
    } catch (_) {}
    try {
      final mirror = await SoraPhone.notificationMirror();
      if (mounted) setState(() => _mirror = mirror);
    } catch (_) {}
  }

  Map<String, dynamic>? _mirror; // the phone's notifications on the PC: {enabled, access, allowed, apps}

  /// On asks for Notification access the first time (back here, [_checkA11y] shows whether it was given).
  Future<void> _setMirror(bool on) async {
    try {
      final mirror = await SoraPhone.notificationMirror(enabled: on);
      if (mounted) setState(() => _mirror = mirror);
      if (on && mirror['access'] != true) await SoraPhone.openNotificationAccess();
    } catch (_) {
      if (mounted) showToast(context, S.of(context).couldntChange);
    }
  }

  Future<void> _chooseMirrorApps() async {
    final mirror = _mirror;
    if (mirror == null) return;
    await showNotificationApps(context, mirror);
    _checkA11y();
  }

  /// "WhatsApp, Messenger +2": the apps chosen, by name.
  String _mirrorApps(S s) {
    final mirror = _mirror ?? const {};
    final allowed = {for (final a in mirror['allowed'] as List? ?? const []) '$a'};
    final names = [
      for (final a in mirror['apps'] as List? ?? const [])
        if (allowed.contains((a as Map)['package'])) '${a['label']}',
    ];
    if (names.isEmpty) return s.mirrorAppsNone;
    return names.length <= 3 ? names.join(', ') : '${names.take(3).join(', ')} +${s.num(names.length - 3)}';
  }

  Map<String, dynamic>? _link; // the background line to the PC: {connected, notify, online}

  Future<void> _setLink({bool? connected, bool? notify}) async {
    if (notify == true) await Permission.notification.request();
    try {
      final link = await SoraPhone.linkSettings(connected: connected, notify: notify);
      if (mounted) setState(() => _link = link);
    } catch (_) {
      if (mounted) showToast(context, S.of(context).couldntChange);
    }
  }

  Future<void> _setHandsFree(bool on) async {
    final session = widget.session;
    if (!on) {
      await WakeService.stop();
      await session.setHandsFree(false);
      return;
    }
    final ok = await WakeService.start(bangla: session.language == 'bn');
    if (!mounted) return;
    if (!ok) {
      showToast(context, S.of(context).handsFreeDenied);
      return;
    }
    await session.setHandsFree(true);
  }

  // ------------------------------------------------------------ PC

  bool? _autostart; // null: not offered (not the Windows app, or the server isn't on Windows)
  bool _autostartBusy = false;
  String? _pcId; // the online PC agent
  bool _pcLoaded = false, _heySoraBusy = false;
  bool? _heySora; // null: the agent didn't say (older agent)
  bool? _clipSync; // null: not known yet
  bool? _phoneToast; // Windows: the phone's notifications as Windows toasts (a server setting)

  /// The PC rows, asked for all at once (one after another, they came in one by one). False when
  /// the server didn't answer.
  Future<bool> _loadPc() async {
    Future<Map<String, dynamic>?> ask(Future<Map<String, dynamic>> Function() call) async {
      try {
        return await call();
      } catch (_) {
        return null;
      }
    }

    final asking = _loadPcAgent(update: false);
    final answers = await Future.wait([
      Platform.isWindows ? ask(widget.api.autostart) : Future.value(null),
      ask(widget.api.clipboard),
      Platform.isWindows ? ask(widget.api.phoneNotifications) : Future.value(null),
    ]);
    final agent = await asking;
    if (!mounted) return false;
    final [a, c, n] = answers;
    setState(() {
      if (a != null && a['supported'] == true) _autostart = a['enabled'] == true;
      if (c != null) _clipSync = c['enabled'] != false;
      if (n != null) _phoneToast = n['toast'] != false;
      if (agent != null) {
        _pcId = agent.$1;
        _heySora = agent.$2;
      }
      _pcLoaded = true;
    });
    return c != null && agent != null;
  }

  /// The online PC agent and whether its "Hey Sora" is on; null when the server didn't answer.
  /// Again when a device comes online or goes away, so the row follows the agent.
  Future<(String?, bool?)?> _loadPcAgent({bool update = true}) async {
    (String?, bool?)? agent;
    try {
      final devices = [for (final d in await widget.api.devices()) Map<String, dynamic>.from(d as Map)];
      final pc = devices.where((d) => d['kind'] == 'pc_agent' && d['online'] == true).firstOrNull;
      final id = pc?['id'] as String?;
      bool? on;
      if (id != null) {
        try {
          on = (await widget.api.heySora(id))['enabled'] == true;
        } catch (_) {}
      }
      agent = (id, on);
    } catch (_) {}
    if (update && agent != null && mounted && (agent.$1 != _pcId || agent.$2 != _heySora || !_pcLoaded)) {
      setState(() {
        _pcId = agent!.$1;
        _heySora = agent.$2;
        _pcLoaded = true;
      });
    }
    return agent;
  }

  Future<void> _setAutostart(bool on) async {
    setState(() {
      _autostartBusy = true;
      _autostart = on;
    });
    try {
      final a = await widget.api.setAutostart(on);
      if (mounted) setState(() => _autostart = a['enabled'] == true);
    } catch (_) {
      if (mounted) {
        setState(() => _autostart = !on);
        showToast(context, S.of(context).couldntChange);
      }
    } finally {
      if (mounted) setState(() => _autostartBusy = false);
    }
  }

  Future<void> _setHeySora(bool on) async {
    final id = _pcId;
    if (id == null) return;
    setState(() {
      _heySoraBusy = true;
      _heySora = on;
    });
    try {
      final h = await widget.api.heySora(id, on: on);
      if (mounted) setState(() => _heySora = h['enabled'] == true);
    } catch (_) {
      if (mounted) {
        setState(() => _heySora = !on);
        showToast(context, S.of(context).couldntChange);
      }
    } finally {
      if (mounted) setState(() => _heySoraBusy = false);
    }
  }

  Future<void> _setPhoneToast(bool on) async {
    setState(() => _phoneToast = on);
    try {
      await widget.api.setPhoneNotificationToast(on);
    } catch (_) {
      if (mounted) {
        setState(() => _phoneToast = !on);
        showToast(context, S.of(context).couldntChange);
      }
    }
  }

  Future<void> _setClipSync(bool on) async {
    final s = S.of(context);
    if (on && WakeService.supported) {
      await Permission.photos.request(); // new screenshots; copying text works without it
      if (_a11y != true && mounted) {
        showToast(context, s.phoneControlHint);
        await SoraPhone.openAccessibilitySettings();
      }
    }
    setState(() => _clipSync = on);
    try {
      await widget.api.setClipboardSync(on);
      await ClipSync.setOn(on);
    } catch (_) {
      if (mounted) {
        setState(() => _clipSync = !on);
        showToast(context, s.couldntChange);
      }
    }
  }

  /// "Turn Sora off": the PC agent (with its mic) and the server stop, then this app closes;
  /// opening the app again starts them (ServerLink).
  Future<void> _turnOff() async {
    final s = S.of(context);
    final ok = await showConfirmSheet(context, title: s.turnSoraOff, text: s.turnSoraOffQ, confirm: s.turnOff, danger: true);
    if (!ok || !mounted) return;
    try {
      await widget.api.stopSora();
    } catch (_) {
      if (mounted) showToast(context, s.couldntChange);
      return;
    }
    await SoraTray.instance.quit();
  }

  Future<void> _signOut() async {
    await WakeService.stop();
    try {
      await widget.api.logout();
    } catch (_) {}
    await widget.session.signOut();
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final session = widget.session;
    final h = _health;

    Widget section(String label, {bool first = false}) => Padding(
      padding: EdgeInsets.fromLTRB(4, first ? 6 : 12, 4, 2),
      child: MonoLabel(label, weight: FontWeight.w500),
    );

    // Grows smoothly when a row arrives later (what the server or the phone reports comes in after
    // the screen opens), instead of jumping.
    Widget card(List<Widget> rows) => AnimatedSize(
      duration: const Duration(milliseconds: 240),
      curve: Curves.easeOutCubic,
      alignment: Alignment.topCenter,
      child: Glass(
        radius: 18,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (var i = 0; i < rows.length; i++)
              DecoratedBox(
                decoration: BoxDecoration(
                  border: i > 0 ? Border(top: BorderSide(color: p.line)) : null,
                ),
                child: rows[i],
              ),
          ],
        ),
      ),
    );

    Widget choice<T>(String label, List<(T, String)> options, T value, ValueChanged<T> onChanged) => Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            label,
            style: SoraType.ui(14, weight: FontWeight.w500, color: p.ink),
          ),
          const SizedBox(height: 8),
          SoraSegmented<T>(options: options, value: value, onChanged: onChanged),
        ],
      ),
    );

    Widget row(String label, Widget value) => Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: SoraType.ui(14, weight: FontWeight.w500, color: p.ink),
            ),
          ),
          const SizedBox(width: 10),
          Flexible(
            child: Align(alignment: Alignment.centerRight, child: value),
          ),
        ],
      ),
    );

    Widget switchRow(String title, String hint, bool value, ValueChanged<bool>? onChanged) => Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: SoraType.ui(14, weight: FontWeight.w500, color: p.ink, height: 1.4),
                ),
                const SizedBox(height: 4),
                Text(hint, style: SoraType.ui(12.5, color: p.dim, height: 1.45)),
              ],
            ),
          ),
          const SizedBox(width: 12),
          Opacity(
            opacity: onChanged == null ? 0.5 : 1,
            child: SoraSwitch(value: value, onChanged: onChanged),
          ),
        ],
      ),
    );

    Text mono(String text) => Text(
      text,
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
      style: SoraType.mono(12.5, weight: FontWeight.w400, spacing: 0, color: p.dim),
    );

    final status = _failed
        ? Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 7,
                height: 7,
                decoration: BoxDecoration(color: p.err, shape: BoxShape.circle),
              ),
              const SizedBox(width: 6),
              Text(s.offline, style: SoraType.ui(13.5, color: p.err)),
            ],
          )
        : h == null
        ? Spinner(size: 16, color: p.dim)
        : Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 7,
                height: 7,
                decoration: BoxDecoration(color: p.ok, shape: BoxShape.circle),
              ),
              const SizedBox(width: 6),
              Text('${s.connectedS} · ${s.num(_ms ?? 0)} ms', style: SoraType.ui(13.5, color: p.ok)),
            ],
          );

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SoraBackground(
        child: SafeArea(
          child: Column(
            children: [
              ScreenHeader(title: s.settings, onBack: widget.onBack),
              Expanded(
                child: ListenableBuilder(
                  listenable: session,
                  builder: (context, _) => ListView(
                    padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                    children: [
                      section(s.appearance, first: true),
                      const SizedBox(height: 4),
                      card([
                        choice<ThemeMode>(
                          s.theme,
                          [(ThemeMode.system, s.themeAuto), (ThemeMode.light, s.themeLight), (ThemeMode.dark, s.themeDark)],
                          session.themeMode,
                          session.setThemeMode,
                        ),
                        choice<String>(s.appLang, const [('en', 'English'), ('bn', 'বাংলা')], session.language, session.setLanguage),
                      ]),
                      section(s.voiceSec),
                      const SizedBox(height: 4),
                      card([
                        choice<String>(
                          s.voiceLang,
                          const [('en', 'English'), ('bn', 'বাংলা')],
                          session.voiceLanguage,
                          session.setVoiceLanguage,
                        ),
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Text(
                                s.soraVoice,
                                style: SoraType.ui(14, weight: FontWeight.w500, color: p.ink),
                              ),
                              for (final v in SoraVoice.all) ...[const SizedBox(height: 8), _voiceRow(v, p, s)],
                              const SizedBox(height: 14),
                              Text(
                                s.speed,
                                style: SoraType.ui(14, weight: FontWeight.w500, color: p.ink),
                              ),
                              const SizedBox(height: 8),
                              SoraSegmented<double>(
                                options: const [(0.9, '0.9×'), (1.0, '1.0×'), (1.2, '1.2×')],
                                value: session.voiceSpeed,
                                onChanged: session.setVoiceSpeed,
                              ),
                            ],
                          ),
                        ),
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                          child: Row(
                            children: [
                              Expanded(
                                child: Text(
                                  s.readAloudNotif,
                                  style: SoraType.ui(14, weight: FontWeight.w500, color: p.ink, height: 1.4),
                                ),
                              ),
                              const SizedBox(width: 12),
                              SoraSwitch(value: session.readAloud, onChanged: session.setReadAloud),
                            ],
                          ),
                        ),
                        if (WakeService.supported)
                          Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                            child: Row(
                              children: [
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        s.handsFree,
                                        style: SoraType.ui(14, weight: FontWeight.w500, color: p.ink, height: 1.4),
                                      ),
                                      const SizedBox(height: 4),
                                      Text(s.handsFreeHint, style: SoraType.ui(12.5, color: p.dim, height: 1.45)),
                                    ],
                                  ),
                                ),
                                const SizedBox(width: 12),
                                SoraSwitch(value: session.handsFree, onChanged: _setHandsFree),
                              ],
                            ),
                          ),
                        WakeTrainer(api: widget.api),
                        if (WakeService.supported)
                          Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                            child: Row(
                              children: [
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        s.phoneControl,
                                        style: SoraType.ui(14, weight: FontWeight.w500, color: p.ink, height: 1.4),
                                      ),
                                      const SizedBox(height: 4),
                                      Text(s.phoneControlHint, style: SoraType.ui(12.5, color: p.dim, height: 1.45)),
                                    ],
                                  ),
                                ),
                                const SizedBox(width: 12),
                                if (_a11y == true)
                                  Text(
                                    s.isOn,
                                    style: SoraType.ui(13.5, weight: FontWeight.w600, color: p.ok),
                                  )
                                else
                                  GlassButton(
                                    label: s.turnOn,
                                    height: 36,
                                    radius: 12,
                                    fontSize: 13.5,
                                    onTap: () async {
                                      await SoraPhone.openAccessibilitySettings();
                                    },
                                  ),
                              ],
                            ),
                          ),
                        if (WakeService.supported && _a11y == true && _link != null) ...[
                          switchRow(
                            s.pcLink,
                            _link!['connected'] != true ? s.pcLinkOff : (_link!['online'] == true ? s.pcLinkOn : s.pcLinkWaiting),
                            _link!['connected'] == true,
                            (on) => _setLink(connected: on),
                          ),
                          switchRow(s.pcLinkNotify, s.pcLinkNotifyHint, _link!['notify'] == true, (on) => _setLink(notify: on)),
                          if (_mirror case final mirror?) ...[
                            switchRow(
                              s.mirrorNotifs,
                              mirror['enabled'] == true && mirror['access'] != true ? s.mirrorNotifsAccess : s.mirrorNotifsHint,
                              mirror['enabled'] == true,
                              _setMirror,
                            ),
                            if (mirror['enabled'] == true)
                              Pressable(
                                onTap: _chooseMirrorApps,
                                child: row(
                                  s.mirrorApps,
                                  Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Flexible(
                                        child: Text(
                                          _mirrorApps(s),
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis,
                                          style: SoraType.ui(13.5, color: p.dim),
                                        ),
                                      ),
                                      LIcon(Symbols.chevron_right_rounded, size: 20, color: p.dim),
                                    ],
                                  ),
                                ),
                              ),
                          ],
                        ],
                      ]),
                      if (_autostart != null || _pcLoaded || _clipSync != null) ...[
                        Rise(child: section(Platform.isWindows ? s.thisPc : 'PC')),
                        const SizedBox(height: 4),
                        card([
                          if (Platform.isWindows)
                            switchRow(s.closeToTray, s.closeToTrayHint, session.closeToTray, (on) => session.setCloseToTray(on)),
                          if (Platform.isWindows)
                            switchRow(
                              s.phoneNotifsPanel,
                              s.phoneNotifsPanelHint,
                              session.phoneNotifications,
                              (on) => session.setPhoneNotifications(on),
                            ),
                          if (_phoneToast != null) switchRow(s.phoneNotifsToast, s.phoneNotifsToastHint, _phoneToast!, _setPhoneToast),
                          if (_autostart != null)
                            switchRow(s.startWithWindows, s.startWithWindowsHint, _autostart!, _autostartBusy ? null : _setAutostart),
                          if (_clipSync != null)
                            switchRow(
                              WakeService.supported ? s.syncClipboard : s.syncClipboardPc,
                              WakeService.supported ? s.syncClipboardHint : s.syncClipboardPcHint,
                              _clipSync!,
                              _setClipSync,
                            ),
                          if (_pcLoaded)
                            switchRow(
                              s.pcHeySora,
                              _pcId == null ? s.pcAgentOff : s.pcHeySoraHint,
                              _heySora ?? false,
                              _pcId == null || _heySora == null || _heySoraBusy ? null : _setHeySora,
                            ),
                          if (_autostart != null)
                            Pressable(
                              onTap: _turnOff,
                              // The rows' own padding and type (switchRow), the icon on the title's line.
                              child: Padding(
                                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                                child: Row(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    SizedBox(
                                      height: 14 * 1.4,
                                      child: Center(child: LIcon(Symbols.power_settings_new_rounded, size: 19, color: p.err)),
                                    ),
                                    const SizedBox(width: 10),
                                    Expanded(
                                      child: Column(
                                        crossAxisAlignment: CrossAxisAlignment.start,
                                        children: [
                                          Text(
                                            s.turnSoraOff,
                                            style: SoraType.ui(14, weight: FontWeight.w600, color: p.err, height: 1.4),
                                          ),
                                          const SizedBox(height: 4),
                                          Text(s.turnSoraOffHint, style: SoraType.ui(12.5, color: p.dim, height: 1.45)),
                                        ],
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                        ]),
                      ],
                      section(s.connection),
                      const SizedBox(height: 4),
                      card([
                        row(s.server, mono(session.serverUrl ?? '')),
                        row(s.status, status),
                        row(s.deviceName, Text(session.deviceName ?? '—', style: SoraType.ui(13.5, color: p.dim))),
                      ]),
                      section(s.about),
                      const SizedBox(height: 4),
                      card([
                        row(s.version, mono(_app)),
                        row(
                          s.serverVer,
                          mono(h == null ? '—' : [h['version'], if (h['tools'] != null) s.tools(h['tools'] as int)].join(' · ')),
                        ),
                      ]),
                      const SizedBox(height: 14),
                      Pressable(
                        onTap: _signOut,
                        child: Container(
                          height: 48,
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(16),
                            border: Border.all(color: p.line),
                          ),
                          child: Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              LIcon(Symbols.logout_rounded, size: 19, color: p.err),
                              const SizedBox(width: 8),
                              Text(
                                s.signOut,
                                style: SoraType.ui(15, weight: FontWeight.w600, color: p.err),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

extension on _SettingsScreenState {
  /// One voice choice: name and description, a play button for a sample, a check when chosen.
  Widget _voiceRow(SoraVoice v, SoraPalette p, S s) {
    final on = widget.session.voice == v.name;
    return Pressable(
      onTap: () {
        widget.session.setVoice(v.name);
        _speaker.preview(v.name);
      },
      child: Glass(
        radius: 14,
        fill: on ? p.accSoft : p.surf,
        borderColor: on ? p.acc : p.line,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        child: Row(
          children: [
            LIcon(Symbols.graphic_eq_rounded, size: 20, color: p.acc),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    v.name,
                    style: SoraType.ui(14.5, weight: FontWeight.w600, color: p.ink, height: 1.35),
                  ),
                  Text(s.isBn ? v.descBn : v.descEn, style: SoraType.ui(12.5, color: p.dim, height: 1.35)),
                ],
              ),
            ),
            Tooltip(
              message: s.play,
              child: Pressable(
                onTap: () => _speaker.preview(v.name),
                child: Glass(
                  width: 30,
                  height: 30,
                  radius: 15,
                  fill: p.glass2,
                  blur: false,
                  child: Center(child: LIcon(Symbols.play_arrow_rounded, size: 18, color: p.ink, fill: true)),
                ),
              ),
            ),
            if (on) ...[const SizedBox(width: 10), LIcon(Symbols.check_circle_rounded, size: 21, color: p.acc, fill: true)],
          ],
        ),
      ),
    );
  }
}
