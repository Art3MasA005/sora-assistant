import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';

import '../theme.dart';
import '../widgets/sora_widgets.dart';

/// Builds [builder] with whether the mouse is over it (desktop hover states from the design's
/// `style-hover`). Clicks go to [onTap] with a pointer cursor.
class Hover extends StatefulWidget {
  const Hover({super.key, required this.builder, this.onTap, this.tooltip});

  final Widget Function(BuildContext context, bool hover) builder;
  final VoidCallback? onTap;
  final String? tooltip;

  @override
  State<Hover> createState() => _HoverState();
}

class _HoverState extends State<Hover> {
  bool _hover = false;

  @override
  Widget build(BuildContext context) {
    Widget child = MouseRegion(
      cursor: widget.onTap == null ? MouseCursor.defer : SystemMouseCursors.click,
      onEnter: (_) => setState(() => _hover = true),
      onExit: (_) => setState(() => _hover = false),
      child: GestureDetector(behavior: HitTestBehavior.opaque, onTap: widget.onTap, child: widget.builder(context, _hover)),
    );
    if (widget.tooltip != null) {
      child = Tooltip(message: widget.tooltip!, waitDuration: const Duration(milliseconds: 500), child: child);
    }
    return Semantics(button: widget.onTap != null, label: widget.tooltip, child: child);
  }
}

/// The 32px square button that hides or shows a sidebar (`left_panel_close`, `right_panel_open`…):
/// a faint white glass square with an inset top highlight.
class PanelToggle extends StatelessWidget {
  const PanelToggle({super.key, required this.icon, required this.tooltip, required this.onTap});

  final IconData icon;
  final String tooltip;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Hover(
      tooltip: tooltip,
      onTap: onTap,
      builder: (_, hover) => AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        width: 32,
        height: 32,
        decoration: BoxDecoration(
          color: hover ? p.surf2 : (p.dark ? const Color(0x0FFFFFFF) : p.surf),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: p.dark ? const Color(0x24FFFFFF) : p.line),
        ),
        alignment: Alignment.center,
        child: LIcon(icon, size: 19, color: hover ? p.ink : p.dim),
      ),
    );
  }
}

/// Red count pill used in the sidebar and panel rails (20px, or 16px on the rail icons).
class PillBadge extends StatelessWidget {
  const PillBadge({super.key, required this.count, this.small = false});

  final int count;
  final bool small;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final h = small ? 16.0 : 20.0;
    return Container(
      constraints: BoxConstraints(minWidth: h),
      height: h,
      padding: EdgeInsets.symmetric(horizontal: small ? 4 : 6),
      decoration: BoxDecoration(color: p.err, borderRadius: BorderRadius.circular(h / 2)),
      alignment: Alignment.center,
      child: Text(
        soraNum(context, count > 99 ? 99 : count),
        style: SoraType.ui(small ? 10 : 11, weight: FontWeight.w600, color: Colors.white, height: 1),
      ),
    );
  }
}

/// A rounded rectangle with a dashed `--line` border (the panel's "Nothing is waiting" box).
class DashedBox extends StatelessWidget {
  const DashedBox({
    super.key,
    required this.child,
    this.radius = 14,
    this.padding = const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
  });

  final Widget child;
  final double radius;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) => CustomPaint(
    painter: _DashedPainter(SoraPalette.of(context).line, radius),
    child: Padding(padding: padding, child: child),
  );
}

/// A Details-panel list that shows its first [visible] children and scrolls inside itself for the
/// rest, so one busy section (clipboard, notifications…) doesn't push the others off the panel.
/// Newest first: the top is what just came; scroll down for older ones. One child per item (put the
/// gap between items inside it), since the cut is made after the [visible]th child.
class ScrollBox extends StatefulWidget {
  const ScrollBox({super.key, required this.children, this.visible = 3});

  final List<Widget> children;
  final int visible;

  @override
  State<ScrollBox> createState() => _ScrollBoxState();
}

class _ScrollBoxState extends State<ScrollBox> {
  final _scroll = ScrollController();
  final _column = GlobalKey();

  /// The first [ScrollBox.visible] children's height; null until they're laid out once.
  double? _height;

  bool get _scrolls => widget.children.length > widget.visible;

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  // Items differ in height (a screenshot is taller than a line of text), so the cut is measured
  // after layout rather than fixed; it rebuilds only when it moved.
  void _measure(_) {
    if (!mounted) return;
    final flex = _column.currentContext?.findRenderObject();
    if (flex is! RenderFlex) return;
    var h = 0.0;
    var n = 0;
    flex.visitChildren((child) {
      if (n++ < widget.visible && child is RenderBox && child.hasSize) h += child.size.height;
    });
    if (h != _height) setState(() => _height = h);
  }

  @override
  Widget build(BuildContext context) {
    final column = Column(key: _column, crossAxisAlignment: CrossAxisAlignment.stretch, children: widget.children);
    if (!_scrolls) return column;
    WidgetsBinding.instance.addPostFrameCallback(_measure);
    return SizedBox(
      // before the first measure: nothing rather than the whole list for a frame
      height: _height ?? 0,
      child: Scrollbar(
        controller: _scroll,
        child: SingleChildScrollView(
          controller: _scroll,
          // room for the scrollbar, so it doesn't sit on the cards
          padding: const EdgeInsets.only(right: 8),
          child: column,
        ),
      ),
    );
  }
}

class _DashedPainter extends CustomPainter {
  _DashedPainter(this.color, this.radius);

  final Color color;
  final double radius;

  @override
  void paint(Canvas canvas, Size size) {
    final path = Path()..addRRect(RRect.fromRectAndRadius((Offset.zero & size).deflate(.5), Radius.circular(radius)));
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1;
    for (final metric in path.computeMetrics()) {
      for (var d = 0.0; d < metric.length; d += 7) {
        canvas.drawPath(metric.extractPath(d, d + 4), paint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _DashedPainter old) => old.color != color || old.radius != radius;
}

/// A side column that folds between its [full] width (the sidebar, the Details panel) and its
/// [mini] rail: the width itself animates, so the middle column grows and shrinks smoothly, while
/// each version keeps its own width (no text reflowing as it goes) — the panel is cut off at the
/// moving edge like a drawer and the rail fades in over it. [atLeft]: anchored to the left edge.
class FoldingPanel extends StatefulWidget {
  const FoldingPanel({
    super.key,
    required this.folded,
    required this.full,
    required this.mini,
    required this.fullWidth,
    required this.miniWidth,
    this.atLeft = true,
  });

  final bool folded, atLeft;
  final Widget full, mini;
  final double fullWidth, miniWidth;

  @override
  State<FoldingPanel> createState() => _FoldingPanelState();
}

class _FoldingPanelState extends State<FoldingPanel> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 300), value: widget.folded ? 1 : 0);
  late final _t = CurvedAnimation(parent: _c, curve: Curves.easeInOutCubic);
  late final _panelFade = ReverseAnimation(
    CurvedAnimation(
      parent: _c,
      curve: const Interval(0, .7, curve: Curves.easeOut),
    ),
  );
  late final _railFade = CurvedAnimation(
    parent: _c,
    curve: const Interval(.45, 1, curve: Curves.easeIn),
  );

  @override
  void didUpdateWidget(FoldingPanel old) {
    super.didUpdateWidget(old);
    if (old.folded != widget.folded) widget.folded ? _c.forward() : _c.reverse();
  }

  @override
  void dispose() {
    _t.dispose();
    _c.dispose();
    super.dispose();
  }

  Widget _place(double width, Animation<double> fade, bool active, Widget child) => Positioned(
    top: 0,
    bottom: 0,
    left: widget.atLeft ? 0 : null,
    right: widget.atLeft ? null : 0,
    width: width,
    child: IgnorePointer(
      ignoring: !active,
      child: FadeTransition(
        opacity: fade,
        child: RepaintBoundary(child: child),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: _t,
    builder: (_, _) {
      final t = _t.value;
      return SizedBox(
        width: widget.fullWidth + (widget.miniWidth - widget.fullWidth) * t,
        child: ClipRect(
          child: Stack(
            clipBehavior: Clip.none,
            children: [
              if (t < 1) _place(widget.fullWidth, _panelFade, !widget.folded, widget.full),
              if (t > 0) _place(widget.miniWidth, _railFade, widget.folded, widget.mini),
            ],
          ),
        ),
      );
    },
  );
}

/// A side column that comes and goes with the screen (the Details panel is on Chat and Voice
/// only): it slides in from / out to the window's edge and fades, and the middle column follows
/// its width, instead of jumping.
class SlideAway extends StatefulWidget {
  const SlideAway({super.key, required this.visible, required this.child});

  final bool visible;
  final Widget child;

  @override
  State<SlideAway> createState() => _SlideAwayState();
}

class _SlideAwayState extends State<SlideAway> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 260), value: widget.visible ? 1 : 0);
  late final _t = CurvedAnimation(parent: _c, curve: Curves.easeInOutCubic);
  late Widget _shown = widget.child; // kept while it slides away

  @override
  void didUpdateWidget(SlideAway old) {
    super.didUpdateWidget(old);
    if (widget.visible) _shown = widget.child;
    if (old.visible != widget.visible) widget.visible ? _c.forward() : _c.reverse();
  }

  @override
  void dispose() {
    _t.dispose();
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: _t,
    builder: (_, child) => _t.value == 0
        ? const SizedBox.shrink()
        : ClipRect(
            child: Align(alignment: Alignment.centerLeft, widthFactor: _t.value, child: child),
          ),
    child: FadeTransition(opacity: _t, child: _shown),
  );
}
