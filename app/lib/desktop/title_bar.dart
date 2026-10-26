import 'package:flutter/gestures.dart' show kPrimaryMouseButton;
import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';
import 'package:window_manager/window_manager.dart';

import '../brand/sora_logo.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/sora_widgets.dart';
import 'desktop_kit.dart';

/// The Windows window, drawn by the app: one graphite background behind a 36px transparent title
/// bar and [child]. The native title bar is hidden (see main.dart).
class DesktopFrame extends StatelessWidget {
  const DesktopFrame({super.key, required this.child, this.online});

  final Widget child;

  /// Server status shown in the title bar; null before sign-in (nothing shown).
  final bool? online;

  @override
  Widget build(BuildContext context) => SoraBackground.paint(
    context,
    Material(
      type: MaterialType.transparency,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          DesktopTitleBar(online: online),
          Expanded(child: child),
        ],
      ),
    ),
  );
}

/// Sora mark + name, the connection line, and minimise / maximise / close (46×36; close turns
/// Windows red on hover). Everything left of the buttons drags the window; double-click maximises.
class DesktopTitleBar extends StatefulWidget {
  const DesktopTitleBar({super.key, this.online});

  final bool? online;

  @override
  State<DesktopTitleBar> createState() => _DesktopTitleBarState();
}

class _DesktopTitleBarState extends State<DesktopTitleBar> with WindowListener {
  bool _maximized = false;

  @override
  void initState() {
    super.initState();
    windowManager.addListener(this);
    windowManager.isMaximized().then((m) {
      if (mounted) setState(() => _maximized = m);
    });
  }

  @override
  void dispose() {
    windowManager.removeListener(this);
    super.dispose();
  }

  @override
  void onWindowMaximize() => setState(() => _maximized = true);

  @override
  void onWindowUnmaximize() => setState(() => _maximized = false);

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final online = widget.online;
    return SizedBox(
      height: 36,
      child: Row(
        // full height, so the whole bar drags (not just the strip the text is in)
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(
            child: _DragArea(
              child: Padding(
                padding: const EdgeInsets.only(left: 14),
                child: Row(
                  children: [
                    const SoraMark(size: 16),
                    const SizedBox(width: 8),
                    Text('Sora', style: SoraType.ui(12.5, weight: FontWeight.w600, color: p.ink)),
                    if (online != null) ...[
                      Container(width: 1, height: 14, margin: const EdgeInsets.symmetric(horizontal: 12), color: p.line),
                      Container(
                        width: 5,
                        height: 5,
                        decoration: BoxDecoration(
                          color: online ? p.ok : p.faint,
                          shape: BoxShape.circle,
                          boxShadow: online ? [BoxShadow(color: p.ok, blurRadius: 6)] : null,
                        ),
                      ),
                      const SizedBox(width: 6),
                      Flexible(
                        child: Text(
                          online ? s.ownerLine : s.offline,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: SoraType.mono(10.5, weight: FontWeight.w500, spacing: 0, color: p.dim),
                        ),
                      ),
                    ],
                    const Spacer(),
                  ],
                ),
              ),
            ),
          ),
          _WindowButton(icon: Symbols.remove_rounded, size: 16, tooltip: s.minimize, onTap: windowManager.minimize),
          _WindowButton(
            icon: _maximized ? Symbols.filter_none_rounded : Symbols.crop_square_rounded,
            size: _maximized ? 12 : 13,
            tooltip: _maximized ? s.restore : s.maximize,
            onTap: () => _maximized ? windowManager.unmaximize() : windowManager.maximize(),
          ),
          _WindowButton(icon: Symbols.close_rounded, size: 17, tooltip: s.close, onTap: windowManager.close, danger: true),
        ],
      ),
    );
  }
}

/// Drags the window from the moment the mouse goes down, like a native title bar (window_manager's
/// DragToMoveArea waits for Flutter to see a pan, which on this window never came, so it didn't
/// move); a second click within 400 ms maximises or restores instead.
class _DragArea extends StatefulWidget {
  const _DragArea({required this.child});

  final Widget child;

  @override
  State<_DragArea> createState() => _DragAreaState();
}

class _DragAreaState extends State<_DragArea> {
  DateTime? _lastDown;

  Future<void> _down(PointerDownEvent e) async {
    if (e.buttons != kPrimaryMouseButton) return;
    final now = DateTime.now();
    final last = _lastDown;
    _lastDown = now;
    if (last != null && now.difference(last) < const Duration(milliseconds: 400)) {
      _lastDown = null;
      await (await windowManager.isMaximized() ? windowManager.unmaximize() : windowManager.maximize());
      return;
    }
    await windowManager.startDragging();
  }

  @override
  Widget build(BuildContext context) =>
      Listener(behavior: HitTestBehavior.opaque, onPointerDown: _down, child: widget.child);
}

class _WindowButton extends StatelessWidget {
  const _WindowButton({required this.icon, required this.size, required this.tooltip, required this.onTap, this.danger = false});

  final IconData icon;
  final double size;
  final String tooltip;
  final VoidCallback onTap;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Hover(
      onTap: onTap,
      builder: (_, hover) => AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        width: 46,
        height: 36,
        // fade to the same colour at zero alpha (Colors.transparent is black: a grey flash)
        color: danger ? const Color(0xFFC42B1C).withAlpha(hover ? 255 : 0) : (hover ? p.surf2 : p.surf2.withAlpha(0)),
        alignment: Alignment.center,
        child: LIcon(icon, size: size, weight: 300, color: hover ? (danger ? Colors.white : p.ink) : p.dim),
      ),
    );
  }
}
