import 'dart:ui' as ui;

import 'package:flutter/foundation.dart' show TargetPlatform, defaultTargetPlatform;
import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../brand/sora_logo.dart';
import '../shell/layout.dart';
import '../theme.dart';

/// Screen ground: the "graphite" preset from the design (`BG.graphite`) — a soft white glow from
/// above the top edge over a vertical charcoal (dark) or pale grey (light) gradient.
class SoraBackground extends StatelessWidget {
  const SoraBackground({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    // The desktop window paints one background behind everything (see DesktopFrame).
    if (SoraLayout.isDesktop(context)) return child;
    return paint(context, child);
  }

  /// The background of a window [size] big, drawn straight on [canvas] ([shade]: 1 dark, 0 light).
  static void paintWindow(Canvas canvas, Size size, double shade) => _GraphitePainter(shade).paint(canvas, size);

  /// Paints the background regardless of layout (the desktop frame itself).
  static Widget paint(BuildContext context, Widget child) => CustomPaint(
    painter: _GraphitePainter(SoraPalette.of(context).shade),
    child: RepaintBoundary(child: child),
  );
}

class _GraphitePainter extends CustomPainter {
  _GraphitePainter(this.shade);

  /// 1 dark, 0 light (in between while the theme changes).
  final double shade;

  static const _darkStops = [Color(0xFF15161A), Color(0xFF0B0B0D), Color(0xFF070708)];
  static const _lightStops = [Color(0xFFF6F7F9), Color(0xFFECEEF1), Color(0xFFE3E6EA)];

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    Color mix(Color light, Color dark) => Color.lerp(light, dark, shade)!;
    canvas.drawRect(
      rect,
      Paint()
        ..shader = LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [for (var i = 0; i < 3; i++) mix(_lightStops[i], _darkStops[i])],
          stops: const [0, .55, 1],
        ).createShader(rect),
    );
    _radial(canvas, size, rx: 1.2, ry: .6, cx: .5, cy: -.12, color: mix(const Color(0xFFFFFFFF), const Color(0x1AFFFFFF)), stop: .58);
    if (shade > 0) {
      _radial(canvas, size, rx: .7, ry: .4, cx: 1, cy: 1, color: const Color(0x0AFFFFFF).withValues(alpha: .04 * shade), stop: .7);
    }
  }

  /// CSS `radial-gradient(RX% RY% at CX% CY%, color, transparent STOP%)`: an ellipse whose radii are
  /// fractions of the box width/height. Fades to the same colour at zero alpha, as CSS does.
  static void _radial(
    Canvas canvas,
    Size s, {
    required double rx,
    required double ry,
    required double cx,
    required double cy,
    required Color color,
    required double stop,
  }) {
    final c = Offset(s.width * cx, s.height * cy);
    final sx = s.width * rx, sy = s.height * ry;
    canvas.save();
    canvas.translate(c.dx, c.dy);
    canvas.scale(sx, sy);
    canvas.drawRect(
      Rect.fromLTRB(-c.dx / sx, -c.dy / sy, (s.width - c.dx) / sx, (s.height - c.dy) / sy),
      Paint()
        ..shader = RadialGradient(
          colors: [color, color.withAlpha(0)],
          stops: [0, stop],
        ).createShader(Rect.fromCircle(center: Offset.zero, radius: 1)),
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _GraphitePainter old) => old.shade != shade;
}

/// The design's `--blur` / `--blurStrong`: backdrop blur plus saturate and a touch of brightness.
/// [amount] below 1 is part of the way there (0: no change), for glass that is appearing.
ui.ImageFilter soraGlassFilter(SoraPalette p, {bool strong = false, double amount = 1}) {
  final phone = defaultTargetPlatform == TargetPlatform.android;
  final s = 1 + ((strong ? 2.2 : 2.0) - 1) * amount, b = 1 + (p.glassBrightness - 1) * amount;
  final sigma = (strong ? (phone ? 22.0 : 34.0) : (phone ? 16.0 : 20.0)) * amount;
  // CSS saturate() matrix, each row scaled by brightness().
  final m = <double>[
    (.213 + .787 * s) * b,
    (.715 - .715 * s) * b,
    (.072 - .072 * s) * b,
    0,
    0,
    (.213 - .213 * s) * b,
    (.715 + .285 * s) * b,
    (.072 - .072 * s) * b,
    0,
    0,
    (.213 - .213 * s) * b,
    (.715 - .715 * s) * b,
    (.072 + .928 * s) * b,
    0,
    0,
    0,
    0,
    0,
    1,
    0,
  ];
  return ui.ImageFilter.compose(
    outer: ColorFilter.matrix(m),
    inner: ui.ImageFilter.blur(sigmaX: sigma, sigmaY: sigma, tileMode: TileMode.clamp),
  );
}

/// Crystal glass: a low-alpha fill, a 1px `--line` border and the `--hi` highlight edge. [fill]
/// defaults to `--surf`; panels and sheets pass `--glass2` / `--sheet` with [strong] blur. [sheen]
/// adds the 70px top highlight used on approval cards.
///
/// The backdrop is blurred only for [strong] glass or with [blur] true: glass that floats over
/// content (sheets, menus, the composer). Cards on the plain background don't blur — a blurred
/// gradient looks the same, a backdrop blur costs a full extra pass on phones, and inside a fading
/// page it samples nothing and goes dark. Blurred glass that comes and goes (a dialog) passes its
/// route's animation as [reveal] instead of being faded.
class Glass extends StatelessWidget {
  const Glass({
    super.key,
    required this.child,
    this.radius = 16,
    this.fill,
    this.strong = false,
    this.blur,
    this.border = true,
    this.borderColor,
    this.shadow = false,
    this.sheen = false,
    this.padding,
    this.width,
    this.height,
    this.reveal,
  });

  final Widget child;
  final double radius;
  final Color? fill, borderColor;
  final bool strong, border, shadow, sheen;
  final bool? blur;
  final EdgeInsetsGeometry? padding;
  final double? width, height;

  /// 0 → 1 while the glass appears (1 → 0 while it goes): the blur, fill and edges grow with it and
  /// only the content fades, so the blur always samples the real backdrop and nothing flashes.
  final Animation<double>? reveal;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final content = Padding(padding: padding ?? EdgeInsets.zero, child: child);
    final reveal = this.reveal;
    if (reveal == null) return _frame(p, content, 1);
    return AnimatedBuilder(
      animation: reveal,
      child: FadeTransition(opacity: reveal, child: content),
      builder: (context, faded) => _frame(p, faded!, reveal.value.clamp(0.0, 1.0)),
    );
  }

  /// The glass around [content], [t] of the way in.
  Widget _frame(SoraPalette p, Widget content, double t) {
    Color a(Color c) => t >= 1 ? c : c.withValues(alpha: c.a * t);
    final br = BorderRadius.circular(radius);
    Widget body = DecoratedBox(
      decoration: BoxDecoration(
        color: a(fill ?? p.surf),
        borderRadius: br,
        border: border ? Border.all(color: a(borderColor ?? p.line)) : null,
      ),
      position: DecorationPosition.background,
      child: CustomPaint(
        foregroundPainter: _HighlightPainter(p.hi, radius, border ? 1 : 0, t),
        child: Stack(
          // Pass the box's own constraints through, so a fixed-height glass still centres its row.
          fit: StackFit.passthrough,
          children: [
            if (sheen)
              Positioned(
                left: 0,
                right: 0,
                top: 0,
                height: 70,
                child: IgnorePointer(
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                        colors: [a(p.sheen), p.sheen.withAlpha(0)],
                      ),
                    ),
                  ),
                ),
              ),
            content,
          ],
        ),
      ),
    );
    final blurred = blur ?? strong;
    if (blurred) {
      body = BackdropFilter(
        filter: soraGlassFilter(p, strong: strong, amount: t),
        child: body,
      );
    }
    // The blur (and the sheen) need the rounded clip; a plain card's box is already rounded.
    if (blurred || sheen) body = ClipRRect(borderRadius: br, child: body);
    final shadows = [
      for (final s in [if (shadow) ...p.shadow, if (p.hi.outer != null) p.hi.outer!])
        t >= 1 ? s : BoxShadow(color: a(s.color), offset: s.offset, blurRadius: s.blurRadius, spreadRadius: s.spreadRadius),
    ];
    if (shadows.isNotEmpty) {
      body = DecoratedBox(
        decoration: BoxDecoration(borderRadius: br, boxShadow: shadows),
        child: body,
      );
    }
    return SizedBox(width: width, height: height, child: body);
  }
}

/// Paints `--hi` inside the border: a 1px light line along the top edge, a fainter one along the
/// bottom, and a hairline ring.
class _HighlightPainter extends CustomPainter {
  _HighlightPainter(this.hi, this.radius, this.borderWidth, this.opacity);

  final GlassHighlight hi;
  final double radius, borderWidth, opacity;

  @override
  void paint(Canvas canvas, Size size) {
    final outer = RRect.fromRectAndRadius(Offset.zero & size, Radius.circular(radius));
    final inner = outer.deflate(borderWidth);
    // The sliver of [inner] not covered by itself moved [dy]: an even-odd fill of both, clipped to
    // [inner] (cheaper than Path.combine on every paint).
    Color o(Color c) => opacity >= 1 ? c : c.withValues(alpha: c.a * opacity);
    void edge(Color c, double dy) {
      c = o(c);
      if (c.a == 0) return;
      canvas.save();
      canvas.clipRRect(inner);
      canvas.drawPath(
        Path()
          ..fillType = PathFillType.evenOdd
          ..addRRect(inner)
          ..addRRect(inner.shift(Offset(0, dy))),
        Paint()..color = c,
      );
      canvas.restore();
    }

    edge(hi.top, 1);
    edge(hi.bottom, -1);
    canvas.drawRRect(
      inner.deflate(hi.ringWidth / 2),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = hi.ringWidth
        ..color = o(hi.ring),
    );
  }

  @override
  bool shouldRepaint(covariant _HighlightPainter old) =>
      old.hi != hi || old.radius != radius || old.borderWidth != borderWidth || old.opacity != opacity;
}

/// Tap target with a light press response (scale + dim) instead of a Material ripple, which
/// would fight the glass.
class Pressable extends StatefulWidget {
  const Pressable({super.key, required this.child, this.onTap, this.onLongPress, this.semanticLabel});

  final Widget child;
  final VoidCallback? onTap, onLongPress;
  final String? semanticLabel;

  @override
  State<Pressable> createState() => _PressableState();
}

class _PressableState extends State<Pressable> {
  bool _down = false;

  void _set(bool v) {
    if (_down != v) setState(() => _down = v);
  }

  @override
  Widget build(BuildContext context) {
    final enabled = widget.onTap != null || widget.onLongPress != null;
    return Semantics(
      button: true,
      enabled: enabled,
      label: widget.semanticLabel,
      // A button's label isn't text to select (the chat is a SelectionArea): the pointer is a hand over it,
      // not the text cursor, and a drag across it doesn't select it.
      child: SelectionContainer.disabled(
        child: MouseRegion(
          cursor: enabled ? SystemMouseCursors.click : MouseCursor.defer,
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: widget.onTap,
            onLongPress: widget.onLongPress,
            onTapDown: enabled ? (_) => _set(true) : null,
            onTapUp: enabled ? (_) => _set(false) : null,
            onTapCancel: enabled ? () => _set(false) : null,
            child: AnimatedScale(
              scale: _down ? .96 : 1,
              duration: const Duration(milliseconds: 120),
              curve: Curves.easeOut,
              child: AnimatedOpacity(opacity: _down ? .82 : 1, duration: const Duration(milliseconds: 120), child: widget.child),
            ),
          ),
        ),
      ),
    );
  }
}

/// Material Symbols Rounded icon. [fill] is the FILL axis (1 for active/solid icons).
class LIcon extends StatelessWidget {
  const LIcon(this.icon, {super.key, this.size = 20, this.color, this.fill = false, this.weight = 400});

  final IconData icon;
  final double size;
  final Color? color;
  final bool fill;
  final double weight;

  @override
  Widget build(BuildContext context) =>
      Icon(icon, size: size, color: color, fill: fill ? 1 : 0, weight: weight, opticalSize: size.clamp(20, 48).toDouble());
}

/// Round glass icon button (header menu / export / new chat, 42–44px; voice dock 54px).
/// [badge] shows the red unread count on the top-right corner.
class GlassIconButton extends StatelessWidget {
  const GlassIconButton({
    super.key,
    required this.icon,
    required this.tooltip,
    this.onTap,
    this.size = 42,
    this.iconSize,
    this.badge = 0,
    this.fill = false,
  });

  final IconData icon;
  final String tooltip;
  final VoidCallback? onTap;
  final double size;
  final double? iconSize;
  final int badge;
  final bool fill;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Tooltip(
      message: tooltip,
      child: Pressable(
        onTap: onTap,
        semanticLabel: tooltip,
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            Glass(
              width: size,
              height: size,
              radius: size / 2,
              child: Center(
                child: LIcon(icon, size: iconSize ?? (size * .5).roundToDouble(), color: onTap == null ? p.faint : p.ink, fill: fill),
              ),
            ),
            if (badge > 0) Positioned(top: -3, right: -3, child: CountBadge(count: badge)),
          ],
        ),
      ),
    );
  }
}

/// Red count bubble with a ring in the page colour (menu button, nav items).
class CountBadge extends StatelessWidget {
  const CountBadge({super.key, required this.count});

  final int count;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Container(
      constraints: const BoxConstraints(minWidth: 18),
      height: 18,
      padding: const EdgeInsets.symmetric(horizontal: 4),
      decoration: BoxDecoration(
        color: p.err,
        borderRadius: BorderRadius.circular(9),
        border: Border.all(color: p.bg, width: 2),
      ),
      alignment: Alignment.center,
      child: Text(
        soraNum(context, count > 99 ? 99 : count),
        style: SoraType.ui(10.5, weight: FontWeight.w600, color: Colors.white, height: 1),
      ),
    );
  }
}

/// Filled ink button — the design's primary action (Connect, Yes). Inverts with the theme:
/// white on dark, near-black on light.
class InkButton extends StatelessWidget {
  const InkButton({
    super.key,
    required this.label,
    this.onTap,
    this.height = 52,
    this.radius = 16,
    this.fontSize = 16,
    this.leading,
    this.trailing,
    this.busy = false,
    this.disabled = false,
    this.expand = true,
  });

  final String label;
  final VoidCallback? onTap;
  final double height, radius, fontSize;
  final IconData? leading, trailing;
  final bool busy, disabled, expand;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final fg = p.bg;
    return Opacity(
      opacity: disabled ? .45 : 1,
      child: Pressable(
        onTap: disabled || busy ? null : onTap,
        child: Container(
          height: height,
          width: expand ? double.infinity : null,
          padding: const EdgeInsets.symmetric(horizontal: 18),
          decoration: BoxDecoration(
            color: p.ink,
            borderRadius: BorderRadius.circular(radius),
            boxShadow: [
              BoxShadow(color: const Color(0x40000000), blurRadius: height > 48 ? 24 : 20, offset: Offset(0, height > 48 ? 8 : 6)),
            ],
          ),
          child: Row(
            mainAxisSize: expand ? MainAxisSize.max : MainAxisSize.min,
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              if (busy) ...[Spinner(size: 20, color: fg), const SizedBox(width: 10)],
              if (!busy && leading != null) ...[LIcon(leading!, size: 20, color: fg), const SizedBox(width: 10)],
              Flexible(
                child: Text(
                  label,
                  overflow: TextOverflow.ellipsis,
                  style: SoraType.ui(fontSize, weight: FontWeight.w600, color: fg),
                ),
              ),
              if (!busy && trailing != null) ...[const SizedBox(width: 10), LIcon(trailing!, size: 20, color: fg)],
            ],
          ),
        ),
      ),
    );
  }
}

/// Glass button with ink text — the secondary action next to [InkButton] (No, Cancel).
class GlassButton extends StatelessWidget {
  const GlassButton({
    super.key,
    required this.label,
    this.onTap,
    this.height = 46,
    this.radius = 15,
    this.fontSize = 15,
    this.icon,
    this.color,
  });

  final String label;
  final VoidCallback? onTap;
  final double height, radius, fontSize;
  final IconData? icon;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final fg = color ?? p.ink;
    return Pressable(
      onTap: onTap,
      child: Glass(
        height: height,
        radius: radius,
        padding: const EdgeInsets.symmetric(horizontal: 14),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (icon != null) ...[LIcon(icon!, size: 19, color: fg), const SizedBox(width: 8)],
            Flexible(
              child: Text(
                label,
                overflow: TextOverflow.ellipsis,
                style: SoraType.ui(fontSize, weight: FontWeight.w500, color: fg),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// `progress_activity` spinning at 1s per turn, like the design's loaders.
class Spinner extends StatefulWidget {
  const Spinner({super.key, this.size = 16, this.color, this.period = const Duration(seconds: 1)});

  final double size;
  final Color? color;
  final Duration period;

  @override
  State<Spinner> createState() => _SpinnerState();
}

class _SpinnerState extends State<Spinner> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: widget.period)..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => RotationTransition(
    turns: _c,
    child: LIcon(Symbols.progress_activity_rounded, size: widget.size, color: widget.color ?? SoraPalette.of(context).acc),
  );
}

/// Segmented choice. The default is the in-card style (`--surf2` track, `--segOn` thumb, 34px);
/// [pill] is the small floating style used for the EN / বাং switch (glass track, ink thumb, 28px).
class SoraSegmented<T> extends StatelessWidget {
  const SoraSegmented({
    super.key,
    required this.options,
    required this.value,
    required this.onChanged,
    this.pill = false,
    this.bare = false,
  });

  final List<(T, String)> options;
  final T value;
  final ValueChanged<T> onChanged;
  final bool pill;

  /// Just the segments, for a caller that draws its own track (the menu's glass theme switch).
  final bool bare;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    Widget item((T, String) o) {
      final on = o.$1 == value;
      final label = Text(
        o.$2,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: pill
            ? SoraType.ui(12.5, weight: FontWeight.w500, color: on ? p.bg : p.ink)
            : SoraType.ui(13.5, weight: on ? FontWeight.w600 : FontWeight.w500, color: on ? p.ink : p.dim),
      );
      final box = AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        height: pill ? 28 : 34,
        padding: EdgeInsets.symmetric(horizontal: pill ? 11 : 8),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: on ? (pill ? p.ink : p.segOn) : p.segOn.withAlpha(0),
          borderRadius: BorderRadius.circular(pill ? 14 : 10),
          boxShadow: on && !pill ? const [BoxShadow(color: Color(0x24000000), blurRadius: 3, offset: Offset(0, 1))] : null,
        ),
        child: label,
      );
      final tap = GestureDetector(behavior: HitTestBehavior.opaque, onTap: () => onChanged(o.$1), child: box);
      return pill ? tap : Expanded(child: tap);
    }

    final row = Row(mainAxisSize: pill ? MainAxisSize.min : MainAxisSize.max, children: options.map(item).toList());
    if (pill) {
      return Glass(radius: 999, padding: const EdgeInsets.all(3), child: row);
    }
    if (bare) return row;
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(color: p.surf2, borderRadius: BorderRadius.circular(13)),
      child: row,
    );
  }
}

/// On/off switch: 46×28 track, 22px knob (accent when on).
class SoraSwitch extends StatelessWidget {
  const SoraSwitch({super.key, required this.value, required this.onChanged});

  final bool value;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Semantics(
      toggled: value,
      child: GestureDetector(
        onTap: onChanged == null ? null : () => onChanged!(!value),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          width: 46,
          height: 28,
          padding: const EdgeInsets.all(3),
          decoration: BoxDecoration(color: value ? p.acc : p.surf2, borderRadius: BorderRadius.circular(14)),
          child: AnimatedAlign(
            duration: const Duration(milliseconds: 200),
            curve: Curves.easeOut,
            alignment: value ? Alignment.centerRight : Alignment.centerLeft,
            child: Container(
              width: 22,
              height: 22,
              decoration: BoxDecoration(color: value ? p.accInk : p.faint, shape: BoxShape.circle),
            ),
          ),
        ),
      ),
    );
  }
}

/// Filter chip: 34px pill, accent outline + tint when selected.
class SoraChip extends StatelessWidget {
  const SoraChip({super.key, required this.label, this.selected = false, this.onTap, this.icon});

  final String label;
  final bool selected;
  final VoidCallback? onTap;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final fg = selected ? p.acc : p.ink;
    return Pressable(
      onTap: onTap,
      child: Glass(
        height: 34,
        radius: 17,
        fill: selected ? p.accSoft : p.surf,
        borderColor: selected ? p.acc : p.line,
        padding: const EdgeInsets.symmetric(horizontal: 14),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[LIcon(icon!, size: 16, color: fg), const SizedBox(width: 6)],
            Text(
              label,
              style: SoraType.ui(13.5, weight: FontWeight.w500, color: fg, height: 1),
            ),
          ],
        ),
      ),
    );
  }
}

/// Small uppercase JetBrains Mono section label (`CONNECT VIA`, `TRY ASKING`, …).
class MonoLabel extends StatelessWidget {
  const MonoLabel(this.text, {super.key, this.size = 10.5, this.color, this.weight = FontWeight.w600, this.spacing = .12});

  final String text;
  final double size, spacing;
  final Color? color;
  final FontWeight weight;

  @override
  Widget build(BuildContext context) => Text(
    text.toUpperCase(),
    maxLines: 1,
    overflow: TextOverflow.ellipsis,
    style: SoraType.mono(size, weight: weight, spacing: spacing, color: color ?? SoraPalette.of(context).dim),
  );
}

/// Tinted notice row: error (`--errSoft` / `--err`) by default, or any tint/colour pair.
class NoticeRow extends StatelessWidget {
  const NoticeRow({
    super.key,
    required this.text,
    this.icon = Symbols.error_rounded,
    this.tint,
    this.color,
    this.radius = 12,
    this.fontSize = 13.5,
  });

  final String text;
  final IconData icon;
  final Color? tint, color;
  final double radius, fontSize;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final fg = color ?? p.err;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(color: tint ?? p.errSoft, borderRadius: BorderRadius.circular(radius)),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 1),
            child: LIcon(icon, size: 18, color: fg),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(text, style: SoraType.ui(fontSize, color: fg, height: 1.45)),
          ),
        ],
      ),
    );
  }
}

/// Numbers in the UI language: Bangla digits when the app is in Bangla.
String soraNum(BuildContext context, num n) {
  final s = n.toString();
  if (Localizations.maybeLocaleOf(context)?.languageCode != 'bn') return s;
  const bn = '০১২৩৪৫৬৭৮৯';
  return s.replaceAllMapped(RegExp('[0-9]'), (m) => bn[int.parse(m[0]!)]);
}

// ---------------------------------------------------------------------------------------------
// Older helpers kept so screens not yet rebuilt on the new design still compile; they now draw in
// the new glass style.

/// Circular glass button (old name for [GlassIconButton]).
class RoundButton extends StatelessWidget {
  const RoundButton({super.key, required this.icon, required this.tooltip, this.onTap, this.size = 44});

  final IconData icon;
  final String tooltip;
  final VoidCallback? onTap;
  final double size;

  @override
  Widget build(BuildContext context) =>
      GlassIconButton(icon: icon, tooltip: tooltip, onTap: onTap, size: size, iconSize: (size * .48).roundToDouble());
}

/// Screen header: round button, centred title, round button.
class SoraHeader extends StatelessWidget {
  const SoraHeader({super.key, required this.title, this.leading, this.trailing});

  final String title;
  final Widget? leading, trailing;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 6, 14, 4),
      child: Row(
        children: [
          SizedBox(width: 44, child: leading),
          Expanded(
            child: Text(
              title,
              textAlign: TextAlign.center,
              style: SoraType.ui(17, weight: FontWeight.w600, color: p.ink),
            ),
          ),
          SizedBox(width: 44, child: trailing),
        ],
      ),
    );
  }
}

/// Flat card decoration without backdrop blur (cheap, for long lists).
BoxDecoration soraCard(SoraPalette p, {double radius = 16, Color? border}) => BoxDecoration(
  color: p.surf,
  borderRadius: BorderRadius.circular(radius),
  border: Border.all(color: border ?? p.line),
  boxShadow: [if (p.hi.outer != null) p.hi.outer!],
);

/// Sora in the chat, menu and sign-in: the round L-monogram mark.
class SoraAvatar extends StatelessWidget {
  const SoraAvatar({super.key, this.size = 30});

  final double size;

  @override
  Widget build(BuildContext context) => SoraMark(size: size);
}
