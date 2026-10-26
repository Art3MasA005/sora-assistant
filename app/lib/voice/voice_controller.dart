import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';

import '../core/api.dart';
import '../core/session.dart';
import '../l10n/strings.dart';
import '../orb/orb_controller.dart';
import '../chat/chat_models.dart' show toolLabel;
import '../widgets/markdown_lite.dart';
import '../phone/phone_actions.dart';
import 'speaker.dart';
import 'voice_input.dart';

/// Listen → ask the agent (voice mode) → speak the reply, keeping the orb's state and loudness in step.
///
/// A conversation keeps going hands-free: after each answer it listens again, until the owner says
/// nothing for a few seconds, says bye / thanks / ধন্যবাদ, or taps pause or close.
///
/// Listening records the owner and has the server's Whisper write it down (Bangla, English or a mix,
/// the same on every phone). When the server has no speech-to-text, the phone's own recogniser is used.
class VoiceController extends ChangeNotifier {
  VoiceController(this.api, this.session, this.orb) : speaker = Speaker(api, session);

  final SoraApi api;
  final Session session;
  final OrbController orb;
  final Speaker speaker;
  final _stt = SpeechToText();
  // A thinking pause mid-sentence shouldn't end the turn; nothing said for 8 s does.
  final _rec = VoiceRecorder(silence: const Duration(milliseconds: 1600));
  int _emptyTries = 0; // follow-ups in a row that heard only noise

  bool sttReady = false;

  /// Speech-to-text on the server (Whisper) instead of the phone's recogniser.
  bool _serverStt = false;

  /// Copy in the app's language; the screen keeps this current.
  S s = S.en;
  bool bangla = false;
  String? _bnLocale, _enLocale;

  /// In a hands-free conversation (listens again after every answer).
  bool conversing = false;

  String heard = '';
  String reply = ''; // empty: the screen shows its greeting

  /// While speaking: how many words of [reply] have been said (the transcript reveals them).
  int spokenWords = 0;

  /// The service Sora is using right now ("Calendar"), for "Checking Calendar…".
  String? activeTool;
  Map<String, dynamic>? pending; // {action_id, summary, tool}
  final List<String> notes = []; // phone actions this build can't perform yet
  bool _sending = false;
  bool _finishing = false;
  Timer? _speechEnvelope;
  bool _disposed = false;

  OrbState get state => orb.state;

  Future<void> init() async {
    try {
      _serverStt = (await api.health())['stt_ready'] == true;
    } catch (_) {
      _serverStt = false;
    }
    if (_serverStt) {
      sttReady = await _rec.hasPermission();
      _notify();
      return;
    }
    try {
      sttReady = await _stt.initialize(
        onError: (e) {
          // Silence or unrecognised speech isn't a fault: go back to idle with a gentle note.
          if (e.errorMsg == 'error_speech_timeout' || e.errorMsg == 'error_no_match') {
            heard = '';
            reply = conversing ? '' : s.didntCatch;
            conversing = false;
            _idle(keepReply: true);
          } else {
            _fail(s.micProblem(e.errorMsg));
          }
        },
      );
      if (sttReady) {
        final locales = await _stt.locales();
        String? pick(String prefix, String preferred) {
          final m = locales.where((l) => l.localeId.toLowerCase().startsWith(prefix)).map((l) => l.localeId).toList();
          if (m.isEmpty) return null;
          return m.firstWhere((id) => id.toLowerCase().replaceAll('-', '_') == preferred, orElse: () => m.first);
        }

        _bnLocale = pick('bn', 'bn_bd');
        _enLocale = pick('en', 'en_us');
        // voice input starts in the language chosen in Settings when the device can recognise it
        bangla = session.voiceLanguage == 'bn' && _bnLocale != null;
      }
    } catch (_) {
      sttReady = false; // e.g. no recogniser on this platform
    }
    _notify();
  }

  void toggleLanguage() {
    if (_bnLocale == null) return;
    bangla = !bangla;
    _notify();
  }

  bool get canUseBangla => _bnLocale != null;

  /// Main button: idle → listen; listening → send now; speaking → stop talking.
  Future<void> mainButton() async {
    switch (orb.state) {
      case OrbState.listening:
        if (_serverStt) {
          await _finishRecording(heardSomething: true);
        } else {
          await _stt.stop(); // the final result triggers the send
        }
      case OrbState.speaking:
        await speaker.stop();
        _endSpeaking();
      case OrbState.thinking:
        break;
      case OrbState.idle:
      case OrbState.error:
        conversing = true;
        await listen();
    }
  }

  /// [afterSpeaking]: Sora has just spoken (a follow-up or a yes/no question), so the first moment
  /// of audio is its own voice fading out.
  Future<void> listen({bool afterSpeaking = false}) async {
    if (!sttReady) {
      _fail(s.noVoiceInput);
      return;
    }
    heard = '';
    reply = pending != null ? (pending!['summary'] as String? ?? '') : s.statusListening;
    orb.state = OrbState.listening;
    orb.setInput(0);
    _notify();
    if (_serverStt) {
      try {
        await _rec.start(
          onLevel: orb.setInput,
          onEnd: (end) => _finishRecording(heardSomething: end == Endpoint.finished),
          skip: afterSpeaking ? const Duration(milliseconds: 700) : Duration.zero,
        );
      } catch (e) {
        _fail(s.micProblem('$e'));
      }
      return;
    }
    await _stt.listen(
      onResult: _onResult,
      // Android reports roughly -2..10 dB; map that to the orb's 0..1 loudness.
      onSoundLevelChange: (db) => orb.setInput(((db + 2) / 12).clamp(0.0, 1.0)),
      listenOptions: SpeechListenOptions(
        localeId: bangla ? _bnLocale : _enLocale,
        listenFor: const Duration(seconds: 60),
        pauseFor: const Duration(seconds: 3),
        partialResults: true,
        cancelOnError: true,
        listenMode: ListenMode.dictation,
      ),
    );
  }

  /// The owner stopped talking (or tapped to send): write the recording down on the server, then send it.
  Future<void> _finishRecording({required bool heardSomething}) async {
    if (orb.state != OrbState.listening || _finishing) return;
    _finishing = true;
    final wav = await _rec.stop(keepQuiet: heardSomething).whenComplete(() => _finishing = false);
    orb.setInput(0);
    if (wav == null) {
      heard = '';
      if (conversing) {
        // Quiet after an answer: the conversation is over.
        conversing = false;
        _idle();
      } else {
        reply = s.didntCatch;
        _idle(keepReply: true);
      }
      return;
    }
    orb.state = OrbState.thinking;
    reply = s.working;
    _notify();
    String text;
    try {
      text = await api.transcribe(wav);
    } on ApiException catch (e) {
      if (e.unauthorized) return session.signOut();
      _fail(e.message);
      return;
    } catch (_) {
      _fail(s.serverUnreachable);
      return;
    }
    if (_disposed) return;
    if (text.isEmpty) {
      heard = '';
      if (conversing && _emptyTries < 2) {
        // Only noise (a door, Sora's own echo): keep the conversation going and listen again.
        _emptyTries++;
        await listen(afterSpeaking: true);
        return;
      }
      _emptyTries = 0;
      reply = s.didntCatch;
      _idle(keepReply: true);
      return;
    }
    _emptyTries = 0;
    if (conversing && pending == null && isGoodbye(text)) {
      conversing = false;
      heard = text;
      _idle();
      return;
    }
    orb.state = OrbState.listening; // send() moves on to thinking
    await send(text);
  }

  void _onResult(SpeechRecognitionResult r) {
    heard = r.recognizedWords;
    _notify();
    if (r.finalResult) {
      if (heard.trim().isEmpty) {
        _idle();
      } else {
        unawaited(send(heard.trim()));
      }
    }
  }

  Future<void> send(String text) async {
    if (_sending) return;
    _sending = true;
    heard = text;
    reply = s.working;
    pending = null;
    orb.state = OrbState.thinking;
    _notify();
    await _run(api.chat(text, conversationId: session.conversationId, voice: true));
  }

  Future<void> decide(bool approve) async {
    final p = pending;
    if (p == null || _sending) return;
    _sending = true;
    pending = null;
    reply = approve ? s.onIt : s.declined;
    orb.state = OrbState.thinking;
    _notify();
    await _run(api.decide(p['action_id'] as String, approve, voice: true));
  }

  Future<void> _run(Stream<AgentEvent> events) async {
    final spoken = <String>[];
    try {
      await for (final e in events) {
        switch (e.type) {
          case 'conversation':
            await session.setConversation(e.data['id'] as String?);
          case 'message':
            final t = (e.data['content'] as String? ?? '').trim();
            if (t.isNotEmpty) spoken.add(t);
          case 'tool_start':
            activeTool = toolLabel(e.data['name'] as String? ?? '');
            _notify();
          case 'tool_result':
            activeTool = null;
            _notify();
          case 'confirmation_required':
            pending = e.data;
          case 'client_action':
            final problem = await runPhoneAction(
              e.data['action'] as String? ?? '',
              Map<String, dynamic>.from(e.data['params'] as Map? ?? const {}),
            );
            if (problem != null) spoken.add(problem); // a failure is said out loud; success is silent
          case 'error':
            throw ApiException(500, e.data['message'] as String? ?? s.genericError);
        }
      }
    } on ApiException catch (e) {
      _sending = false;
      if (e.unauthorized) {
        await session.signOut();
        return;
      }
      _fail(e.message);
      return;
    } catch (e) {
      _sending = false;
      _fail(s.serverUnreachable);
      return;
    }
    _sending = false;
    activeTool = null;
    final text = stripMarkdown(spoken.join(' '));
    if (text.isNotEmpty) {
      reply = text;
      await _speak(text);
    }
    if (pending != null) {
      // Ask out loud and listen for a yes/no; the server understands "হ্যাঁ", "haan", "না"...
      reply = pending!['summary'] as String? ?? s.confirmPrompt;
      _notify();
      await listen(afterSpeaking: text.isNotEmpty);
    } else if (conversing && orb.state != OrbState.error && !_disposed) {
      await listen(afterSpeaking: text.isNotEmpty); // the follow-up, no tap needed
    } else if (orb.state != OrbState.error) {
      _idle(keepReply: true);
    }
  }

  /// Pause button: stop listening (without sending) or stop talking.
  Future<void> stop() async {
    conversing = false;
    if (orb.state == OrbState.listening) {
      await _stt.cancel();
      await _rec.cancel();
      _idle(keepReply: true);
    } else if (orb.state == OrbState.speaking) {
      await speaker.stop();
      _endSpeaking();
    }
  }

  /// Close button: drop whatever is going on, including a pending approval question.
  Future<void> cancel() async {
    conversing = false;
    await _stt.cancel();
    await _rec.cancel();
    await speaker.stop();
    _speechEnvelope?.cancel();
    pending = null;
    heard = '';
    orb.setInput(0);
    _idle();
  }

  // ---------------------------------------------------------------- speaking

  Future<void> _speak(String text) async {
    orb.state = OrbState.speaking;
    spokenWords = 0;
    _notify();
    await speaker.speak(
      text,
      onStart: _startEnvelope,
      onWords: (n) {
        spokenWords = n;
        _wordPulse();
        _notify();
      },
    );
    _endSpeaking();
  }

  // The audio isn't analysed, so loudness follows a voice-like envelope, re-synced on every word.
  double _envClock = 0;
  void _startEnvelope() {
    _speechEnvelope?.cancel();
    _envClock = 0;
    _speechEnvelope = Timer.periodic(const Duration(milliseconds: 50), (_) {
      _envClock += 0.05;
      final syll = math.max(0.0, math.sin(_envClock * math.pi * 2 * 4.2));
      orb.setInput(0.25 + 0.55 * math.pow(syll, 0.7), pitchHz: 175 + 45 * math.sin(_envClock * 1.3));
    });
  }

  void _wordPulse() => _envClock = 0.06; // start of a syllable

  void _endSpeaking() {
    _speechEnvelope?.cancel();
    _speechEnvelope = null;
    orb.setInput(0);
    if (orb.state == OrbState.speaking) _idle(keepReply: true);
  }

  // ---------------------------------------------------------------- states

  void _idle({bool keepReply = false}) {
    orb.state = OrbState.idle;
    if (!keepReply) reply = '';
    _notify();
  }

  void _fail(String message) {
    conversing = false;
    orb.state = OrbState.error;
    reply = message;
    _notify();
    Future.delayed(const Duration(seconds: 3), () {
      if (!_disposed && orb.state == OrbState.error) _idle(keepReply: true);
    });
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _speechEnvelope?.cancel();
    _stt.cancel();
    _rec.dispose();
    speaker.dispose();
    super.dispose();
  }
}

// Short goodbyes that end a hands-free conversation (kept in step with is_goodbye in the server's
// textutil.py). "Thanks, now open YouTube" is a request, not a goodbye: the whole utterance must match.
final _goodbye = RegExp(
  r"^[\s\p{P}]*(?:ok(?:ay)?[\s\p{P}]+)?(?:bye|goodbye|bye bye|good night|that'?s all|that is all|stop|stop listening|"
  r"thank you|thanks|thank you sora|thanks sora|never ?mind|no thanks|nothing|"
  r"ধন্যবাদ|থ্যাংক ইউ|বাই|ঠিক আছে|ঠিকাছে|থাক|আর কিছু না|আর কিছু লাগবে না|চুপ করো|বন্ধ করো|"
  r"dhonnobad|thik ache|thak|ar kichu na)(?:[\s\p{P}]+(?:sora|সোরা))?[\s\p{P}]*$",
  caseSensitive: false,
  unicode: true,
);

bool isGoodbye(String text) => _goodbye.hasMatch(text.trim());
