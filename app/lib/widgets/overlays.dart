import 'dart:async';

import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../shell/layout.dart';
import '../theme.dart';
import 'sora_widgets.dart';

// ------------------------------------------------------------------------------------- toast

/// Hosts the design's toast: a centred `--sheet` glass pill 96px above the bottom that rises in and
/// dismisses itself after 1.9s. Wrapped around the whole app; call [showToast] from anywhere.
class ToastHost extends StatefulWidget {
  const ToastHost({super.key, required this.child});

  final Widget child;

  @override
  State<ToastHost> createState() => _ToastHostState();
}

class _ToastHostState extends State<ToastHost> {
  String? _text;
  int _serial = 0;
  Timer? _timer;

  void show(String text) {
    _timer?.cancel();
    setState(() {
      _text = text;
      _serial++;
    });
    _timer = Timer(const Duration(milliseconds: 1900), () {
      if (mounted) setState(() => _text = null);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final bottom = MediaQuery.paddingOf(context).bottom + 96;
    return Stack(
      children: [
        widget.child,
        if (_text != null)
          Positioned(
            left: 16,
            right: 16,
            bottom: bottom,
            child: IgnorePointer(
              child: Center(
                child: Rise(
                  key: ValueKey(_serial),
                  child: Material(
                    type: MaterialType.transparency,
                    child: Glass(
                      radius: 16,
                      // it fades in, so no backdrop blur (that would flash dark): a denser fill instead
                      fill: p.dark ? const Color(0xEB16181D) : const Color(0xF2FFFFFF),
                      strong: true,
                      blur: false,
                      shadow: true,
                      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                      child: Text(
                        _text!,
                        style: SoraType.ui(14, weight: FontWeight.w500, color: p.ink),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}

void showToast(BuildContext context, String text) => context.findRootAncestorStateOfType<_ToastHostState>()?.show(text);

// ------------------------------------------------------------------------------------- motion

/// The design's `rise` keyframes: fade in while moving up 8px.
class Rise extends StatefulWidget {
  const Rise({
    super.key,
    required this.child,
    this.duration = const Duration(milliseconds: 300),
    this.delay = Duration.zero,
    this.offset = 8,
  });

  final Widget child;
  final Duration duration, delay;
  final double offset;

  @override
  State<Rise> createState() => _RiseState();
}

class _RiseState extends State<Rise> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: widget.duration + widget.delay)..forward();
  late final _t = CurvedAnimation(
    parent: _c,
    curve: Interval(widget.delay.inMicroseconds / (widget.duration + widget.delay).inMicroseconds, 1, curve: const Cubic(.2, .8, .2, 1)),
  );

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FadeTransition(
    opacity: _t,
    child: widget.offset == 0
        ? widget.child
        : AnimatedBuilder(
            animation: _t,
            builder: (_, child) => Transform.translate(offset: Offset(0, widget.offset * (1 - _t.value)), child: child),
            child: widget.child,
          ),
  );
}

// ------------------------------------------------------------------------------------- sheets

/// Bottom sheet in the design's style: `--sheet` glass with strong blur, 28px top corners, a grab
/// handle and a 17/600 title, over a `--scrim`.
///
/// On desktop the same content opens as a centred 460px glass dialog with 24px corners.
Future<T?> showSoraSheet<T>(BuildContext context, {required String title, required WidgetBuilder builder}) {
  final p = SoraPalette.of(context);
  if (SoraLayout.isDesktop(context)) return _showSoraDialog<T>(context, p, title, builder);
  return showModalBottomSheet<T>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    barrierColor: p.scrim,
    elevation: 0,
    builder: (ctx) {
      final pad = MediaQuery.viewInsetsOf(ctx).bottom + MediaQuery.paddingOf(ctx).bottom;
      // The sheet slides up while its blur and fill grow and its content fades in (reveal, as in Glass):
      // a full blur sliding in at once looked torn, and so does one inside a fade.
      final reveal = _sheetCurve(ModalRoute.of(ctx)?.animation ?? kAlwaysCompleteAnimation);
      return ConstrainedBox(
        constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(ctx).height * .86),
        child: AnimatedBuilder(
          animation: reveal,
          builder: (_, content) {
            final t = reveal.value.clamp(0.0, 1.0);
            Color a(Color c) => t >= 1 ? c : c.withValues(alpha: c.a * t);
            return ClipRRect(
              borderRadius: const BorderRadius.vertical(top: Radius.circular(28)),
              child: BackdropFilter(
                filter: soraGlassFilter(p, strong: true, amount: t),
                child: Container(
                  decoration: BoxDecoration(
                    color: a(p.sheet),
                    borderRadius: const BorderRadius.vertical(top: Radius.circular(28)),
                    border: Border(
                      top: BorderSide(color: a(p.line)),
                      left: BorderSide(color: a(p.line)),
                      right: BorderSide(color: a(p.line)),
                    ),
                  ),
                  padding: EdgeInsets.fromLTRB(18, 10, 18, 22 + pad),
                  child: content,
                ),
              ),
            );
          },
          child: FadeTransition(
            opacity: reveal,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Center(
                    child: Container(
                      width: 40,
                      height: 5,
                      decoration: BoxDecoration(color: p.faint, borderRadius: BorderRadius.circular(3)),
                    ),
                  ),
                  const SizedBox(height: 14),
                  Text(
                    title,
                    style: SoraType.ui(17, weight: FontWeight.w600, color: p.ink, height: 1.35),
                  ),
                  const SizedBox(height: 14),
                  builder(ctx),
                ],
              ),
            ),
          ),
        ),
      );
    },
  );
}

Future<T?> _showSoraDialog<T>(BuildContext context, SoraPalette p, String title, WidgetBuilder builder) => showGeneralDialog<T>(
  context: context,
  barrierDismissible: true,
  barrierLabel: MaterialLocalizations.of(context).modalBarrierDismissLabel,
  barrierColor: p.scrim,
  transitionDuration: const Duration(milliseconds: 260),
  // No fade around the glass (its blur would sample nothing and flash): it slides and grows a little,
  // and the glass itself comes in (reveal).
  transitionBuilder: (_, a, _, child) {
    final t = _sheetCurve(a);
    return SlideTransition(
      position: Tween(begin: const Offset(0, .015), end: Offset.zero).animate(t),
      child: ScaleTransition(scale: Tween(begin: .97, end: 1.0).animate(t), child: child),
    );
  },
  pageBuilder: (ctx, a, _) => Center(
    child: Material(
      type: MaterialType.transparency,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: 460, maxHeight: MediaQuery.sizeOf(ctx).height * .86),
        child: Glass(
          radius: 24,
          fill: p.sheet,
          strong: true,
          reveal: _sheetCurve(a),
          padding: const EdgeInsets.fromLTRB(18, 10, 18, 22),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  title,
                  style: SoraType.ui(17, weight: FontWeight.w600, color: p.ink, height: 1.35),
                ),
                const SizedBox(height: 14),
                builder(ctx),
              ],
            ),
          ),
        ),
      ),
    ),
  ),
);

// One curve per route's animation: the builders run again on rebuilds, and each new CurvedAnimation
// would add another listener to the route.
final _sheetCurves = Expando<Animation<double>>();

Animation<double> _sheetCurve(Animation<double> a) =>
    _sheetCurves[a] ??= CurvedAnimation(parent: a, curve: const Cubic(.2, .8, .2, 1), reverseCurve: const Cubic(.4, 0, .6, 1));

/// One row of a list sheet: 50px, icon + label, red when [danger].
class SheetItem extends StatelessWidget {
  const SheetItem({super.key, required this.icon, required this.label, required this.onTap, this.danger = false});

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final c = danger ? p.err : p.ink;
    return Pressable(
      onTap: onTap,
      child: SizedBox(
        height: 50,
        child: Row(
          children: [
            const SizedBox(width: 6),
            LIcon(icon, size: 21, color: c),
            const SizedBox(width: 14),
            Expanded(
              child: Text(label, style: SoraType.ui(15.5, color: c)),
            ),
          ],
        ),
      ),
    );
  }
}

/// Square glass tile with a big accent icon over a label (attach sheet: Camera / Photos / Files).
class SheetTile extends StatelessWidget {
  const SheetTile({super.key, required this.icon, required this.label, required this.onTap, this.height = 86});

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final double height;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Pressable(
      onTap: onTap,
      child: Glass(
        height: height,
        radius: 18,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            LIcon(icon, size: 26, color: p.acc),
            const SizedBox(height: 6),
            Text(label, style: SoraType.ui(13.5, color: p.ink)),
          ],
        ),
      ),
    );
  }
}

// ------------------------------------------------------------------------------------- list screens

/// Header of the list screens: glass back button, 21/600 title, optional pill action on the right.
class ScreenHeader extends StatelessWidget {
  const ScreenHeader({super.key, required this.title, required this.onBack, this.action});

  final String title;
  final VoidCallback onBack;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final s = MaterialLocalizations.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 6, 14, 10),
      child: Row(
        children: [
          GlassIconButton(icon: Symbols.arrow_back_rounded, tooltip: s.backButtonTooltip, onTap: onBack, iconSize: 21),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              title,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: SoraType.ui(21, weight: FontWeight.w600, color: SoraPalette.of(context).ink),
            ),
          ),
          ?action,
        ],
      ),
    );
  }
}

/// Pill action button for [ScreenHeader] (e.g. "+ New reminder").
class HeaderAction extends StatelessWidget {
  const HeaderAction({super.key, required this.icon, required this.label, required this.onTap});

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Pressable(
      onTap: onTap,
      child: Glass(
        height: 38,
        radius: 19,
        padding: const EdgeInsets.fromLTRB(10, 0, 14, 0),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            LIcon(icon, size: 18, color: p.acc),
            const SizedBox(width: 6),
            Text(
              label,
              style: SoraType.ui(13.5, weight: FontWeight.w500, color: p.ink),
            ),
          ],
        ),
      ),
    );
  }
}

/// Empty state: 64px glass tile with a dim icon over centred text.
class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Rise(
      duration: const Duration(milliseconds: 400),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 64),
        child: Column(
          children: [
            Glass(
              width: 64,
              height: 64,
              radius: 20,
              child: Center(child: LIcon(icon, size: 28, color: p.dim)),
            ),
            const SizedBox(height: 14),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 270),
              child: Text(
                text,
                textAlign: TextAlign.center,
                style: SoraType.ui(15, color: p.dim, height: 1.55),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
