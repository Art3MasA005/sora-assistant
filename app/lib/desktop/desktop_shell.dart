import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../chat/chat_activity.dart';
import '../chat/chat_screen.dart';
import '../connections/connections_screen.dart';
import '../core/api.dart';
import '../core/language_sync.dart';
import '../core/live_events.dart';
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
import '../shell/screen_stack.dart';
import '../shell/screens.dart';
import '../voice/voice_screen.dart';
import '../widgets/list_kit.dart';
import '../widgets/overlays.dart';
import 'desktop_kit.dart';
import 'details_panel.dart';
import 'sidebar.dart';
import 'title_bar.dart';
import 'tray.dart';

/// Signed-in Windows app, per `Sora Desktop.dc.html`: title bar; a 272px sidebar (64px rail when
/// hidden); the main column, where Chat stays alive underneath like on the phone and the other
/// screens keep to 760px; and on Chat and Voice a 300px Details panel (56px rail when hidden).
///
/// Ctrl+N starts a new chat; Esc goes back to Chat.
class DesktopShell extends StatefulWidget {
  const DesktopShell({super.key, required this.session, required this.api});

  final Session session;
  final SoraApi api;

  @override
  State<DesktopShell> createState() => _DesktopShellState();
}

class _DesktopShellState extends State<DesktopShell> {
  final _chat = GlobalKey<ChatScreenState>();
  final _activity = ChatActivity();
  late final _link = ServerLink(widget.session);
  late final _language = LanguageSync(widget.session, widget.api);
  // What the server pushes as it happens: a device coming online or going away, the phone's notifications.
  late final _live = LiveEvents(widget.session);
  StreamSubscription<Map<String, dynamic>>? _liveSub;
  bool _phoneNotifications = false;
  Timer? _poll, _retry;

  SoraScreen _screen = SoraScreen.chat;
  bool _leftMin = false, _rightMin = false, _online = true;
  int _unread = 0;
  List<Map<String, dynamic>>? _conversations;
  Map<String, dynamic>? _pc, _phone;
  String _ownerName = '';
  String? _ownerEmail;

  String? _conversationId, _title;

  @override
  void initState() {
    super.initState();
    _language.start();
    SoraTray.instance.turnOff = () async {
      try {
        await widget.api.stopSora();
      } catch (_) {}
      await SoraTray.instance.quit();
    };
    _conversationId = widget.session.conversationId;
    widget.session.addListener(_onSession);
    widget.session.addListener(_onPhoneNotifications);
    _onPhoneNotifications();
    _liveSub = _live.events.listen((e) {
      if (e['type'] == 'device_status') _loadDevices();
    });
    _live.start();
    _activity.addListener(_onActivity);
    _loadMe();
    _refresh();
    _poll = Timer.periodic(const Duration(seconds: 45), (_) => _refresh());
  }

  @override
  void dispose() {
    _language.stop();
    SoraTray.instance.turnOff = null;
    _poll?.cancel();
    _retry?.cancel();
    widget.session.removeListener(_onSession);
    widget.session.removeListener(_onPhoneNotifications);
    _liveSub?.cancel();
    _live.stop();
    _activity.removeListener(_onActivity);
    _activity.dispose();
    super.dispose();
  }

  // A new or reopened chat moves to the top of Recent; a new chat's title arrives with its first reply.
  void _onSession() {
    if (widget.session.conversationId == _conversationId) return;
    _conversationId = widget.session.conversationId;
    setState(() {});
    _loadConversations();
  }

  // Settings → "Phone notifications in Details": whether that section shows (the live line stays on
  // for the devices either way).
  void _onPhoneNotifications() {
    final on = widget.session.phoneNotifications;
    if (on == _phoneNotifications) return;
    _phoneNotifications = on;
    if (mounted) setState(() {});
  }

  void _onActivity() {
    if (_activity.title == _title) return;
    _title = _activity.title;
    _loadConversations();
  }

  Future<void> _loadMe() async {
    try {
      final me = await widget.api.me();
      final email = me['email'] as String?;
      final name = (me['name'] as String?)?.trim();
      if (!mounted) return;
      setState(() {
        _ownerEmail = email;
        _ownerName = name?.isNotEmpty == true ? name! : (email?.split('@').first ?? 'Sora');
      });
    } catch (_) {
      if (mounted && _ownerName.isEmpty) setState(() => _ownerName = 'Sora');
    }
  }

  DateTime _refreshedAt = DateTime.fromMillisecondsSinceEpoch(0);

  /// Unread count, server status, the online PC and Recent — on start, every 45 s and after
  /// navigating (once the page has slid in, at most every 10 s). When the server doesn't answer,
  /// starts Sora if it is off or finds its new address, and tries again soon. The shell is rebuilt
  /// only when something changed.
  Future<void> _refresh() async {
    _refreshedAt = DateTime.now();
    try {
      final unread = (await widget.api.notifications(unread: true)).length;
      if (mounted && (unread != _unread || !_online)) {
        setState(() {
          _unread = unread;
          _online = true;
        });
      }
    } on ApiException catch (e) {
      if (e.unauthorized) await widget.session.signOut();
      return;
    } catch (_) {
      if (mounted && _online) setState(() => _online = false);
      final back = await _link.recover();
      if (!mounted) return;
      _retry?.cancel();
      _retry = Timer(Duration(seconds: back ? 1 : 10), _refresh);
      return;
    }
    if (_conversations == null) _loadMe(); // the first try at start-up found the server off
    _loadConversations();
    await _loadDevices();
  }

  /// The online PC agent and phone; also as soon as the server says one came or went.
  Future<void> _loadDevices() async {
    try {
      final devices = [for (final d in await widget.api.devices()) Map<String, dynamic>.from(d as Map)];
      final pc = devices.where((d) => d['kind'] == 'pc_agent' && d['online'] == true).firstOrNull;
      final phone = devices.where((d) => d['kind'] == 'android' && d['online'] == true).firstOrNull;
      if (mounted && (_sig(pc) != _sig(_pc) || _sig(phone) != _sig(_phone))) {
        setState(() {
          _pc = pc;
          _phone = phone;
        });
      }
    } catch (_) {}
  }

  static String _sig(Object? value) => jsonEncode(value);

  Future<void> _loadConversations() async {
    try {
      final list = [for (final c in await widget.api.conversations()) Map<String, dynamic>.from(c as Map)];
      if (mounted && _sig(list) != _sig(_conversations)) setState(() => _conversations = list);
    } catch (_) {}
  }

  void _go(SoraScreen screen) {
    if (screen == _screen) return;
    final from = _screen;
    setState(() => _screen = screen);
    // Voice adds to the same conversation; show it when coming back to chat.
    if (screen == SoraScreen.chat && from == SoraScreen.voice) _chat.currentState?.reload();
    // after the page has slid in: a rebuild during the slide would stutter it
    if (DateTime.now().difference(_refreshedAt) > const Duration(seconds: 10)) {
      Timer(const Duration(milliseconds: 400), () {
        if (mounted) _refresh();
      });
    }
  }

  // Built once and reused while nothing it shows changed, so a shell rebuild (a new unread count,
  // the sidebar) doesn't rebuild the whole conversation underneath.
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
        activity: _activity,
        onMenu: () {},
        onVoice: () => _go(SoraScreen.voice),
      );
    }
    return _chatView!;
  }

  Widget? _pageView;
  (SoraScreen, int)? _pageFor;

  Widget _currentPage() {
    if (_pageView == null || _pageFor != (_screen, _unread)) {
      _pageFor = (_screen, _unread);
      _pageView = _page(_screen);
    }
    return _pageView!;
  }

  void _back() => _go(SoraScreen.chat);

  void _newChat() {
    _chat.currentState?.newChat();
    _go(SoraScreen.chat);
  }

  Future<void> _deleteConversation(String id) async {
    final s = S.of(context);
    final ok = await showConfirmSheet(context, title: s.deleteChat, text: s.deleteChatQ, confirm: s.del, danger: true);
    if (!ok || !mounted) return;
    final before = _conversations;
    setState(() => _conversations = [...?_conversations]..removeWhere((c) => c['id'] == id));
    try {
      await widget.api.deleteConversation(id);
    } catch (_) {
      if (!mounted) return;
      setState(() => _conversations = before);
      showToast(context, s.couldntChange);
      return;
    }
    if (id == _conversationId) _chat.currentState?.newChat(); // it was open: start a fresh one
  }

  void _open(String id) {
    _chat.currentState?.openConversation(id);
    _go(SoraScreen.chat);
  }

  Widget _page(SoraScreen screen) => switch (screen) {
    SoraScreen.chat => const SizedBox.shrink(),
    SoraScreen.voice => VoiceScreen(session: widget.session, api: widget.api, unread: _unread, onMenu: () {}, onChat: _back),
    SoraScreen.connections => ConnectionsScreen(api: widget.api, onBack: _back),
    SoraScreen.settings => SettingsScreen(session: widget.session, api: widget.api, onBack: _back, events: _live.events),
    SoraScreen.conversations => ConversationsScreen(api: widget.api, onBack: _back, onOpen: _open, onNewChat: _newChat),
    SoraScreen.notifications => NotificationsScreen(api: widget.api, onBack: _back, onUnreadChanged: _refresh, onOpenChat: _open),
    SoraScreen.reminders => RemindersScreen(api: widget.api, onBack: _back),
    SoraScreen.routines => RoutinesScreen(api: widget.api, onBack: _back),
    SoraScreen.memories => MemoriesScreen(api: widget.api, onBack: _back),
    SoraScreen.people => PeopleScreen(api: widget.api, onBack: _back),
    SoraScreen.knowledge => KnowledgeScreen(api: widget.api, onBack: _back),
    SoraScreen.devices => DevicesScreen(api: widget.api, session: widget.session, onBack: _back, events: _live.events),
  };

  @override
  Widget build(BuildContext context) {
    final onChat = _screen == SoraScreen.chat;
    final hasPanel = onChat || _screen == SoraScreen.voice;

    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.keyN, control: true): _newChat,
        const SingleActivator(LogicalKeyboardKey.escape): _back,
      },
      child: Focus(
        autofocus: true,
        child: DesktopFrame(
          online: _online,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              FoldingPanel(
                folded: _leftMin,
                fullWidth: 272,
                miniWidth: 64,
                mini: DesktopRail(
                  current: _screen,
                  unread: _unread,
                  onSelect: _go,
                  onNewChat: _newChat,
                  onShow: () => setState(() => _leftMin = false),
                ),
                full: DesktopSidebar(
                  current: _screen,
                  unread: _unread,
                  conversations: _conversations,
                  openConversationId: _conversationId,
                  ownerName: _ownerName,
                  ownerEmail: _ownerEmail,
                  onSelect: _go,
                  onNewChat: _newChat,
                  onOpenConversation: _open,
                  onDeleteConversation: _deleteConversation,
                  onHide: () => setState(() => _leftMin = true),
                ),
              ),
              Expanded(
                child: ScreenStack(
                  onChat: onChat,
                  chat: _chatScreen,
                  pageKey: _screen,
                  // the window's own background behind it, so it covers what is underneath
                  page: WindowBackdrop(
                    child: _screen == SoraScreen.voice
                        ? _currentPage()
                        : Align(
                            alignment: Alignment.topCenter,
                            child: ConstrainedBox(
                              constraints: const BoxConstraints(maxWidth: 760),
                              child: Padding(padding: const EdgeInsets.only(top: 18), child: _currentPage()),
                            ),
                          ),
                  ),
                ),
              ),
              SlideAway(
                visible: hasPanel,
                child: FoldingPanel(
                  folded: _rightMin,
                  atLeft: false,
                  fullWidth: 300,
                  miniWidth: 56,
                  mini: DetailsRail(activity: _activity, onShow: () => setState(() => _rightMin = false)),
                  full: DetailsPanel(
                    activity: _activity,
                    api: widget.api,
                    pc: _pc,
                    phone: _phone,
                    onHide: () => setState(() => _rightMin = true),
                    live: _phoneNotifications ? _live : null,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
