import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../brand/sora_logo.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/sora_widgets.dart';
import '../widgets/overlays.dart';
import 'chat_models.dart';

/// Repeating animation driver for the small looping effects below.
mixin _Loop<T extends StatefulWidget> on State<T>, SingleTickerProviderStateMixin<T> {
  Duration get period;
  late final AnimationController loop = AnimationController(vsync: this, duration: period)..repeat();

  @override
  void dispose() {
    loop.dispose();
    super.dispose();
  }
}

/// Text with the design's `shimmer`: a dim → ink → accent highlight sweeping across every 1.6s.
class ShimmerText extends StatefulWidget {
  const ShimmerText(this.text, {super.key, required this.style});

  final String text;
  final TextStyle style;

  @override
  State<ShimmerText> createState() => _ShimmerTextState();
}

class _ShimmerTextState extends State<ShimmerText> with SingleTickerProviderStateMixin, _Loop {
  @override
  Duration get period => const Duration(milliseconds: 1600);

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return AnimatedBuilder(
      animation: loop,
      builder: (_, child) => ShaderMask(
        blendMode: BlendMode.srcIn,
        shaderCallback: (rect) {
          // background-size 200%, position 200% → -200%: the band crosses the text once per period.
          final w = rect.width * 2, x = rect.width * 2 * (1 - loop.value) - rect.width * 2 + rect.width;
          return LinearGradient(
            colors: [p.dim, p.ink, p.acc, p.dim],
            stops: const [0, .45, .55, 1],
          ).createShader(Rect.fromLTWH(x - w / 2, 0, w, rect.height));
        },
        child: child,
      ),
      child: Text(widget.text, style: widget.style),
    );
  }
}

/// Three 7px accent dots bouncing in turn (`@keyframes dot`).
class TypingDots extends StatefulWidget {
  const TypingDots({super.key});

  @override
  State<TypingDots> createState() => _TypingDotsState();
}

class _TypingDotsState extends State<TypingDots> with SingleTickerProviderStateMixin, _Loop {
  @override
  Duration get period => const Duration(milliseconds: 1200);

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: AnimatedBuilder(
        animation: loop,
        builder: (_, _) => Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (var i = 0; i < 3; i++) ...[
              if (i > 0) const SizedBox(width: 5),
              Builder(
                builder: (_) {
                  // 0–80–100%: rest; peak at 40%. Each dot starts .15s later.
                  final t = ((loop.value - i * .125) % 1 + 1) % 1;
                  final k = t < .4 ? t / .4 : (t < .8 ? (.8 - t) / .4 : 0.0);
                  return Transform.translate(
                    offset: Offset(0, -3 * k),
                    child: Opacity(
                      opacity: .25 + .75 * k,
                      child: Container(
                        width: 7,
                        height: 7,
                        decoration: BoxDecoration(color: p.acc, shape: BoxShape.circle),
                      ),
                    ),
                  );
                },
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Three small bars pulsing like an equaliser (`@keyframes eq`), shown while reading aloud.
class EqBars extends StatefulWidget {
  const EqBars({super.key});

  @override
  State<EqBars> createState() => _EqBarsState();
}

class _EqBarsState extends State<EqBars> with SingleTickerProviderStateMixin, _Loop {
  @override
  Duration get period => const Duration(milliseconds: 800);

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return SizedBox(
      height: 16,
      child: AnimatedBuilder(
        animation: loop,
        builder: (_, _) => Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (var i = 0; i < 3; i++) ...[
              if (i > 0) const SizedBox(width: 2),
              Container(
                width: 3,
                height: 14 * (.35 + .65 * (.5 - .5 * math.cos(2 * math.pi * (loop.value - i * .25)))),
                decoration: BoxDecoration(color: p.acc, borderRadius: BorderRadius.circular(2)),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Sora's 30px avatar; while she works, an accent arc spins around it.
class SoraWorkingAvatar extends StatefulWidget {
  const SoraWorkingAvatar({super.key, required this.working});

  final bool working;

  @override
  State<SoraWorkingAvatar> createState() => _SoraWorkingAvatarState();
}

class _SoraWorkingAvatarState extends State<SoraWorkingAvatar> with SingleTickerProviderStateMixin, _Loop {
  @override
  Duration get period => const Duration(milliseconds: 1100);

  // The arc spins only while she works: a ticker left running after the reply would redraw the app
  // every frame for good (no idle frames: lag and battery).
  @override
  void didUpdateWidget(SoraWorkingAvatar old) {
    super.didUpdateWidget(old);
    if (widget.working && !loop.isAnimating) {
      loop.repeat();
    } else if (!widget.working && loop.isAnimating) {
      loop.stop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return SizedBox(
      width: 30,
      height: 30,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          if (widget.working)
            Positioned(
              left: -3,
              top: -3,
              right: -3,
              bottom: -3,
              child: RotationTransition(
                turns: loop,
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: SweepGradient(colors: [p.acc, p.acc.withAlpha(0), p.acc, p.acc.withAlpha(0)], stops: const [0, .35, .65, 1]),
                  ),
                ),
              ),
            ),
          const SoraMark(size: 30),
        ],
      ),
    );
  }
}

/// Service chip above a reply: "Checking Gmail…" with a spinner, then Gmail ✓ (or red on failure).
class ToolChip extends StatelessWidget {
  const ToolChip({super.key, required this.chip});

  final ToolChipData chip;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final state = chip.state;
    final fail = state == ToolState.fail;
    final labelStyle = SoraType.ui(12.5, weight: FontWeight.w500, color: fail ? p.err : p.ink, height: 1);
    return Rise(
      child: Glass(
        height: 28,
        radius: 14,
        fill: fail ? p.errSoft : p.surf,
        borderColor: fail ? p.err : p.line,
        padding: const EdgeInsets.fromLTRB(8, 0, 10, 0),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            LIcon(chip.icon, size: 15, color: p.dim),
            const SizedBox(width: 6),
            if (state == ToolState.run) ShimmerText(s.checking(chip.label), style: labelStyle) else Text(chip.label, style: labelStyle),
            const SizedBox(width: 6),
            switch (state) {
              ToolState.run => Spinner(size: 14, color: p.acc),
              ToolState.ok => LIcon(Symbols.check_circle_rounded, size: 15, color: p.ok, fill: true),
              ToolState.fail => LIcon(Symbols.error_rounded, size: 15, color: p.err, fill: true),
            },
          ],
        ),
      ),
    );
  }
}

/// Inline approval card: what Sora wants to do, the details, and Yes / No. After a decision it
/// shows Working… → Done / Cancelled / Couldn't complete.
class ApprovalCard extends StatelessWidget {
  const ApprovalCard({super.key, required this.approval, required this.onDecide, required this.onToggle});

  final Approval approval;
  final void Function(bool approve) onDecide;
  final VoidCallback onToggle;

  static const _collapsedLines = 6;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final v = ApprovalView.of(approval, s);
    final st = approval.status;
    final live = st == ApprovalStatus.pending || st == ApprovalStatus.busy;
    final lines = v.body?.trimRight().split('\n') ?? const <String>[];
    final long = lines.length > _collapsedLines;
    final shown = long && !approval.expanded ? lines.take(_collapsedLines).toList() : lines;

    Widget details() => Container(
      decoration: BoxDecoration(
        color: p.surf,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: p.line),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (final (i, (k, val)) in v.fields.indexed)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
              decoration: BoxDecoration(
                border: i < v.fields.length - 1 || lines.isNotEmpty ? Border(bottom: BorderSide(color: p.line)) : null,
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    width: 58,
                    child: Padding(
                      padding: const EdgeInsets.only(top: 1),
                      child: Text(k, style: SoraType.ui(12.5, color: p.dim, height: 1.45)),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      val,
                      style: SoraType.ui(13.5, weight: FontWeight.w500, color: p.ink, height: 1.45),
                    ),
                  ),
                ],
              ),
            ),
          if (lines.isNotEmpty)
            Stack(
              children: [
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                  child: Text(shown.join('\n'), style: SoraType.ui(13.5, color: p.ink, height: 1.55)),
                ),
                if (long && !approval.expanded)
                  Positioned(
                    left: 0,
                    right: 0,
                    bottom: 0,
                    height: 44,
                    child: IgnorePointer(
                      child: DecoratedBox(
                        decoration: BoxDecoration(
                          gradient: LinearGradient(
                            begin: Alignment.topCenter,
                            end: Alignment.bottomCenter,
                            colors: [p.fadeTo.withAlpha(0), p.fadeTo],
                          ),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          if (long)
            Pressable(
              onTap: onToggle,
              child: Container(
                height: 38,
                decoration: BoxDecoration(
                  border: Border(top: BorderSide(color: p.line)),
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    LIcon(approval.expanded ? Symbols.expand_less_rounded : Symbols.expand_more_rounded, size: 18, color: p.acc),
                    const SizedBox(width: 4),
                    Text(
                      approval.expanded ? s.showLess : '${s.showAll} · ${s.num(lines.length)} ${s.lines}',
                      style: SoraType.ui(13, weight: FontWeight.w500, color: p.acc),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );

    Widget result(IconData icon, String text, Color fg, {Color? bg, FontWeight weight = FontWeight.w600, bool fill = true}) => Rise(
      child: Container(
        height: 42,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: BoxDecoration(color: bg ?? p.surf, borderRadius: BorderRadius.circular(14)),
        child: Row(
          children: [
            LIcon(icon, size: 18, color: fg, fill: fill),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                text,
                style: SoraType.ui(14, weight: weight, color: fg),
              ),
            ),
          ],
        ),
      ),
    );

    return Rise(
      duration: const Duration(milliseconds: 400),
      child: AnimatedOpacity(
        duration: const Duration(milliseconds: 250),
        opacity: live ? 1 : .86,
        child: Glass(
          radius: 22,
          fill: p.glass2,
          strong: true,
          blur: false, // it fades in; nothing moves behind it
          sheen: true,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 14, 14, 0),
                child: Row(
                  children: [
                    Container(
                      width: 30,
                      height: 30,
                      decoration: BoxDecoration(
                        color: p.accSoft,
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: p.accLine),
                      ),
                      child: Center(child: LIcon(v.icon, size: 17, color: p.acc, fill: true)),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          MonoLabel(s.needsApproval),
                          Text(v.service, style: SoraType.ui(12.5, color: p.dim)),
                        ],
                      ),
                    ),
                    if (st == ApprovalStatus.pending)
                      Container(
                        width: 8,
                        height: 8,
                        margin: const EdgeInsets.only(right: 4),
                        decoration: BoxDecoration(
                          color: p.acc,
                          shape: BoxShape.circle,
                          boxShadow: [BoxShadow(color: p.accSoft, spreadRadius: 4)],
                        ),
                      ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      v.title,
                      style: SoraType.ui(16, weight: FontWeight.w600, color: p.ink, height: 1.35),
                    ),
                    if (v.fields.isNotEmpty || lines.isNotEmpty) ...[const SizedBox(height: 12), details()],
                    if (approval.tainted) ...[
                      const SizedBox(height: 12),
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          LIcon(Symbols.shield_lock_rounded, size: 16, color: p.dim),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(s.safety, style: SoraType.ui(12.5, color: p.dim, height: 1.45)),
                          ),
                        ],
                      ),
                    ],
                    const SizedBox(height: 12),
                    switch (st) {
                      ApprovalStatus.pending => Row(
                        children: [
                          Expanded(
                            flex: 2,
                            child: GlassButton(label: s.no, onTap: () => onDecide(false)),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            flex: 3,
                            child: InkButton(label: s.yes, height: 46, radius: 15, fontSize: 15, onTap: () => onDecide(true)),
                          ),
                        ],
                      ),
                      ApprovalStatus.busy => Container(
                        height: 46,
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                        decoration: BoxDecoration(color: p.surf, borderRadius: BorderRadius.circular(15)),
                        child: Row(
                          children: [
                            Spinner(size: 17, color: p.acc),
                            const SizedBox(width: 8),
                            Text(s.actionBusy, style: SoraType.ui(14, color: p.dim)),
                          ],
                        ),
                      ),
                      ApprovalStatus.done => result(Symbols.check_circle_rounded, s.actionDone, p.ok),
                      ApprovalStatus.cancelled => result(
                        Symbols.block_rounded,
                        s.actionCancelled,
                        p.dim,
                        weight: FontWeight.w500,
                        fill: false,
                      ),
                      ApprovalStatus.failed => result(Symbols.cancel_rounded, s.actionFailed, p.err, bg: p.errSoft),
                    },
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 34px round icon button with no chrome (message actions: copy, like, read aloud…).
class GhostIconButton extends StatelessWidget {
  const GhostIconButton({super.key, required this.icon, required this.tooltip, this.onTap, this.active = false, this.size = 18});

  final IconData icon;
  final String tooltip;
  final VoidCallback? onTap;
  final bool active;
  final double size;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Tooltip(
      message: tooltip,
      child: Pressable(
        onTap: onTap,
        semanticLabel: tooltip,
        child: SizedBox(
          width: 34,
          height: 34,
          child: Center(
            child: LIcon(icon, size: size, color: active ? p.acc : p.dim, fill: active),
          ),
        ),
      ),
    );
  }
}
