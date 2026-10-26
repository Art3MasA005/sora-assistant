import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';

import '../theme.dart';
import '../widgets/sora_widgets.dart';

/// Chat underneath, the other screens over it, with no hard cuts: a screen fades (and rises a
/// little) in over what was there, which stays drawn until it is covered (so nothing dark shows
/// through), and fades out again over Chat when going back. Chat stays alive (its ticker paused)
/// and stops being drawn once a screen covers it.
class ScreenStack extends StatefulWidget {
  const ScreenStack({super.key, required this.onChat, required this.chat, required this.pageKey, required this.page});

  final bool onChat;
  final Widget chat;

  /// The screen over Chat (ignored while [onChat]); a new [pageKey] is a new screen.
  final Object pageKey;
  final Widget page;

  static const duration = Duration(milliseconds: 240);

  @override
  State<ScreenStack> createState() => _ScreenStackState();
}

class _ScreenStackState extends State<ScreenStack> {
  static const _chatKey = ValueKey('#chat');
  late bool _chatDrawn = widget.onChat;
  Timer? _hide;

  @override
  void didUpdateWidget(ScreenStack old) {
    super.didUpdateWidget(old);
    if (widget.onChat == old.onChat) return;
    _hide?.cancel();
    if (widget.onChat) {
      _chatDrawn = true;
    } else {
      _hide = Timer(ScreenStack.duration + const Duration(milliseconds: 40), () {
        if (mounted && !widget.onChat) setState(() => _chatDrawn = false);
      });
    }
  }

  @override
  void dispose() {
    _hide?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final current = widget.onChat ? _chatKey : ValueKey(widget.pageKey);
    return Stack(
      fit: StackFit.expand,
      children: [
        Offstage(offstage: !_chatDrawn, child: TickerMode(enabled: widget.onChat, child: widget.chat)),
        AnimatedSwitcher(
          duration: ScreenStack.duration,
          switchInCurve: Curves.easeOutCubic,
          switchOutCurve: Curves.easeInCubic,
          layoutBuilder: (top, below) => Stack(fit: StackFit.expand, children: [...below, ?top]),
          // Rebuilt for every child on each build (a new closure), so the outgoing one is judged
          // against where we are going now.
          transitionBuilder: (child, a) {
            if (child.key == current) {
              if (child.key == _chatKey) return child;
              return FadeTransition(
                opacity: a,
                child: SlideTransition(position: Tween(begin: const Offset(0, .012), end: Offset.zero).animate(a), child: child),
              );
            }
            // leaving: back to Chat it fades out; under a new screen it stays until covered
            return widget.onChat ? FadeTransition(opacity: a, child: child) : child;
          },
          child: widget.onChat
              ? const SizedBox.shrink(key: _chatKey)
              : KeyedSubtree(key: current, child: RepaintBoundary(child: widget.page)),
        ),
      ],
    );
  }
}

/// The window's background (see [SoraBackground]) as seen through this box, so a screen laid over
/// another hides it completely while matching the background around it exactly (desktop, where
/// screens are otherwise see-through).
class WindowBackdrop extends SingleChildRenderObjectWidget {
  const WindowBackdrop({super.key, super.child});

  @override
  RenderObject createRenderObject(BuildContext context) =>
      _RenderWindowBackdrop(SoraPalette.of(context).shade, MediaQuery.sizeOf(context));

  @override
  void updateRenderObject(BuildContext context, RenderObject renderObject) {
    (renderObject as _RenderWindowBackdrop)
      ..shade = SoraPalette.of(context).shade
      ..window = MediaQuery.sizeOf(context);
  }
}

class _RenderWindowBackdrop extends RenderProxyBox {
  _RenderWindowBackdrop(this._shade, this._window);

  double _shade;
  Size _window;

  set shade(double v) {
    if (v == _shade) return;
    _shade = v;
    markNeedsPaint();
  }

  set window(Size v) {
    if (v == _window) return;
    _window = v;
    markNeedsPaint();
  }

  @override
  void paint(PaintingContext context, Offset offset) {
    final canvas = context.canvas;
    final origin = localToGlobal(Offset.zero);
    canvas.save();
    canvas.clipRect(offset & size);
    canvas.translate(offset.dx - origin.dx, offset.dy - origin.dy);
    SoraBackground.paintWindow(canvas, _window, _shade);
    canvas.restore();
    super.paint(context, offset);
  }
}
