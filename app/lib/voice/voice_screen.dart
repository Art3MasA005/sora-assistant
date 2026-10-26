import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../chat/chat_models.dart';
import '../chat/chat_widgets.dart' show ShimmerText;
import '../core/api.dart';
import '../core/session.dart';
import '../l10n/strings.dart';
import '../orb/orb_controller.dart';
import '../orb/particle_orb.dart';
import '../shell/layout.dart';
import '../theme.dart';
import '../widgets/sora_widgets.dart';
import '../widgets/overlays.dart';
import 'voice_controller.dart';
import 'wake_service.dart';

/// Voice, from the design: header, the particle orb, a live transcript (words fade in; older words
/// dim while listening), approval questions as a glass card, and pause / talk / close controls.
class VoiceScreen extends StatefulWidget {
  const VoiceScreen({
    super.key,
    required this.session,
    required this.api,
    required this.onMenu,
    required this.onChat,
    this.unread = 0,
  });

  final Session session;
  final SoraApi api;
  final VoidCallback onMenu, onChat;
  final int unread;

  @override
  State<VoiceScreen> createState() => _VoiceScreenState();
}

class _VoiceScreenState extends State<VoiceScreen> with SingleTickerProviderStateMixin {
  SoraPalette get p => SoraPalette.of(context);
  S get s => S.of(context);

  final orb = OrbController();
  late final VoiceController voice = VoiceController(widget.api, widget.session, orb);
  late final _ping = AnimationController(vsync: this, duration: const Duration(milliseconds: 1600))..repeat();

  @override
  void initState() {
    super.initState();
    WakeService.pause(); // this screen records; the background "Hey Sora" lets go of the mic
    voice.init();
    voice.addListener(_onVoice);
  }

  void _onVoice() {
    if (voice.notes.isNotEmpty && mounted) showToast(context, voice.notes.removeLast());
  }

  @override
  void dispose() {
    _ping.dispose();
    voice.removeListener(_onVoice);
    voice.dispose();
    WakeService.resume();
    super.dispose();
  }

  String _status(OrbState state) {
    if (voice.pending != null) return s.waitAnswer;
    return switch (state) {
      OrbState.idle => s.statusIdle,
      OrbState.listening => s.statusListening,
      OrbState.thinking => s.statusThinking,
      OrbState.speaking => s.statusSpeaking,
      OrbState.error => s.statusError,
    };
  }

  @override
  Widget build(BuildContext context) {
    orb.light = !p.dark; // the orb eases into the other palette when the theme changes
    voice.s = s;
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SoraBackground(
        child: SafeArea(
          child: ListenableBuilder(
            listenable: voice,
            builder: (context, _) => Column(
              children: [
                // On desktop the sidebar has the menu and Chat, so the orb gets the space.
                if (SoraLayout.isDesktop(context)) const SizedBox(height: 16) else _header(),
                Expanded(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(minHeight: 210),
                    child: ParticleOrb(controller: orb, scale: .32),
                  ),
                ),
                ConstrainedBox(
                  constraints: const BoxConstraints(minHeight: 120),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 24),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        if (voice.pending != null) _approval() else _words(),
                        if (voice.state == OrbState.thinking) ...[const SizedBox(height: 10), _working()],
                      ],
                    ),
                  ),
                ),
                _dock(),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _header() => Padding(
    padding: const EdgeInsets.fromLTRB(14, 6, 14, 0),
    child: Row(
      children: [
        GlassIconButton(icon: Symbols.menu_rounded, tooltip: s.menu, size: 44, iconSize: 22, badge: widget.unread, onTap: widget.onMenu),
        Expanded(child: Text('Sora', textAlign: TextAlign.center, style: SoraType.ui(17, weight: FontWeight.w600, color: p.ink))),
        GlassIconButton(icon: Symbols.chat_bubble_rounded, tooltip: s.chat, size: 44, iconSize: 21, onTap: widget.onChat),
      ],
    ),
  );

  /// The transcript, word by word, as in the design: while listening the latest four words are
  /// bright and earlier ones dim; while thinking all sit at .85; a finished reply rests at .45.
  Widget _words() {
    final state = voice.state;
    List<(String, double)> words;
    Color color = p.ink;
    if (state == OrbState.error) {
      words = [(voice.reply, 1)];
      color = p.err;
    } else if (state == OrbState.speaking) {
      final all = voice.reply.split(RegExp(r'\s+'));
      words = [for (final w in all.take(voice.spokenWords.clamp(0, all.length))) (w, 1.0)];
    } else if ((state == OrbState.listening || state == OrbState.thinking) && voice.heard.isNotEmpty) {
      final all = voice.heard.split(RegExp(r'\s+'));
      words = [
        for (final (i, w) in all.indexed) (w, state == OrbState.thinking ? .85 : (i < all.length - 4 ? .34 : 1.0)),
      ];
    } else if (state == OrbState.idle && voice.reply.isNotEmpty) {
      words = [for (final w in voice.reply.split(RegExp(r'\s+'))) (w, .45)];
    } else {
      words = [(s.greeting, 1)];
    }
    final style = SoraType.ui(21, weight: FontWeight.w500, color: color, height: 1.38);
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 330, maxHeight: 176),
      child: SingleChildScrollView(
        reverse: true,
        child: Text.rich(
          TextSpan(
            children: [
              for (final (i, (w, o)) in words.indexed)
                WidgetSpan(
                  alignment: PlaceholderAlignment.baseline,
                  baseline: TextBaseline.alphabetic,
                  child: _WordIn(key: ValueKey('$state$i$w'), opacity: o, child: Text('$w ', style: style)),
                ),
            ],
          ),
          textAlign: TextAlign.center,
          style: style,
        ),
      ),
    );
  }

  Widget _working() => Row(
    mainAxisAlignment: MainAxisAlignment.center,
    children: [
      Spinner(size: 16, color: p.acc, period: const Duration(milliseconds: 1100)),
      const SizedBox(width: 8),
      ShimmerText(voice.activeTool != null ? s.checking(voice.activeTool!) : s.working, style: SoraType.ui(14, color: p.ink)),
    ],
  );

  /// Spoken approval: what Sora wants to do, Yes / No, and a reminder that a spoken yes/no works.
  Widget _approval() {
    final a = Approval(voice.pending!);
    final v = ApprovalView.of(a, s);
    final text = a.summary.trim().split('\n').first;
    return Rise(
      duration: const Duration(milliseconds: 350),
      child: Glass(
        radius: 24,
        fill: p.glass2,
        strong: true,
        blur: false, // it fades in (a blur inside a fade goes dark)
        shadow: true,
        sheen: true,
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Container(
                  width: 30,
                  height: 30,
                  decoration: BoxDecoration(color: p.accSoft, borderRadius: BorderRadius.circular(10), border: Border.all(color: p.accLine)),
                  child: Center(child: LIcon(v.icon, size: 17, color: p.acc, fill: true)),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [MonoLabel(s.needsApproval), Text(v.service, style: SoraType.ui(12.5, color: p.dim))],
                  ),
                ),
                LIcon(Symbols.shield_lock_rounded, size: 18, color: p.dim),
              ],
            ),
            const SizedBox(height: 12),
            Text(text.isEmpty ? v.title : text, style: SoraType.ui(15.5, color: p.ink, height: 1.5)),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(flex: 2, child: GlassButton(label: s.no, onTap: () => voice.decide(false))),
                const SizedBox(width: 10),
                Expanded(flex: 3, child: InkButton(label: s.yes, height: 46, radius: 15, fontSize: 15, onTap: () => voice.decide(true))),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                LIcon(Symbols.mic_rounded, size: 15, color: p.dim),
                const SizedBox(width: 6),
                Flexible(child: Text(s.sayYesNo, style: SoraType.ui(12.5, color: p.dim))),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _dock() {
    final state = voice.state;
    final listening = state == OrbState.listening;
    final speaking = state == OrbState.speaking;
    final thinking = state == OrbState.thinking;
    final error = state == OrbState.error;
    final (bg, fg, icon) = thinking
        ? (p.surf2, p.dim, Symbols.progress_activity_rounded)
        : speaking
        ? (p.ink, p.bg, Symbols.stop_rounded)
        : error
        ? (p.err, Colors.white, Symbols.mic_rounded)
        : (p.acc, p.accInk, listening && voice.pending == null ? Symbols.arrow_upward_rounded : Symbols.mic_rounded);
    return Padding(
      padding: const EdgeInsets.fromLTRB(0, 6, 0, 12),
      child: Column(
        children: [
          ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 20),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: Text(_status(state), textAlign: TextAlign.center, style: SoraType.ui(14, color: p.dim)),
            ),
          ),
          const SizedBox(height: 10),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              GlassIconButton(
                icon: Symbols.pause_rounded,
                tooltip: s.pause,
                size: 54,
                iconSize: 24,
                onTap: listening || speaking ? voice.stop : null,
              ),
              const SizedBox(width: 34),
              SizedBox(
                width: 78,
                height: 78,
                child: Stack(
                  clipBehavior: Clip.none,
                  children: [
                    if (listening)
                      Positioned(
                        left: -6,
                        top: -6,
                        right: -6,
                        bottom: -6,
                        child: AnimatedBuilder(
                          animation: _ping,
                          builder: (_, _) {
                            final t = Curves.easeOut.transform(_ping.value);
                            return Opacity(
                              opacity: .9 * (1 - t),
                              child: Transform.scale(
                                scale: .92 + .48 * t,
                                child: DecoratedBox(
                                  decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: p.acc, width: 1.5)),
                                ),
                              ),
                            );
                          },
                        ),
                      ),
                    Semantics(
                      button: true,
                      label: listening ? s.send : s.talk,
                      child: GestureDetector(
                        onTap: thinking ? null : voice.mainButton,
                        child: AnimatedContainer(
                          duration: const Duration(milliseconds: 250),
                          width: 78,
                          height: 78,
                          decoration: BoxDecoration(
                            color: bg,
                            shape: BoxShape.circle,
                            boxShadow: thinking ? null : [BoxShadow(color: error ? p.errSoft : p.accSoft, spreadRadius: 6)],
                          ),
                          child: Center(
                            child: thinking ? Spinner(size: 32, color: fg) : LIcon(icon, size: 32, color: fg, fill: true),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 34),
              GlassIconButton(icon: Symbols.close_rounded, tooltip: s.cancel, size: 54, iconSize: 24, onTap: voice.cancel),
            ],
          ),
        ],
      ),
    );
  }
}

/// The design's `lw` word entrance: fade in from a 5px blur while rising 3px, then settle at
/// [opacity] (older words dim smoothly).
class _WordIn extends StatefulWidget {
  const _WordIn({super.key, required this.child, required this.opacity});

  final Widget child;
  final double opacity;

  @override
  State<_WordIn> createState() => _WordInState();
}

class _WordInState extends State<_WordIn> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 450))..forward();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedOpacity(
    duration: const Duration(milliseconds: 600),
    opacity: widget.opacity,
    child: AnimatedBuilder(
      animation: _c,
      // fade + rise only: a blur per word, re-rendered every frame, was the heaviest part of the
      // transcript on phones
      builder: (_, child) {
        final t = Curves.ease.transform(_c.value);
        return Transform.translate(offset: Offset(0, 3 * (1 - t)), child: child);
      },
      child: FadeTransition(opacity: CurvedAnimation(parent: _c, curve: Curves.ease), child: widget.child),
    ),
  );
}
