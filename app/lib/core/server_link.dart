import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:web_socket_channel/io.dart';

import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:sora_phone/sora_phone.dart';

import '../phone/phone_actions.dart';
import '../voice/wake_service.dart';
import 'clip_sync.dart';
import 'server_finder.dart';
import 'session.dart';

/// Gets the app back to its server when requests stop going through: on Windows it starts Sora if
/// it is off (the server writes how in %LOCALAPPDATA%\Sora\backend.json), then it looks for the
/// server ([ServerFinder]) and keeps the address that answers.
class ServerLink {
  ServerLink(this.session);

  final Session session;
  Future<bool>? _running;
  DateTime? _launched;

  /// True when the server answers again (possibly at a new address).
  Future<bool> recover() => _running ??= _recover().whenComplete(() => _running = null);

  Future<bool> _recover() async {
    final token = session.token;
    if (token == null) return false;
    var url = await ServerFinder.find(token: token, current: session.serverUrl);
    if (url == null && Platform.isWindows && await _startBackend()) {
      // Sora takes a few seconds to come up (the database, then the server).
      for (var i = 0; i < 12 && url == null; i++) {
        await Future<void>.delayed(const Duration(seconds: 3));
        url = await ServerFinder.find(token: token, current: session.serverUrl);
      }
    }
    if (url == null) return false;
    if (url != session.serverUrl) await session.setServer(url);
    return true;
  }

  /// Starts the server and the PC agent hidden (each one exits at once if it is already running).
  /// At most once every two minutes.
  Future<bool> _startBackend() async {
    final last = _launched;
    if (last != null && DateTime.now().difference(last) < const Duration(minutes: 2)) return false;
    final appData = Platform.environment['LOCALAPPDATA'];
    if (appData == null) return false;
    final file = File('$appData\\Sora\\backend.json');
    if (!await file.exists()) return false;
    try {
      final how = jsonDecode(await file.readAsString()) as Map<String, dynamic>;
      final exe = how['exe'] as String, cwd = how['cwd'] as String;
      for (final which in ['server', 'agent']) {
        final args = [for (final a in how[which] as List) a as String];
        await Process.start(exe, args, workingDirectory: cwd, mode: ProcessStartMode.detached);
      }
      _launched = DateTime.now();
      return true;
    } catch (_) {
      return false;
    }
  }
}

/// The phone's live line to the server while the app runs, so the server sees the phone online and
/// "open YouTube on my phone" said on the PC reaches it. Usually the accessibility service holds it
/// (SoraLink, app open or closed; this tells it the address and token), or the "Hey Sora" service;
/// this opens one only when neither does (one line per device: a second one replaces the first).
class LiveLink {
  LiveLink(this.session);

  final Session session;
  bool _on = false;
  IOWebSocketChannel? _ws;
  String? _told; // the server/token last given to the accessibility service's line
  final _own = StreamController<Map<String, dynamic>>.broadcast(); // from this class's own line

  static bool get supported => Platform.isAndroid;

  /// What the server pushes for the screens (a device came online or went away), over whichever
  /// line is up: the accessibility service's (through the plugin) or this one.
  late final Stream<Map<String, dynamic>> events = supported ? _merge(SoraPhone.events, _own.stream) : _own.stream;

  static Stream<Map<String, dynamic>> _merge(Stream<Map<String, dynamic>> a, Stream<Map<String, dynamic>> b) {
    final out = StreamController<Map<String, dynamic>>.broadcast();
    StreamSubscription<Map<String, dynamic>>? sa, sb;
    out.onListen = () {
      sa = a.listen(out.add);
      sb = b.listen(out.add);
    };
    out.onCancel = () {
      sa?.cancel();
      sb?.cancel();
    };
    return out.stream;
  }

  DateTime? _nudged;

  /// The accessibility service's line is down while this app reaches the server: it may still be
  /// trying an old address (the PC or the phone got a new one from the router). Give it the one that
  /// works; it switches to it, or just tries again now if it had it. At most every 30 s, app open only.
  Future<void> _nudgeLink(String server, String token, bool bangla) async {
    final last = _nudged;
    if (last != null && DateTime.now().difference(last) < const Duration(seconds: 30)) return;
    try {
      final link = await SoraPhone.linkSettings();
      if (link['online'] == true || link['connected'] != true) return; // up, or the owner disconnected it
      _nudged = DateTime.now();
      if (!await ServerFinder.isSora(server, token: token)) return; // the shells look for the server
      await SoraPhone.link(server, token, bangla: bangla);
    } catch (_) {}
  }

  void start() {
    if (!supported || _on) return;
    _on = true;
    unawaited(_loop());
    unawaited(ClipSync.start(server: () => session.serverUrl, token: () => session.token));
    unawaited(_askToRunFreely());
  }

  /// Once: Android's battery saver may cut the background line's network while the phone sleeps;
  /// letting Sora run unrestricted keeps it (an idle socket, so it costs next to nothing).
  Future<void> _askToRunFreely() async {
    const store = FlutterSecureStorage();
    try {
      if (await store.read(key: 'battery_asked') != null) return;
      if (!await SoraPhone.accessibilityEnabled()) return; // no background line without it
      await store.write(key: 'battery_asked', value: '1');
      await Permission.notification.request(); // "Connected to the PC" (Android 13+ asks)
      if (!await FlutterForegroundTask.isIgnoringBatteryOptimizations) {
        await FlutterForegroundTask.requestIgnoreBatteryOptimization();
      }
    } catch (_) {}
  }

  Future<void> stop() async {
    _on = false;
    await _ws?.sink.close();
    _ws = null;
  }

  Future<void> _loop() async {
    var pause = 2;
    while (_on) {
      final server = session.serverUrl, token = session.token;
      final bangla = session.language == 'bn';
      if ('$server $token $bangla' != _told) {
        _told = '$server $token $bangla';
        try {
          await SoraPhone.link(server, token, bangla: bangla);
        } catch (_) {}
      }
      if (server == null || token == null || await WakeService.running || await SoraPhone.linkActive()) {
        if (server != null && token != null) await _nudgeLink(server, token, bangla);
        await Future<void>.delayed(const Duration(seconds: 10));
        continue;
      }
      try {
        final url = server.replaceFirst(RegExp(r'^http'), 'ws').replaceAll(RegExp(r'/+$'), '');
        final ws = IOWebSocketChannel.connect(
          Uri.parse('$url/ws'),
          headers: {'Authorization': 'Bearer $token'},
          pingInterval: const Duration(seconds: 30),
        );
        await ws.ready;
        _ws = ws;
        pause = 2;
        await for (final raw in ws.stream) {
          final msg = jsonDecode(raw as String) as Map<String, dynamic>;
          switch (msg['type']) {
            case 'ping':
              ws.sink.add(jsonEncode({'type': 'pong'}));
            case 'command':
              ws.sink.add(
                jsonEncode(
                  await phoneCommandResult(
                    msg['id'] as String?,
                    msg['action'] as String? ?? '',
                    Map<String, dynamic>.from(msg['params'] as Map? ?? const {}),
                  ),
                ),
              );
            case 'device_status':
              _own.add(msg);
          }
        }
      } catch (_) {
        // server off or at a new address (the shells look for it): try again soon
      }
      _ws = null;
      if (!_on) break;
      await Future<void>.delayed(Duration(seconds: pause));
      pause = math.min(pause * 2, 30);
    }
  }
}
