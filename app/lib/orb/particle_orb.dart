import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import 'noise.dart';
import 'orb_controller.dart';

/// Sora's voice orb: 1,500 points on a sphere that breathe, ripple and scatter with the voice.
/// A port of ui/prototype/sora-orb.html ("Particles").
class ParticleOrb extends StatefulWidget {
  const ParticleOrb({super.key, required this.controller, this.scale = 0.33});

  final OrbController controller;

  /// Sphere radius as a share of the smaller side (the design's voice screen uses 0.32).
  final double scale;

  @override
  State<ParticleOrb> createState() => _ParticleOrbState();
}

class _ParticleOrbState extends State<ParticleOrb> with SingleTickerProviderStateMixin {
  late final Ticker _ticker;
  final _frame = ValueNotifier<int>(0);
  late final _OrbPainter _painter;
  Duration _last = Duration.zero;

  @override
  void initState() {
    super.initState();
    _painter = _OrbPainter(widget.controller, _frame)..scale = widget.scale;
    _ticker = createTicker(_onTick)..start();
  }

  void _onTick(Duration elapsed) {
    final dt = math.min(0.05, (elapsed - _last).inMicroseconds / 1e6);
    _last = elapsed;
    final reduce = MediaQuery.maybeOf(context)?.disableAnimations ?? false;
    _painter.advance(dt * (reduce ? 0.4 : 1.0));
    _frame.value++;
  }

  @override
  void dispose() {
    _ticker.dispose();
    _frame.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return RepaintBoundary(
      child: CustomPaint(painter: _painter, size: Size.infinite),
    );
  }
}

class _OrbPainter extends CustomPainter {
  _OrbPainter(this.c, Listenable repaint) : super(repaint: repaint) {
    for (var i = 0; i < n; i++) {
      // Fibonacci sphere: even spacing, with the ring patterns at the poles.
      final y = 1 - (i / (n - 1)) * 2;
      final rad = math.sqrt(1 - y * y);
      final th = i * math.pi * (3 - math.sqrt(5));
      base[i * 3] = math.cos(th) * rad;
      base[i * 3 + 1] = y;
      base[i * 3 + 2] = math.sin(th) * rad;
      seeds[i] = _rng.nextDouble();
    }
  }

  static const n = 1500;
  static const _depthBuckets = 6, _colorBuckets = 4;
  static final _rng = math.Random(7);

  final OrbController c;
  final base = Float32List(n * 3);
  final seeds = Float32List(n);
  final _noise = ValueNoise();
  double clock = 0, rotY = 0;
  double scale = 0.33;

  // Reused per frame: points grouped by (depth, colour) so each group is one drawRawPoints call.
  final List<Float32List> _buf = List.generate(_depthBuckets * _colorBuckets, (_) => Float32List(n * 2));
  final List<int> _len = List.filled(_depthBuckets * _colorBuckets, 0);

  void advance(double dt) {
    clock += dt;
    c.tick(dt);
    rotY += dt * (0.22 + c.swirl * 1.3);
  }

  @override
  void paint(Canvas canvas, Size size) {
    final level = c.displayLevel(clock);
    final unit = math.min(size.width, size.height);
    final shell = scale * unit;
    final cx = size.width / 2, cy = size.height / 2;
    const tilt = 0.35;
    final ct = math.cos(tilt), st = math.sin(tilt);
    final cr = math.cos(rotY), sr = math.sin(rotY);
    final scatter = level * level * 0.55; // loud moments break the sphere apart
    final pull = 1 - c.swirl * 0.12; // thinking: drawn inward
    final jitter = c.err * 0.04;

    for (var k = 0; k < _len.length; k++) {
      _len[k] = 0;
    }
    for (var i = 0; i < n; i++) {
      var x = base[i * 3], y = base[i * 3 + 1], z = base[i * 3 + 2];
      final n1 = _noise.sample(x * 2.2 + clock * 0.55, y * 2.2, z * 2.2 - clock * 0.4);
      final d =
          pull *
          (1 +
              0.04 * math.sin(clock * 1.4 + seeds[i] * 6) +
              (n1 - 0.5) * (0.08 + level * 0.7) +
              scatter * (seeds[i] - 0.3) +
              (_rng.nextDouble() - 0.5) * jitter);
      x *= d;
      y *= d;
      z *= d;
      if (c.swirl > 0.05) {
        // twist around the vertical axis while thinking
        final tw = y * c.swirl * 1.4, c2 = math.cos(tw), s2 = math.sin(tw);
        final nx = x * c2 - z * s2;
        z = x * s2 + z * c2;
        x = nx;
      }
      final rx = x * cr - z * sr;
      var rz = x * sr + z * cr;
      final ry = y * ct - rz * st;
      rz = y * st + rz * ct;
      final persp = 2.8 / (2.8 - rz);
      final depth = ((rz + 1) / 2).clamp(0.0, 0.999);
      final mix = ((y + 1) / 2).clamp(0.0, 0.999);
      final bucket = (depth * _depthBuckets).floor() * _colorBuckets + (mix * _colorBuckets).floor();
      final at = _len[bucket];
      _buf[bucket][at] = cx + rx * shell * persp;
      _buf[bucket][at + 1] = cy - ry * shell * persp;
      _len[bucket] = at + 2;
    }

    final ca = c.colorA, cb = c.colorB;
    if (c.light) {
      // On white, a soft halo gives the sphere presence; it swells with the voice.
      final r = shell * (1.25 + level * 0.25);
      canvas.drawCircle(
        Offset(cx, cy),
        r,
        Paint()
          ..shader = ui.Gradient.radial(
            Offset(cx, cy),
            r,
            [
              Color.lerp(ca, Colors.white, 0.55)!.withValues(alpha: 0.42 + level * 0.25),
              Color.lerp(cb, Colors.white, 0.7)!.withValues(alpha: 0.18),
              Colors.white.withValues(alpha: 0),
            ],
            [0.0, 0.55, 1.0],
          ),
      );
    }
    final paint = Paint()
      ..blendMode = c.light ? BlendMode.srcOver : BlendMode.plus
      ..strokeCap = c.light ? StrokeCap.round : StrokeCap.square;
    for (var db = 0; db < _depthBuckets; db++) {
      final depth = (db + 0.5) / _depthBuckets;
      final width = c.light ? (1.3 + depth * 1.7) : (1.0 + depth * 1.4);
      paint.strokeWidth = math.max(0.8, width * (0.85 + level * 0.6));
      for (var cbk = 0; cbk < _colorBuckets; cbk++) {
        final k = db * _colorBuckets + cbk;
        if (_len[k] == 0) continue;
        final tint = Color.lerp(ca, cb, (cbk + 0.5) / _colorBuckets)!;
        paint.color = tint.withValues(alpha: c.light ? 0.28 + depth * 0.66 : 0.18 + depth * 0.62);
        canvas.drawRawPoints(ui.PointMode.points, Float32List.sublistView(_buf[k], 0, _len[k]), paint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _OrbPainter oldDelegate) => false;
}
