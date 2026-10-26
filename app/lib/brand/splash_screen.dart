import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme.dart';
import '../widgets/sora_widgets.dart';
import 'sora_logo.dart';

/// Opening animation from the design (`@keyframes sMark` / `sWord`, 2.9s): the mark pops in, hops
/// 72px, lands with a squash, then rolls 60px left through one full turn while "Sora" slides out
/// from behind it. Hands over 0.4s after the animation ends.
class SoraSplash extends StatefulWidget {
  const SoraSplash({super.key, required this.onDone});

  final VoidCallback onDone;

  @override
  State<SoraSplash> createState() => _SoraSplashState();
}

class _SoraSplashState extends State<SoraSplash> with SingleTickerProviderStateMixin {
  static const _ease = Cubic(.25, .1, .25, 1); // CSS `ease`
  static const _rise = Cubic(.2, .7, .3, 1);
  static const _fall = Cubic(.6, 0, .9, .4);
  static const _word = Cubic(.3, .7, .2, 1);

  late final AnimationController _c;
  Timer? _hold;
  bool _started = false;

  @override
  void initState() {
    super.initState();
    _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 2900))
      ..addStatusListener((s) {
        if (s == AnimationStatus.completed) _hold = Timer(const Duration(milliseconds: 400), widget.onDone);
      });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_started) return;
    _started = true;
    if (MediaQuery.maybeOf(context)?.disableAnimations ?? false) _c.value = 1;
    _c.forward();
  }

  @override
  void dispose() {
    _hold?.cancel();
    _c.dispose();
    super.dispose();
  }

  /// Progress of `t` between keyframes `a` and `b`, shaped by `curve`.
  static double seg(double t, double a, double b, [Curve curve = _ease]) =>
      curve.transform(((t - a) / (b - a)).clamp(0.0, 1.0));

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final wordStyle = SoraType.ui(46, weight: FontWeight.w500, color: p.ink, height: 54 / 46)
        .copyWith(letterSpacing: 46 * -.02);

    return Material(
      type: MaterialType.transparency,
      child: SoraBackground(
        child: AnimatedBuilder(
          animation: _c,
          builder: (context, _) {
            final t = _c.value;
            // sMark 0→14%: fade + scale .55→1
            final appear = seg(t, 0, .14);
            final scale = .55 + .45 * appear;
            // 22→36%: hop up 72px; 36→48%: fall back and squash to (1.14, .84); 48→55%: recover
            final dy = -72 * seg(t, .22, .36, _rise) + 72 * seg(t, .36, .48, _fall);
            final squash = seg(t, .36, .48, _fall) - seg(t, .48, .55);
            final sx = 1 + .14 * squash, sy = 1 - .16 * squash;
            // 55→82%: roll left 60px, one full counter-clockwise turn
            final roll = seg(t, .55, .82);
            final dx = -60 * roll;
            // sWord 55→82%: slide out from behind the mark
            final word = seg(t, .55, .82, _word);

            return Center(
              child: SizedBox(
                width: 0,
                height: 64,
                child: Stack(
                  clipBehavior: Clip.none,
                  children: [
                    Positioned(
                      left: -14,
                      top: 5,
                      child: Opacity(
                        opacity: word,
                        child: Transform.translate(
                          offset: Offset(-56 * (1 - word), 0),
                          child: Text('Sora', maxLines: 1, softWrap: false, style: wordStyle),
                        ),
                      ),
                    ),
                    Positioned(
                      left: -32,
                      top: 0,
                      child: Opacity(
                        opacity: appear,
                        child: Transform.translate(
                          offset: Offset(dx, dy),
                          child: Transform(
                            alignment: Alignment.center,
                            transform: Matrix4.diagonal3Values(scale * sx, scale * sy, 1),
                            child: Transform.rotate(angle: -2 * math.pi * roll, child: const SoraMark(size: 64)),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}
