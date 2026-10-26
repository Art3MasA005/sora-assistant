import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../brand/sora_logo.dart';
import '../core/session.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/sora_widgets.dart';
import 'screens.dart';

/// The glass side menu from the design: Sora + connection status, New chat, Chat / Voice, the
/// list screens (Notifications with its unread badge), and the theme switch at the bottom.
class SideMenu extends StatefulWidget {
  const SideMenu({
    super.key,
    required this.session,
    required this.current,
    required this.online,
    required this.unread,
    required this.onSelect,
    required this.onNewChat,
    required this.onClose,
  });

  final Session session;
  final SoraScreen current;
  final bool online;
  final int unread;
  final ValueChanged<SoraScreen> onSelect;
  final VoidCallback onNewChat, onClose;

  @override
  State<SideMenu> createState() => SideMenuState();
}

class SideMenuState extends State<SideMenu> with SingleTickerProviderStateMixin {
  // `drawer` .4s cubic-bezier(.2,.8,.2,1); items `rise` with a 28ms stagger.
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 700))..forward();
  static const _ease = Cubic(.2, .8, .2, 1);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  /// Plays the drawer backwards, then tells the shell to remove it.
  Future<void> close() async {
    await _c.animateBack(0, duration: const Duration(milliseconds: 260), curve: Curves.easeIn);
    if (mounted) widget.onClose();
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final media = MediaQuery.of(context);
    final width = (media.size.width * .82).clamp(0.0, 318.0);
    var index = 0;

    Widget item(SoraScreen screen, IconData icon, String label, {int badge = 0}) {
      final on = widget.current == screen;
      final delay = .028 * index++;
      return _Staggered(
        controller: _c,
        start: delay,
        child: Pressable(
          onTap: () => widget.onSelect(screen),
          child: SizedBox(
            height: 44,
            child: Row(
              children: [
                const SizedBox(width: 6),
                Glass(
                  width: 32,
                  height: 32,
                  radius: 10,
                  fill: p.glass2,
                  blur: false,
                  child: Center(
                    child: LIcon(icon, size: 19, color: on ? p.acc : p.dim, fill: on),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    label,
                    style: SoraType.ui(15, weight: FontWeight.w500, color: p.ink),
                  ),
                ),
                if (badge > 0)
                  Container(
                    constraints: const BoxConstraints(minWidth: 22),
                    height: 22,
                    padding: const EdgeInsets.symmetric(horizontal: 7),
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: p.err,
                      borderRadius: BorderRadius.circular(11),
                      boxShadow: [BoxShadow(color: p.errSoft, blurRadius: 10, offset: const Offset(0, 2))],
                    ),
                    child: Text(
                      s.num(badge),
                      style: SoraType.ui(12, weight: FontWeight.w600, color: Colors.white, height: 1),
                    ),
                  ),
                const SizedBox(width: 10),
              ],
            ),
          ),
        ),
      );
    }

    return Stack(
      children: [
        // scrim
        Positioned.fill(
          child: GestureDetector(
            onTap: close,
            child: FadeTransition(
              opacity: _c.drive(CurveTween(curve: const Interval(0, .36))),
              child: ColoredBox(color: p.scrimLight),
            ),
          ),
        ),
        // drawer
        Positioned(
          left: 8,
          top: media.padding.top + 4,
          bottom: media.padding.bottom + 6,
          width: width,
          child: SlideTransition(
            position: _c
                .drive(CurveTween(curve: const Interval(0, .57, curve: _ease)))
                .drive(Tween(begin: const Offset(-1.1, 0), end: Offset.zero)),
            child: Glass(
              radius: 30,
              fill: p.menuGlass,
              strong: true,
              shadow: true,
              child: Stack(
                children: [
                  Positioned(
                    left: 0,
                    right: 0,
                    top: 0,
                    height: 140,
                    child: IgnorePointer(
                      child: DecoratedBox(
                        decoration: BoxDecoration(
                          gradient: LinearGradient(
                            begin: Alignment.topCenter,
                            end: Alignment.bottomCenter,
                            colors: [p.sheen, p.sheen.withAlpha(0)],
                          ),
                        ),
                      ),
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(10, 12, 10, 10),
                    // its own layer: sliding the drawer then moves it instead of redrawing it
                    child: RepaintBoundary(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          _head(p, s),
                          const SizedBox(height: 8),
                          _Staggered(controller: _c, start: 0, child: _newChat(p, s)),
                          const SizedBox(height: 6),
                          item(SoraScreen.chat, Symbols.chat_bubble_rounded, s.chat),
                          item(SoraScreen.voice, Symbols.graphic_eq_rounded, s.voice),
                          Container(height: 1, margin: const EdgeInsets.symmetric(horizontal: 10, vertical: 6), color: p.line),
                          Expanded(
                            child: ListView(
                              padding: EdgeInsets.zero,
                              children: [
                                item(SoraScreen.conversations, Symbols.forum_rounded, s.conversations),
                                item(SoraScreen.notifications, Symbols.notifications_rounded, s.notifications, badge: widget.unread),
                                item(SoraScreen.reminders, Symbols.alarm_rounded, s.reminders),
                                item(SoraScreen.routines, Symbols.event_repeat_rounded, s.routines),
                                item(SoraScreen.memories, Symbols.psychology_rounded, s.memories),
                                item(SoraScreen.people, Symbols.contacts_rounded, s.people),
                                item(SoraScreen.knowledge, Symbols.menu_book_rounded, s.knowledge),
                                item(SoraScreen.connections, Symbols.hub_rounded, s.connections),
                                item(SoraScreen.devices, Symbols.devices_rounded, s.devices),
                                item(SoraScreen.settings, Symbols.settings_rounded, s.settings),
                              ],
                            ),
                          ),
                          const SizedBox(height: 8),
                          ListenableBuilder(
                            listenable: widget.session,
                            builder: (context, _) => _ThemeSwitch(session: widget.session),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _head(SoraPalette p, S s) => Padding(
    padding: const EdgeInsets.fromLTRB(6, 2, 4, 0),
    child: Row(
      children: [
        SizedBox(
          width: 46,
          height: 46,
          child: Stack(
            clipBehavior: Clip.none,
            children: [
              Positioned(
                left: -3,
                top: -3,
                right: -3,
                bottom: -3,
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(color: p.accLine),
                  ),
                ),
              ),
              const SoraMark(size: 46),
            ],
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Sora',
                style: SoraType.ui(19, weight: FontWeight.w600, color: p.ink).copyWith(letterSpacing: -.19),
              ),
              Row(
                children: [
                  Container(
                    width: 6,
                    height: 6,
                    decoration: BoxDecoration(
                      color: widget.online ? p.ok : p.faint,
                      shape: BoxShape.circle,
                      boxShadow: widget.online ? [BoxShadow(color: p.ok, blurRadius: 8)] : null,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Flexible(
                    child: Text(
                      widget.online ? s.ownerLine : s.offline,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: SoraType.mono(10.5, weight: FontWeight.w500, spacing: 0, color: p.dim),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        GlassIconButton(icon: Symbols.close_rounded, tooltip: s.close, size: 36, iconSize: 19, onTap: close),
      ],
    ),
  );

  Widget _newChat(SoraPalette p, S s) => Pressable(
    onTap: widget.onNewChat,
    child: Glass(
      height: 44,
      radius: 15,
      fill: p.glass2,
      blur: false,
      padding: const EdgeInsets.fromLTRB(6, 0, 10, 0),
      child: Row(
        children: [
          SizedBox(
            width: 32,
            height: 32,
            child: Center(child: LIcon(Symbols.edit_square_rounded, size: 20, color: p.acc)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              s.newChat,
              style: SoraType.ui(15, weight: FontWeight.w500, color: p.ink),
            ),
          ),
        ],
      ),
    ),
  );
}

/// Item entrance: fade + rise, starting [start] seconds into the drawer animation.
class _Staggered extends StatelessWidget {
  const _Staggered({required this.controller, required this.start, required this.child});

  final AnimationController controller;
  final double start;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final total = controller.duration!.inMilliseconds / 1000;
    final a = (start / total).clamp(0.0, 1.0), b = ((start + .4) / total).clamp(0.0, 1.0);
    final t = controller.drive(CurveTween(curve: Interval(a, b, curve: const Cubic(.2, .8, .2, 1))));
    // a fade layer, not Opacity (which re-renders the item offscreen every frame)
    return FadeTransition(
      opacity: t,
      child: AnimatedBuilder(
        animation: t,
        builder: (_, c) => Transform.translate(offset: Offset(0, 8 * (1 - t.value)), child: c),
        child: child,
      ),
    );
  }
}

/// Auto / Light / Dark in a glass track at the bottom of the menu.
class _ThemeSwitch extends StatelessWidget {
  const _ThemeSwitch({required this.session});

  final Session session;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    return Glass(
      radius: 14,
      fill: p.glass2,
      blur: false,
      padding: const EdgeInsets.all(3),
      child: SoraSegmented<ThemeMode>(
        bare: true,
        options: [(ThemeMode.system, s.themeAuto), (ThemeMode.light, s.themeLight), (ThemeMode.dark, s.themeDark)],
        value: session.themeMode,
        onChanged: session.setThemeMode,
      ),
    );
  }
}
