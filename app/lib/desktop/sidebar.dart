import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../l10n/strings.dart';
import '../shell/screens.dart';
import '../theme.dart';
import '../widgets/overlays.dart';
import '../widgets/sora_widgets.dart';
import 'desktop_kit.dart';

/// One place in the sidebar nav.
typedef NavEntry = ({SoraScreen screen, IconData icon, String label, int badge});

List<NavEntry> desktopNav(S s, int unread) => [
  (screen: SoraScreen.chat, icon: Symbols.chat_bubble_rounded, label: s.chat, badge: 0),
  (screen: SoraScreen.voice, icon: Symbols.graphic_eq_rounded, label: s.voice, badge: 0),
  (screen: SoraScreen.notifications, icon: Symbols.notifications_rounded, label: s.notifications, badge: unread),
  (screen: SoraScreen.reminders, icon: Symbols.alarm_rounded, label: s.reminders, badge: 0),
  (screen: SoraScreen.routines, icon: Symbols.event_repeat_rounded, label: s.routines, badge: 0),
  (screen: SoraScreen.memories, icon: Symbols.psychology_rounded, label: s.memories, badge: 0),
  (screen: SoraScreen.people, icon: Symbols.contacts_rounded, label: s.people, badge: 0),
  (screen: SoraScreen.knowledge, icon: Symbols.menu_book_rounded, label: s.knowledge, badge: 0),
  (screen: SoraScreen.connections, icon: Symbols.hub_rounded, label: s.connections, badge: 0),
  (screen: SoraScreen.devices, icon: Symbols.devices_rounded, label: s.devices, badge: 0),
];

/// The 272px left sidebar: Conversations label + hide, New chat (Ctrl N), search, the nav, the nine
/// most recent conversations (filtered by the search), and the owner with a settings button.
class DesktopSidebar extends StatefulWidget {
  const DesktopSidebar({
    super.key,
    required this.current,
    required this.unread,
    required this.conversations,
    required this.openConversationId,
    required this.ownerName,
    required this.ownerEmail,
    required this.onSelect,
    required this.onNewChat,
    required this.onOpenConversation,
    required this.onDeleteConversation,
    required this.onHide,
  });

  final SoraScreen current;
  final int unread;

  /// Rows from `/api/conversations`, newest first; null while loading.
  final List<Map<String, dynamic>>? conversations;
  final String? openConversationId;
  final String ownerName;
  final String? ownerEmail;
  final ValueChanged<SoraScreen> onSelect;
  final VoidCallback onNewChat, onHide;
  final ValueChanged<String> onOpenConversation;

  /// The bin on a Recent row (shown on hover).
  final ValueChanged<String> onDeleteConversation;

  @override
  State<DesktopSidebar> createState() => _DesktopSidebarState();
}

class _DesktopSidebarState extends State<DesktopSidebar> {
  final _search = TextEditingController();

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final q = _search.text.trim().toLowerCase();
    final recent = (widget.conversations ?? const [])
        .where((c) => q.isEmpty || '${c['title']} ${c['preview']}'.toLowerCase().contains(q))
        .take(9)
        .toList();

    return SizedBox(
      width: 272,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 14, 12, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(8, 0, 2, 12),
              child: Row(
                children: [
                  Expanded(child: MonoLabel(s.conversationsL)),
                  PanelToggle(icon: Symbols.left_panel_close_rounded, tooltip: s.hideSidebar, onTap: widget.onHide),
                ],
              ),
            ),
            _NewChatButton(onTap: widget.onNewChat),
            Container(
              height: 38,
              margin: const EdgeInsets.fromLTRB(0, 10, 0, 12),
              padding: const EdgeInsets.symmetric(horizontal: 10),
              decoration: BoxDecoration(
                color: p.surf,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: p.line),
              ),
              child: Row(
                children: [
                  LIcon(Symbols.search_rounded, size: 18, color: p.dim),
                  const SizedBox(width: 8),
                  Expanded(
                    child: TextField(
                      controller: _search,
                      onChanged: (_) => setState(() {}),
                      style: SoraType.ui(13.5, color: p.ink),
                      cursorColor: p.acc,
                      decoration: InputDecoration.collapsed(
                        hintText: s.searchConv,
                        hintStyle: SoraType.ui(13.5, color: p.dim),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            for (final e in desktopNav(s, widget.unread)) ...[
              _NavItem(entry: e, on: widget.current == e.screen, onTap: () => widget.onSelect(e.screen)),
              const SizedBox(height: 4),
            ],
            Padding(padding: const EdgeInsets.fromLTRB(10, 12, 10, 6), child: MonoLabel(s.recent)),
            Expanded(
              child: ListView.separated(
                padding: EdgeInsets.zero,
                itemCount: recent.length,
                separatorBuilder: (_, _) => const SizedBox(height: 1),
                // rows keep their place by id, so a new chat fades in at the top and the rest just move
                findItemIndexCallback: (key) {
                  final i = recent.indexWhere((c) => ValueKey(c['id']) == key);
                  return i < 0 ? null : i;
                },
                itemBuilder: (_, i) {
                  final c = recent[i];
                  final id = c['id'] as String;
                  return Rise(
                    key: ValueKey(id),
                    duration: const Duration(milliseconds: 260),
                    offset: 4,
                    child: _RecentRow(
                      title: (c['title'] as String?)?.trim().isNotEmpty == true ? c['title'] as String : s.newChat,
                      when: s.ago(DateTime.tryParse(c['updated_at'] as String? ?? '')?.toLocal()),
                      on: widget.current == SoraScreen.chat && widget.openConversationId == id,
                      onTap: () => widget.onOpenConversation(id),
                      onDelete: () => widget.onDeleteConversation(id),
                    ),
                  );
                },
              ),
            ),
            Container(
              padding: const EdgeInsets.fromLTRB(6, 10, 6, 0),
              decoration: BoxDecoration(
                border: Border(top: BorderSide(color: p.line)),
              ),
              child: Row(
                children: [
                  Container(
                    width: 32,
                    height: 32,
                    decoration: BoxDecoration(
                      color: p.accSoft,
                      shape: BoxShape.circle,
                      border: Border.all(color: p.accLine),
                    ),
                    alignment: Alignment.center,
                    child: Text(
                      widget.ownerName.isEmpty ? 'L' : widget.ownerName.characters.first.toUpperCase(),
                      style: SoraType.ui(13, weight: FontWeight.w600, color: p.acc, height: 1),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          widget.ownerName,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: SoraType.ui(13.5, weight: FontWeight.w600, color: p.ink, height: 1.3),
                        ),
                        if (widget.ownerEmail != null)
                          Text(
                            widget.ownerEmail!,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: SoraType.ui(11.5, color: p.dim, height: 1.3),
                          ),
                      ],
                    ),
                  ),
                  _GhostIcon(
                    icon: Symbols.settings_rounded,
                    tooltip: s.settings,
                    size: 34,
                    on: widget.current == SoraScreen.settings,
                    onTap: () => widget.onSelect(SoraScreen.settings),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The 64px rail the sidebar collapses to: show, New chat, the nav icons, settings.
class DesktopRail extends StatelessWidget {
  const DesktopRail({
    super.key,
    required this.current,
    required this.unread,
    required this.onSelect,
    required this.onNewChat,
    required this.onShow,
  });

  final SoraScreen current;
  final int unread;
  final ValueChanged<SoraScreen> onSelect;
  final VoidCallback onNewChat, onShow;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    return SizedBox(
      width: 64,
      child: Padding(
        padding: const EdgeInsets.only(top: 14, bottom: 12),
        child: Column(
          children: [
            PanelToggle(icon: Symbols.left_panel_open_rounded, tooltip: s.showSidebar, onTap: onShow),
            const SizedBox(height: 12),
            Hover(
              tooltip: s.newChat,
              onTap: onNewChat,
              builder: (_, hover) => Glass(
                width: 42,
                height: 42,
                radius: 14,
                fill: hover ? p.surf2 : null,
                child: Center(child: LIcon(Symbols.edit_square_rounded, size: 20, color: p.acc)),
              ),
            ),
            const SizedBox(height: 12),
            for (final e in desktopNav(s, unread)) ...[
              Hover(
                tooltip: e.label,
                onTap: () => onSelect(e.screen),
                builder: (_, hover) {
                  final on = current == e.screen;
                  return Stack(
                    children: [
                      _Highlight(
                        on: on,
                        hover: hover,
                        radius: 12,
                        child: SizedBox(
                          width: 42,
                          height: 42,
                          child: Center(
                            child: LIcon(e.icon, size: 19, color: on ? p.acc : p.dim, fill: on),
                          ),
                        ),
                      ),
                      if (e.badge > 0) Positioned(top: 4, right: 4, child: PillBadge(count: e.badge, small: true)),
                    ],
                  );
                },
              ),
              const SizedBox(height: 4),
            ],
            const Spacer(),
            _GhostIcon(
              icon: Symbols.settings_rounded,
              tooltip: s.settings,
              size: 42,
              radius: 12,
              on: current == SoraScreen.settings,
              onTap: () => onSelect(SoraScreen.settings),
            ),
          ],
        ),
      ),
    );
  }
}

/// `--surf2` + `--hi` behind the selected nav item; a fainter `--surf` on hover.
class _Highlight extends StatelessWidget {
  const _Highlight({required this.on, required this.hover, required this.radius, required this.child});

  final bool on, hover;
  final double radius;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return AnimatedContainer(
      duration: const Duration(milliseconds: 150),
      decoration: BoxDecoration(
        color: on ? p.surf2 : (hover ? p.surf : p.surf.withAlpha(0)),
        borderRadius: BorderRadius.circular(radius),
        boxShadow: on && p.hi.outer != null ? [p.hi.outer!] : null,
      ),
      child: child,
    );
  }
}

class _NewChatButton extends StatelessWidget {
  const _NewChatButton({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    return Hover(
      onTap: onTap,
      builder: (_, hover) => Glass(
        height: 42,
        radius: 14,
        fill: hover ? p.surf2 : null,
        padding: const EdgeInsets.only(left: 12, right: 10),
        child: Row(
          children: [
            LIcon(Symbols.edit_square_rounded, size: 19, color: p.acc),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                s.newChat,
                style: SoraType.ui(14.5, weight: FontWeight.w500, color: p.ink),
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: p.line),
              ),
              child: Text(
                'Ctrl N',
                style: SoraType.mono(10.5, weight: FontWeight.w500, spacing: 0, color: p.dim),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.entry, required this.on, required this.onTap});

  final NavEntry entry;
  final bool on;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Hover(
      onTap: onTap,
      builder: (_, hover) => _Highlight(
        on: on,
        hover: hover,
        radius: 11,
        child: SizedBox(
          height: 38,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10),
            child: Row(
              children: [
                LIcon(entry.icon, size: 19, color: on ? p.acc : p.dim, fill: on),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    entry.label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: SoraType.ui(14, weight: on ? FontWeight.w600 : FontWeight.w500, color: p.ink),
                  ),
                ),
                if (entry.badge > 0) PillBadge(count: entry.badge),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// A Recent conversation; on hover its time gives way to a bin.
class _RecentRow extends StatelessWidget {
  const _RecentRow({required this.title, required this.when, required this.on, required this.onTap, required this.onDelete});

  final String title, when;
  final bool on;
  final VoidCallback onTap, onDelete;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Hover(
      onTap: onTap,
      builder: (_, hover) => AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        height: 34,
        padding: const EdgeInsets.symmetric(horizontal: 10),
        decoration: BoxDecoration(color: on ? p.surf2 : (hover ? p.surf : p.surf.withAlpha(0)), borderRadius: BorderRadius.circular(10)),
        child: Row(
          children: [
            Expanded(
              child: Text(
                title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: SoraType.ui(13.5, weight: on ? FontWeight.w600 : FontWeight.w400, color: on || hover ? p.ink : p.dim),
              ),
            ),
            const SizedBox(width: 8),
            if (hover)
              Hover(
                tooltip: S.of(context).del,
                onTap: onDelete,
                builder: (_, over) => SizedBox(
                  width: 24,
                  height: 24,
                  child: Center(child: LIcon(Symbols.delete_rounded, size: 16, color: over ? p.err : p.dim)),
                ),
              )
            else
              Text(when, style: SoraType.ui(11, color: p.dim)),
          ],
        ),
      ),
    );
  }
}

/// Transparent round/rounded icon button (settings in the footer and the rail).
class _GhostIcon extends StatelessWidget {
  const _GhostIcon({required this.icon, required this.tooltip, required this.size, required this.onTap, this.radius, this.on = false});

  final IconData icon;
  final String tooltip;
  final double size;
  final double? radius;
  final bool on;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Hover(
      tooltip: tooltip,
      onTap: onTap,
      builder: (_, hover) => AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        width: size,
        height: size,
        decoration: BoxDecoration(
          color: on ? p.surf2 : (hover ? p.surf : p.surf.withAlpha(0)),
          borderRadius: BorderRadius.circular(radius ?? size / 2),
        ),
        alignment: Alignment.center,
        child: LIcon(icon, size: 20, color: on ? p.acc : (hover ? p.ink : p.dim), fill: on),
      ),
    );
  }
}
