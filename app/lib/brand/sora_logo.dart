import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme.dart';

/// The Sora mark from the logo handoff (`assets/brand/sora-mark-{dark,light}.svg`): two concentric
/// half rings rising from a half disc, like a signal. Drawn in its 120×120 viewBox on a disc with a
/// hairline ring (the in-app avatar). Dark: black disc, white rings, cyan core. Light: white disc,
/// ink rings, indigo core.
class SoraMark extends StatelessWidget {
  const SoraMark({super.key, this.size = 30, this.dark, this.disc = true});

  final double size;

  /// Force a variant; defaults to the current theme.
  final bool? dark;

  /// Draw the round background (avatar); false = the bare mark on whatever is behind it.
  final bool disc;

  @override
  Widget build(BuildContext context) {
    final isDark = dark ?? SoraPalette.of(context).dark;
    return CustomPaint(size: Size.square(size), painter: SoraMarkPainter(dark: isDark, disc: disc));
  }
}

class SoraMarkPainter extends CustomPainter {
  SoraMarkPainter({required this.dark, this.disc = true});

  final bool dark, disc;

  static const ink = Color(0xFF10131B), cyan = Color(0xFF5CC8FF), indigo = Color(0xFF4B4FE0);

  @override
  void paint(Canvas canvas, Size size) {
    final k = size.shortestSide / 120;
    canvas.save();
    canvas.scale(k);
    if (disc) {
      canvas.drawCircle(const Offset(60, 60), 59, Paint()..color = dark ? Colors.black : Colors.white);
      canvas.drawCircle(
        const Offset(60, 60),
        59,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2
          ..color = dark ? const Color(0xFF2A2F3A) : const Color(0xFFE2E5EC),
      );
    }
    // <g transform="translate(60 60) scale(.72) translate(-60 -67)">; a bit larger on the round avatar
    // so it still reads at 16px in the title bar.
    canvas.translate(60, 60);
    canvas.scale(disc ? .9 : .72);
    canvas.translate(-60, -67);
    final fg = dark ? Colors.white : ink;
    Paint ring(double opacity) => Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 7
      ..strokeCap = StrokeCap.round
      ..color = fg.withValues(alpha: opacity);
    const centre = Offset(60, 86);
    // <path d="M22 86A38 38 0 0 1 98 86">, <path d="M38 86A22 22 0 0 1 82 86" opacity=".55">
    canvas.drawArc(Rect.fromCircle(center: centre, radius: 38), math.pi, math.pi, false, ring(1));
    canvas.drawArc(Rect.fromCircle(center: centre, radius: 22), math.pi, math.pi, false, ring(.55));
    // <path d="M50 86A10 10 0 0 1 70 86Z">
    canvas.drawArc(Rect.fromCircle(center: centre, radius: 10), math.pi, math.pi, true, Paint()..color = dark ? cyan : indigo);
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant SoraMarkPainter old) => old.dark != dark || old.disc != disc;
}
