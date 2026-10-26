import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';

import '../orb/orb_controller.dart';
import '../orb/particle_orb.dart';

/// `sora.exe --orb --port N --token T`: Sora's orb in the screen's bottom-right corner while the owner
/// talks to it hands-free ("Hey Sora" heard by the PC agent), so it is clear Sora heard even when its
/// answer takes a while. Talking in the app shows the app's own orb instead.
///
/// The PC agent starts this while "Hey Sora" is on and sends it what is happening, one JSON line at a
/// time over 127.0.0.1: {"state": "listening" | "thinking" | "speaking" | "hide", "level": 0..1}. The
/// window (runner: never focused, not in Alt+Tab, topmost) is transparent and lets clicks through; when
/// hidden it draws nothing and the orb's ticker is gone, so it costs nothing until the next wake. It ends
/// when the agent does.
Future<void> runOrbOverlay(List<String> args) async {
  String? arg(String name) {
    final i = args.indexOf(name);
    return i >= 0 && i + 1 < args.length ? args[i + 1] : null;
  }

  final port = int.tryParse(arg('--port') ?? '');
  if (port == null) exit(2);
  await windowManager.ensureInitialized();
  await windowManager.setAsFrameless();
  await windowManager.setHasShadow(false);
  await windowManager.setBackgroundColor(Colors.transparent);
  // The runner makes it a click-through tool window (off the taskbar, out of Alt+Tab, never focused):
  // window_manager's setSkipTaskbar crashes this early, and its setIgnoreMouseEvents leaves it undrawn.
  await windowManager.setSize(const Size(_side, _side));
  await windowManager.setAlignment(Alignment.bottomRight); // the work area's corner, above the taskbar's clock
  final at = await windowManager.getPosition();
  await windowManager.setPosition(at + const Offset(-10, -10));
  runApp(_OrbOverlay(port: port, token: arg('--token') ?? ''));
}

const _side = 168.0;

class _OrbOverlay extends StatefulWidget {
  const _OrbOverlay({required this.port, required this.token});

  final int port;
  final String token;

  @override
  State<_OrbOverlay> createState() => _OrbOverlayState();
}

class _OrbOverlayState extends State<_OrbOverlay> with SingleTickerProviderStateMixin {
  final _orb = OrbController();
  late final _appear = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 300),
    reverseDuration: const Duration(milliseconds: 380),
  );
  late final _curve = CurvedAnimation(parent: _appear, curve: Curves.easeOutBack, reverseCurve: Curves.easeInCubic);
  bool _shown = false; // the orb is in the tree (its ticker runs) while shown and while it goes
  Timer? _speaking; // while Sora speaks: the PC plays the voice, so its loudness is made up here

  @override
  void initState() {
    super.initState();
    _appear.addStatusListener((s) {
      if (s == AnimationStatus.dismissed && _shown) setState(() => _shown = false);
    });
    _connect();
  }

  Future<void> _connect() async {
    try {
      final socket = await Socket.connect(InternetAddress.loopbackIPv4, widget.port, timeout: const Duration(seconds: 5));
      socket.write('${jsonEncode({'token': widget.token})}\n');
      await socket.cast<List<int>>().transform(utf8.decoder).transform(const LineSplitter()).forEach(_onLine);
    } catch (_) {
      // the agent went away
    }
    exit(0); // the agent ended (or never answered): so does the orb
  }

  void _onLine(String line) {
    final Map<String, dynamic> msg;
    try {
      msg = jsonDecode(line) as Map<String, dynamic>;
    } catch (_) {
      return;
    }
    final state = msg['state'] as String?;
    final level = (msg['level'] as num?)?.toDouble();
    if (state == 'hide') {
      _speaking?.cancel();
      _orb.state = OrbState.idle;
      _appear.reverse();
      return;
    }
    final next = switch (state) {
      'thinking' => OrbState.thinking,
      'speaking' => OrbState.speaking,
      _ => OrbState.listening,
    };
    if (next != _orb.state) {
      _orb.state = next;
      _speaking?.cancel();
      if (next == OrbState.speaking) {
        final start = DateTime.now();
        _speaking = Timer.periodic(const Duration(milliseconds: 90), (_) {
          final t = DateTime.now().difference(start).inMilliseconds / 1000;
          _orb.setInput(0.35 + 0.25 * math.sin(t * 7.1).abs() + 0.15 * math.sin(t * 2.3));
        });
      } else {
        _orb.setInput(0);
      }
    }
    if (level != null) _orb.setInput(level);
    if (!_shown) setState(() => _shown = true);
    _appear.forward();
  }

  @override
  void dispose() {
    _speaking?.cancel();
    _appear.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      color: Colors.transparent,
      theme: ThemeData(scaffoldBackgroundColor: Colors.transparent, canvasColor: Colors.transparent),
      home: ColoredBox(
        color: Colors.transparent,
        child: !_shown
            ? const SizedBox.expand()
            : FadeTransition(
                opacity: _appear,
                child: ScaleTransition(
                  scale: Tween(begin: .6, end: 1.0).animate(_curve),
                  alignment: Alignment.bottomRight,
                  // A dark disc behind the light dots, so the orb reads on any wallpaper or window.
                  child: DecoratedBox(
                    decoration: const BoxDecoration(
                      shape: BoxShape.circle,
                      gradient: RadialGradient(colors: [Color(0xEE0B0B12), Color(0xCC0B0B12), Color(0x000B0B12)], stops: [0, .62, 1]),
                    ),
                    child: ParticleOrb(controller: _orb, scale: .3),
                  ),
                ),
              ),
      ),
    );
  }
}
