import 'dart:convert';
import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:material_symbols_icons/symbols.dart';
import 'package:share_plus/share_plus.dart';

import '../brand/sora_logo.dart';
import '../core/api.dart';
import '../core/session.dart';
import '../shell/layout.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../voice/speaker.dart';
import '../widgets/sora_widgets.dart';
import '../widgets/markdown_lite.dart';
import '../widgets/overlays.dart';
import '../phone/phone_actions.dart';
import 'chat_activity.dart';
import 'chat_models.dart';
import 'chat_widgets.dart';

export 'chat_models.dart' show toolLabel;

/// Chat — the app's home. Glass header (menu, title, export, new chat), the conversation with tool
/// chips, approval cards and reply actions, and the composer (attach, message, mic → voice, send).
///
/// On desktop the menu and new-chat buttons live in the sidebar, so the header carries the title on
/// the left with Voice and Export; the conversation keeps to 720px and Enter sends (Shift+Enter for a
/// new line). [activity] feeds the Details panel.
class ChatScreen extends StatefulWidget {
  const ChatScreen({
    super.key,
    required this.session,
    required this.api,
    required this.onMenu,
    required this.onVoice,
    this.unread = 0,
    this.activity,
  });

  final Session session;
  final SoraApi api;
  final VoidCallback onMenu, onVoice;
  final int unread;
  final ChatActivity? activity;

  @override
  State<ChatScreen> createState() => ChatScreenState();
}

class ChatScreenState extends State<ChatScreen> {
  SoraPalette get p => SoraPalette.of(context);
  S get s => S.of(context);
  bool get _desk => SoraLayout.isDesktop(context);

  final _msgs = <ChatMessage>[];
  final _input = TextEditingController();
  final _focus = FocusNode();
  final _scroll = ScrollController();
  late final _speaker = Speaker(widget.api, widget.session);
  String? _title;
  bool _busy = false, _loading = false, _nearBottom = true;
  int _view = 0; // another conversation (or a new chat) on screen: it fades in
  int _loaded = 0; // messages that came with the conversation; the ones after rise in
  int? _reading;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_onScroll);
    reload();
  }

  // Every change to the conversation is also news for the Details panel.
  @override
  void setState(VoidCallback fn) {
    super.setState(fn);
    widget.activity?.publish(_msgs, _decide, title: _title);
  }

  @override
  void dispose() {
    _speaker.dispose();
    _input.dispose();
    _focus.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (!_scroll.hasClients) return;
    final near = _scroll.position.maxScrollExtent - _scroll.offset < 120;
    if (near != _nearBottom) setState(() => _nearBottom = near);
  }

  int get _pending => _msgs.fold(0, (n, m) => n + m.approvals.where((a) => a.status == ApprovalStatus.pending).length);

  // ------------------------------------------------------------------ history

  /// Loads the session's current conversation (after voice added to it, or on start).
  Future<void> reload() async {
    if (_busy) return;
    final id = widget.session.conversationId;
    setState(() {
      _msgs.clear();
      _title = null;
      _loading = id != null; // straight to the spinner (no flash of the empty "new chat" screen)
      _view++;
      _loaded = 0;
    });
    if (id == null) return;
    try {
      final conv = await widget.api.conversation(id);
      _title = conv['title'] as String?;
      ChatMessage? lastSora;
      String? lastUser;
      for (final m in conv['messages'] as List) {
        final text = (m['content'] as String? ?? '').trim();
        if (text.isEmpty) continue;
        if (m['role'] == 'user') {
          lastUser = text;
          _msgs.add(ChatMessage.user(text));
        } else {
          _msgs.add(lastSora = ChatMessage.sora(prompt: lastUser)..text = text);
        }
      }
      final pending = (conv['pending_actions'] as List).map((a) => Approval(Map<String, dynamic>.from(a as Map)));
      if (pending.isNotEmpty) {
        if (lastSora == null || !identical(_msgs.last, lastSora)) _msgs.add(lastSora = ChatMessage.sora(prompt: lastUser));
        lastSora.approvals.addAll(pending);
      }
    } on ApiException catch (e) {
      if (e.status == 404) await widget.session.setConversation(null);
      if (e.unauthorized) await widget.session.signOut();
    } catch (_) {}
    if (mounted) {
      setState(() {
        _loading = false;
        _loaded = _msgs.length;
      });
    }
    _toBottom(jump: true);
  }

  Future<void> openConversation(String id) async {
    await widget.session.setConversation(id);
    await reload();
  }

  Future<void> newChat() async {
    if (_busy) return;
    await _speaker.stop();
    await widget.session.setConversation(null);
    setState(() {
      _msgs.clear();
      _title = null;
      _input.clear();
      _view++;
      _loaded = 0;
    });
    _focus.requestFocus();
  }

  void _toBottom({bool jump = false}) => WidgetsBinding.instance.addPostFrameCallback((_) {
    if (!_scroll.hasClients) return;
    final end = _scroll.position.maxScrollExtent;
    jump ? _scroll.jumpTo(end) : _scroll.animateTo(end, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
  });

  bool _following = false;

  /// While a reply streams in: keep its end in view, once per frame (a new 250 ms scroll animation
  /// for every word would restart each other and judder).
  void _follow() {
    if (_following) return;
    _following = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _following = false;
      if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
    });
  }

  // ------------------------------------------------------------------ talking to Sora

  Future<void> _send([String? preset]) async {
    final text = (preset ?? _input.text).trim();
    if (text.isEmpty || _busy) return;
    _input.clear();
    // A pending approval is answered by the server when the owner types yes/no; the cards follow
    // through the action_resolved events.
    setState(() => _msgs.add(ChatMessage.user(text)));
    await _run(widget.api.chat(text, conversationId: widget.session.conversationId), prompt: text);
  }

  Future<void> _decide(Approval a, bool approve) async {
    if (_busy || a.status != ApprovalStatus.pending) return;
    setState(() => a.status = approve ? ApprovalStatus.busy : ApprovalStatus.cancelled);
    await _run(widget.api.decide(a.id, approve));
  }

  Future<void> _regenerate(ChatMessage m) async {
    final prompt = m.prompt;
    if (prompt == null || _busy) return;
    setState(() => _msgs.remove(m));
    await _run(widget.api.chat(prompt, conversationId: widget.session.conversationId), prompt: prompt);
  }

  Future<void> _run(Stream<AgentEvent> events, {String? prompt}) async {
    final m = ChatMessage.sora(prompt: prompt)..working = true;
    setState(() {
      _busy = true;
      _msgs.add(m);
    });
    _toBottom();
    try {
      await for (final e in events) {
        switch (e.type) {
          case 'conversation':
            await widget.session.setConversation(e.data['id'] as String?);
            _title ??= e.data['title'] as String?;
          case 'delta':
            m.live += e.data['text'] as String? ?? '';
          case 'message':
            final content = (e.data['content'] as String? ?? '').trim();
            m.committed = [m.committed, content].where((t) => t.isNotEmpty).join('\n\n');
            m.live = '';
          case 'tool_start':
            m.toolStarted(e.data['name'] as String? ?? '');
          case 'tool_result':
            m.toolFinished(e.data['name'] as String? ?? '', e.data['ok'] == true);
          case 'confirmation_required':
            m.approvals.add(Approval(e.data));
          case 'action_resolved':
            _resolve(e.data['action_id'] as String?, e.data['status'] as String?);
          case 'client_action':
            // Sora asked this phone to do something (open an app, volume...): do it; say only if it failed.
            final problem = await runPhoneAction(
              e.data['action'] as String? ?? '',
              Map<String, dynamic>.from(e.data['params'] as Map? ?? const {}),
            );
            if (problem != null && mounted) showToast(context, problem);
          case 'error':
            m.error = e.data['message'] as String? ?? s.genericError;
        }
        if (mounted) setState(() {});
        if (_nearBottom) _follow();
      }
    } on ApiException catch (e) {
      if (e.unauthorized) {
        await widget.session.signOut();
        return;
      }
      m.error = e.message;
    } catch (_) {
      m.error = s.serverUnreachable;
    }
    if (!mounted) return;
    setState(() {
      m.working = false;
      // Anything still "busy" didn't get an answer from the server.
      for (final a in _msgs.expand((x) => x.approvals)) {
        if (a.status == ApprovalStatus.busy && m.error != null) a.status = ApprovalStatus.failed;
      }
      if (m.text.isEmpty && m.tools.isEmpty && m.approvals.isEmpty && m.error == null) _msgs.remove(m);
      _busy = false;
    });
    _toBottom();
  }

  void _resolve(String? actionId, String? status) {
    for (final a in _msgs.expand((x) => x.approvals)) {
      if (a.id != actionId) continue;
      a.status = switch (status) {
        'confirmed' => ApprovalStatus.done,
        'failed' => ApprovalStatus.failed,
        _ => ApprovalStatus.cancelled,
      };
    }
  }

  // ------------------------------------------------------------------ actions

  Future<void> _readAloud(ChatMessage m) async {
    await _speaker.stop();
    if (_reading == m.id) {
      setState(() => _reading = null);
      return;
    }
    setState(() => _reading = m.id);
    await _speaker.speak(m.text);
    if (mounted && _reading == m.id) setState(() => _reading = null);
  }

  String _transcript() =>
      _msgs.where((m) => m.text.isNotEmpty).map((m) => '${m.fromUser ? s.you : 'Sora'}:\n${stripMarkdown(m.text)}').join('\n\n');

  void _openExport() => showSoraSheet<void>(
    context,
    title: s.exportTitle,
    builder: (ctx) => Column(
      children: [
        SheetItem(
          icon: Symbols.picture_as_pdf_rounded,
          label: s.expPdf,
          onTap: () {
            Navigator.pop(ctx);
            showToast(context, s.comingSoon);
          },
        ),
        SheetItem(
          icon: Symbols.article_rounded,
          label: s.expTxt,
          onTap: () async {
            Navigator.pop(ctx);
            final name = '${(_title ?? 'Sora chat').replaceAll(RegExp(r'[^\w\- ঀ-৿]'), '').trim()}.txt';
            await SharePlus.instance.share(
              ShareParams(
                files: [XFile.fromData(utf8.encode(_transcript()), mimeType: 'text/plain', name: name)],
                fileNameOverrides: [name],
              ),
            );
          },
        ),
        SheetItem(
          icon: Symbols.content_copy_rounded,
          label: s.expCopy,
          onTap: () async {
            Navigator.pop(ctx);
            await Clipboard.setData(ClipboardData(text: _transcript()));
            if (mounted) showToast(context, s.copied);
          },
        ),
      ],
    ),
  );

  void _openAttach() => showSoraSheet<void>(
    context,
    title: s.attachTitle,
    builder: (ctx) => Row(
      children: [
        for (final (i, (icon, label)) in [
          (Symbols.photo_camera_rounded, s.camera),
          (Symbols.image_rounded, s.photos),
          (Symbols.description_rounded, s.files),
        ].indexed) ...[
          if (i > 0) const SizedBox(width: 10),
          Expanded(
            child: SheetTile(
              icon: icon,
              label: label,
              onTap: () {
                Navigator.pop(ctx);
                showToast(context, s.comingSoon);
              },
            ),
          ),
        ],
      ],
    ),
  );

  // ------------------------------------------------------------------ layout

  @override
  Widget build(BuildContext context) {
    final top = MediaQuery.paddingOf(context).top;
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SoraBackground(
        child: Column(
          children: [
            Expanded(
              child: Stack(
                children: [
                  Positioned.fill(
                    child: LayoutBuilder(
                      builder: (_, c) {
                        _listWidth = c.maxWidth;
                        // Fades in when what's shown changes (spinner, empty, the messages), not
                        // while a reply streams. Only the new one is kept: two lists at once would
                        // share the scroll controller.
                        return AnimatedSwitcher(
                          duration: const Duration(milliseconds: 220),
                          switchInCurve: Curves.easeOutCubic,
                          layoutBuilder: (current, _) => current ?? const SizedBox.shrink(),
                          child: KeyedSubtree(key: ValueKey((_view, _loading, _msgs.isEmpty)), child: _list(top)),
                        );
                      },
                    ),
                  ),
                  Positioned(left: 0, right: 0, top: 0, child: _header(top)),
                  if (_pending > 0 && !_nearBottom) Positioned(left: 0, right: 0, bottom: 6, child: Center(child: _pendingPill())),
                ],
              ),
            ),
            SafeArea(
              top: false,
              child: _desk
                  ? Center(
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 776),
                        child: Padding(padding: const EdgeInsets.fromLTRB(8, 0, 8, 10), child: _composer()),
                      ),
                    )
                  : _composer(),
            ),
          ],
        ),
      ),
    );
  }

  /// Sticky glass header that fades out at its bottom edge.
  Widget _header(double top) => Stack(
    children: [
      // `mask-image: linear-gradient(#000 62%, transparent)` over a blurred `--headGlass` layer. A mask
      // can't wrap a backdrop filter here, so the fade is drawn as strips whose blur and tint step down.
      Positioned.fill(
        child: IgnorePointer(
          child: BackdropGroup(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // four steps (each blur is a pass over what's behind; they share one read of it)
                for (final (flex, k) in [(62, 1.0), (13, .66), (13, .33), (12, .1)])
                  Expanded(
                    flex: flex,
                    child: ClipRect(
                      child: BackdropFilter.grouped(
                        filter: ImageFilter.blur(sigmaX: 24 * k, sigmaY: 24 * k, tileMode: TileMode.clamp),
                        child: ColoredBox(color: p.headGlass.withValues(alpha: p.headGlass.a * k)),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
      if (_desk)
        _deskHeaderRow()
      else
        Padding(
          padding: EdgeInsets.fromLTRB(12, top + 6, 12, 24),
          child: SizedBox(
            height: 42,
            child: Stack(
              children: [
                Row(
                  children: [
                    GlassIconButton(icon: Symbols.menu_rounded, tooltip: s.menu, onTap: widget.onMenu, badge: widget.unread, iconSize: 21),
                    const Spacer(),
                    GlassIconButton(
                      icon: Symbols.ios_share_rounded,
                      tooltip: s.export,
                      onTap: _msgs.isEmpty ? null : _openExport,
                      iconSize: 20,
                    ),
                    const SizedBox(width: 8),
                    GlassIconButton(icon: Symbols.edit_square_rounded, tooltip: s.newChat, onTap: _busy ? null : newChat, iconSize: 20),
                  ],
                ),
                Positioned(
                  left: 104,
                  right: 104,
                  top: 0,
                  bottom: 0,
                  child: IgnorePointer(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text(
                          _title ?? s.newChat,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: SoraType.ui(15.5, weight: FontWeight.w600, color: p.ink),
                        ),
                        Text('${s.chat} · Sora', style: SoraType.ui(11.5, color: p.dim)),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
    ],
  );

  /// Desktop header: title and "Chat · Sora" on the left; Voice and Export on the right.
  Widget _deskHeaderRow() => Padding(
    padding: const EdgeInsets.fromLTRB(18, 12, 18, 26),
    child: Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                _title ?? s.newChat,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: SoraType.ui(15.5, weight: FontWeight.w600, color: p.ink),
              ),
              Text('${s.chat} · Sora', style: SoraType.ui(11.5, color: p.dim)),
            ],
          ),
        ),
        GlassIconButton(icon: Symbols.graphic_eq_rounded, tooltip: s.voice, size: 38, iconSize: 19, onTap: widget.onVoice),
        const SizedBox(width: 8),
        GlassIconButton(
          icon: Symbols.ios_share_rounded,
          tooltip: s.export,
          size: 38,
          iconSize: 18,
          onTap: _msgs.isEmpty ? null : _openExport,
        ),
      ],
    ),
  );

  /// Side padding that centres the conversation at [_maxWidth] on desktop.
  static const _maxWidth = 720.0;
  double _listWidth = 0;
  double _side(double width, double phone) => _desk ? ((width - _maxWidth) / 2).clamp(28.0, double.infinity) : phone;

  Widget _list(double top) {
    if (_loading) return Center(child: Spinner(size: 22, color: p.acc));
    if (_msgs.isEmpty) return _empty(top);
    return SelectionArea(
      child: ListView.separated(
        controller: _scroll,
        padding: _desk
            ? EdgeInsets.fromLTRB(_side(_listWidth, 14), 76, _side(_listWidth, 14), 16)
            : EdgeInsets.fromLTRB(14, top + 70, 14, 14),
        itemCount: _msgs.length,
        separatorBuilder: (_, _) => const SizedBox(height: 18),
        itemBuilder: (_, i) {
          final m = _msgs[i];
          final turn = m.fromUser ? _userBubble(m) : _soraTurn(m, i == _msgs.length - 1);
          // a message sent or received now rises in; the history is just there
          return KeyedSubtree(
            key: ValueKey(m.id),
            child: i >= _loaded ? Rise(duration: const Duration(milliseconds: 320), offset: 6, child: turn) : turn,
          );
        },
      ),
    );
  }

  Widget _empty(double top) => ListView(
    padding: _desk ? EdgeInsets.fromLTRB(_side(_listWidth, 18), 76, _side(_listWidth, 18), 16) : EdgeInsets.fromLTRB(18, top + 70, 18, 16),
    children: [
      SizedBox(height: MediaQuery.sizeOf(context).height * (_desk ? .12 : .14)),
      Center(
        child: Rise(duration: const Duration(milliseconds: 500), child: const SoraMark(size: 54)),
      ),
      const SizedBox(height: 14),
      Rise(
        duration: const Duration(milliseconds: 500),
        delay: const Duration(milliseconds: 80),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 290),
            child: Text(
              s.greeting,
              textAlign: TextAlign.center,
              style: SoraType.ui(24, weight: FontWeight.w500, color: p.ink, height: 1.3),
            ),
          ),
        ),
      ),
      const SizedBox(height: 26),
      Center(child: MonoLabel(s.tryAsk, size: 10, weight: FontWeight.w500, spacing: .14)),
      const SizedBox(height: 14),
      for (final (i, (icon, text)) in s.suggestions.indexed) ...[
        if (i > 0) const SizedBox(height: 8),
        Rise(
          duration: const Duration(milliseconds: 450),
          delay: Duration(milliseconds: 60 * i),
          child: Pressable(
            onTap: () => _send(text),
            child: Glass(
              radius: 16,
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              child: Row(
                children: [
                  LIcon(_suggestionIcon(icon), size: 19, color: p.acc),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(text, style: SoraType.ui(14, color: p.ink, height: 1.4)),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    ],
  );

  static IconData _suggestionIcon(String name) => switch (name) {
    'calendar_month' => Symbols.calendar_month_rounded,
    'mail' => Symbols.mail_rounded,
    'alarm' => Symbols.alarm_rounded,
    _ => Symbols.event_note_rounded,
  };

  Widget _userBubble(ChatMessage m) => Rise(
    child: Align(
      alignment: Alignment.centerRight,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: _desk ? _maxWidth * .84 : MediaQuery.sizeOf(context).width * .84 - 28),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: p.bubble,
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(20),
              topRight: Radius.circular(20),
              bottomLeft: Radius.circular(20),
              bottomRight: Radius.circular(6),
            ),
          ),
          child: Text(m.text, style: SoraType.ui(15, color: p.bubbleInk, height: 1.5)),
        ),
      ),
    ),
  );

  Widget _soraTurn(ChatMessage m, bool last) {
    final parts = <Widget>[
      if (m.tools.isNotEmpty) Wrap(spacing: 6, runSpacing: 6, children: [for (final c in m.tools.values) ToolChip(chip: c)]),
      if (m.typing) const TypingDots(),
      if (m.text.isNotEmpty) MarkdownLite(m.text),
      if (m.error != null)
        Rise(
          child: NoticeRow(text: m.error!, icon: Symbols.warning_rounded, radius: 14, fontSize: 14),
        ),
      for (final a in m.approvals)
        ApprovalCard(approval: a, onDecide: (yes) => _decide(a, yes), onToggle: () => setState(() => a.expanded = !a.expanded)),
      if (m.done && m.text.isNotEmpty) _actions(m, last),
    ];
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SoraWorkingAvatar(working: m.working),
        const SizedBox(width: 10),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.only(top: 3),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (var i = 0; i < parts.length; i++) ...[if (i > 0) const SizedBox(height: 10), parts[i]],
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _actions(ChatMessage m, bool last) => Transform.translate(
    offset: const Offset(-8, 0),
    child: Row(
      children: [
        GhostIconButton(
          icon: Symbols.content_copy_rounded,
          tooltip: s.copy,
          onTap: () async {
            await Clipboard.setData(ClipboardData(text: stripMarkdown(m.text)));
            if (mounted) showToast(context, s.copied);
          },
        ),
        GhostIconButton(
          icon: Symbols.thumb_up_rounded,
          tooltip: s.goodReply,
          active: m.feedback == 'up',
          onTap: () => setState(() => m.feedback = m.feedback == 'up' ? null : 'up'),
        ),
        GhostIconButton(
          icon: Symbols.thumb_down_rounded,
          tooltip: s.badReply,
          active: m.feedback == 'down',
          onTap: () => setState(() => m.feedback = m.feedback == 'down' ? null : 'down'),
        ),
        GhostIconButton(
          icon: _reading == m.id ? Symbols.stop_circle_rounded : Symbols.volume_up_rounded,
          tooltip: s.readAloud,
          active: _reading == m.id,
          size: 19,
          onTap: () => _readAloud(m),
        ),
        if (_reading == m.id) const Padding(padding: EdgeInsets.only(right: 6), child: EqBars()),
        if (last && m.prompt != null)
          GhostIconButton(icon: Symbols.refresh_rounded, tooltip: s.regenerate, size: 19, onTap: _busy ? null : () => _regenerate(m)),
        GhostIconButton(
          icon: Symbols.share_rounded,
          tooltip: s.share,
          onTap: () => SharePlus.instance.share(ShareParams(text: stripMarkdown(m.text))),
        ),
      ],
    ),
  );

  Widget _pendingPill() => Pressable(
    onTap: _toBottom,
    child: Glass(
      height: 32,
      radius: 16,
      fill: p.glass2,
      borderColor: p.amberLine,
      shadow: true,
      padding: const EdgeInsets.symmetric(horizontal: 14),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 7,
            height: 7,
            decoration: BoxDecoration(color: p.amber, shape: BoxShape.circle),
          ),
          const SizedBox(width: 8),
          Text(
            s.waiting(_pending),
            style: SoraType.ui(13, weight: FontWeight.w600, color: p.amber),
          ),
        ],
      ),
    ),
  );

  Widget _composer() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          GlassIconButton(icon: Symbols.add_rounded, tooltip: s.attach, size: 44, iconSize: 22, onTap: _openAttach),
          const SizedBox(width: 8),
          Expanded(
            child: Glass(
              radius: 22,
              blur: true, // the conversation scrolls under it
              padding: const EdgeInsets.fromLTRB(16, 0, 4, 0),
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 42),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Expanded(
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 10),
                        child: Focus(
                          // Desktop: Enter sends, Shift+Enter starts a new line.
                          onKeyEvent: (_, e) {
                            if (!_desk || e is! KeyDownEvent || e.logicalKey != LogicalKeyboardKey.enter) return KeyEventResult.ignored;
                            if (HardwareKeyboard.instance.isShiftPressed) return KeyEventResult.ignored;
                            _send();
                            return KeyEventResult.handled;
                          },
                          child: TextField(
                            controller: _input,
                            focusNode: _focus,
                            minLines: 1,
                            maxLines: 5,
                            textInputAction: TextInputAction.send,
                            onSubmitted: (_) => _send(),
                            style: SoraType.ui(15, color: p.ink, height: 1.4),
                            decoration: InputDecoration(
                              hintText: s.messageHint,
                              hintStyle: SoraType.ui(15, color: p.faint, height: 1.4),
                              isCollapsed: true,
                              filled: false,
                              border: InputBorder.none,
                              enabledBorder: InputBorder.none,
                              focusedBorder: InputBorder.none,
                            ),
                          ),
                        ),
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.only(bottom: 3),
                      child: Tooltip(
                        message: s.voiceInput,
                        child: Pressable(
                          onTap: widget.onVoice,
                          semanticLabel: s.voiceInput,
                          child: SizedBox(
                            width: 36,
                            height: 36,
                            child: Center(child: LIcon(Symbols.mic_rounded, size: 21, color: p.dim)),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
          const SizedBox(width: 8),
          // Only the send button follows the typing (not the whole conversation).
          ValueListenableBuilder<TextEditingValue>(
            valueListenable: _input,
            builder: (_, value, _) {
              final ready = value.text.trim().isNotEmpty && !_busy;
              return Pressable(
                onTap: ready ? _send : null,
                semanticLabel: s.send,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(color: ready ? p.acc : p.surf2, shape: BoxShape.circle),
                  child: Center(child: LIcon(Symbols.arrow_upward_rounded, size: 22, color: ready ? p.accInk : p.faint)),
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}
