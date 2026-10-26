import 'dart:async';

import 'package:flutter/material.dart';

import '../chat/chat_screen.dart';
import '../connections/connections_screen.dart';
import '../core/api.dart';
import '../core/language_sync.dart';
import '../core/server_link.dart';
import '../core/session.dart';
import '../l10n/strings.dart';
import '../lists/conversations_screen.dart';
import '../lists/devices_screen.dart';
import '../lists/knowledge_screen.dart';
import '../lists/memories_screen.dart';
import '../lists/people_screen.dart';
import '../lists/notifications_screen.dart';
import '../lists/reminders_screen.dart';
import '../lists/routines_screen.dart';
import '../settings/settings_screen.dart';
import '../voice/voice_screen.dart';
import 'screens.dart';
import 'screen_stack.dart';
import 'side_menu.dart';

/// Signed-in app frame. Chat is home and stays alive underneath (so a reply keeps streaming while
/// you look elsewhere); the side menu switches to Voice and the list screens. Back returns to Chat.
class HomeShell extends StatefulWidget {
  const HomeShell({super.key, required this.session, required this.api});

  final Session session;
  final SoraApi api;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  final _chat = GlobalKey<ChatScreenState>();
  final _menuKey = GlobalKey<SideMenuState>();
  SoraScreen _screen = SoraScreen.chat;
  bool _menu = false, _online = true;
  int _unread = 0;
  late final _link = ServerLink(widget.session);
  late final _language = LanguageSync(widget.session, widget.api);
  late final _live = LiveLink(widget.session);
  Timer? _poll, _retry;

  @override
  void initState() {
    super.initState();
    _language.start();
    _refresh();
    _live.start();
    _poll = Timer.periodic(const Duration(seconds: 30), (_) => _refresh());
  }

  @override
  void dispose() {
    _language.stop();
    _poll?.cancel();
    _retry?.cancel();
    _live.stop();
    super.dispose();
  }

  /// Unread notification count for the badges; also tells the menu whether the server is reachable.
  /// When it isn't, looks for it (the PC may have a new address) and tries again soon.
  Future<void> _refresh() async {
    try {
      final unread = (await widget.api.notifications(unread: true)).length;
      // rebuild only for news (a rebuild every 30 s for nothing would also rebuild the chat)
      if (mounted && (unread != _unread || !_online)) {
        setState(() {
          _unread = unread;
          _online = true;
        });
      }
    } on ApiException catch (e) {
      if (e.unauthorized) await widget.session.signOut();
    } catch (_) {
      if (mounted && _online) setState(() => _online = false);
      final back = await _link.recover();
      if (!mounted) return;
      _retry?.cancel();
      _retry = Timer(Duration(seconds: back ? 1 : 10), _refresh);
    }
  }

  void _openMenu() {
    setState(() => _menu = true);
    _refresh();
  }

  void _go(SoraScreen screen) {
    final from = _screen;
    setState(() => _screen = screen);
    // the drawer slides away (then removes itself) while the screen fades in under it
    if (_menu) _menuKey.currentState?.close();
    // Voice adds to the same conversation; show it when coming back to chat.
    if (screen == SoraScreen.chat && from == SoraScreen.voice) _chat.currentState?.reload();
  }

  void _back() => _go(SoraScreen.chat);

  // Built once and reused while the unread count is the same, so opening the menu or a page
  // doesn't rebuild the whole conversation underneath.
  Widget? _chatView;
  int? _chatUnread;

  Widget get _chatScreen {
    if (_chatView == null || _chatUnread != _unread) {
      _chatUnread = _unread;
      _chatView = ChatScreen(
        key: _chat,
        session: widget.session,
        api: widget.api,
        unread: _unread,
        onMenu: _openMenu,
        onVoice: () => _go(SoraScreen.voice),
      );
    }
    return _chatView!;
  }

  Widget? _pageView;
  (SoraScreen, int, String)? _pageFor;

  Widget _currentPage(S s) {
    if (_pageView == null || _pageFor != (_screen, _unread, s.code)) {
      _pageFor = (_screen, _unread, s.code);
      _pageView = _page(_screen, s);
    }
    return _pageView!;
  }

  Widget _page(SoraScreen screen, S s) => switch (screen) {
    SoraScreen.chat => const SizedBox.shrink(),
    SoraScreen.voice => VoiceScreen(session: widget.session, api: widget.api, unread: _unread, onMenu: _openMenu, onChat: _back),
    SoraScreen.connections => ConnectionsScreen(api: widget.api, onBack: _back),
    SoraScreen.settings => SettingsScreen(session: widget.session, api: widget.api, onBack: _back, events: _live.events),
    SoraScreen.conversations => ConversationsScreen(
      api: widget.api,
      onBack: _back,
      onOpen: (id) {
        _chat.currentState?.openConversation(id);
        _go(SoraScreen.chat);
      },
      onNewChat: () {
        _chat.currentState?.newChat();
        _go(SoraScreen.chat);
      },
    ),
    SoraScreen.notifications => NotificationsScreen(
      api: widget.api,
      onBack: _back,
      onUnreadChanged: _refresh,
      onOpenChat: (id) {
        _chat.currentState?.openConversation(id);
        _go(SoraScreen.chat);
      },
    ),
    SoraScreen.reminders => RemindersScreen(api: widget.api, onBack: _back),
    SoraScreen.routines => RoutinesScreen(api: widget.api, onBack: _back),
    SoraScreen.memories => MemoriesScreen(api: widget.api, onBack: _back),
    SoraScreen.people => PeopleScreen(api: widget.api, onBack: _back),
    SoraScreen.knowledge => KnowledgeScreen(api: widget.api, onBack: _back),
    SoraScreen.devices => DevicesScreen(api: widget.api, session: widget.session, onBack: _back, events: _live.events),
  };

  @override
  Widget build(BuildContext context) {
    final s = S.of(context);
    final onChat = _screen == SoraScreen.chat;
    return PopScope(
      canPop: onChat && !_menu,
      onPopInvokedWithResult: (didPop, _) {
        if (didPop) return;
        if (_menu) {
          _menuKey.currentState?.close();
        } else {
          _back();
        }
      },
      child: Stack(
        children: [
          // each screen paints its own background, so it covers Chat as it fades in
          ScreenStack(onChat: onChat, chat: _chatScreen, pageKey: _screen, page: _currentPage(s)),
          if (_menu)
            Material(
              type: MaterialType.transparency,
              child: SideMenu(
                key: _menuKey,
                session: widget.session,
                current: _screen,
                online: _online,
                unread: _unread,
                onSelect: _go,
                onNewChat: () {
                  _chat.currentState?.newChat();
                  _go(SoraScreen.chat);
                },
                onClose: () => setState(() => _menu = false),
              ),
            ),
        ],
      ),
    );
  }
}
