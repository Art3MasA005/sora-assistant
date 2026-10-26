import 'dart:async';
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter_tts/flutter_tts.dart';

import '../core/api.dart';
import '../core/session.dart';
import '../widgets/markdown_lite.dart';

/// Sora's voices from the design, each backed by an Edge neural voice on the server (English and
/// Bangla variants), so Bangla sounds natural even on phones without a Bangla TTS engine.
class SoraVoice {
  const SoraVoice(this.name, this.en, this.bn, this.descEn, this.descBn);

  final String name, en, bn, descEn, descBn;

  static const all = [
    SoraVoice('Nova', 'en-US-AvaMultilingualNeural', 'bn-BD-NabanitaNeural', 'Warm and clear', 'উষ্ণ ও স্পষ্ট'),
    SoraVoice('Orion', 'en-US-AndrewMultilingualNeural', 'bn-BD-PradeepNeural', 'Calm, lower voice', 'শান্ত, গভীর কণ্ঠ'),
    SoraVoice('Tara', 'en-IN-NeerjaNeural', 'bn-IN-TanishaaNeural', 'Natural Bangla', 'স্বাভাবিক বাংলা'),
    SoraVoice('Aria', 'en-US-AriaNeural', 'bn-BD-NabanitaNeural', 'Bright and quick', 'উজ্জ্বল ও দ্রুত'),
  ];

  static SoraVoice byName(String name) => all.firstWhere((v) => v.name == name, orElse: () => all.first);
}

final _bangla = RegExp('[ঀ-৿]');

/// Speaks text in the owner's chosen voice: server TTS sentence by sentence (the next sentence is
/// fetched while the current one plays), falling back to the device's TTS if the server can't.
class Speaker {
  Speaker(this.api, this.session);

  final SoraApi api;
  final Session session;
  final _player = AudioPlayer();
  final _tts = FlutterTts();
  int _run = 0;
  bool _ttsReady = false;

  /// Splits after . ! ? । and line breaks, keeping each piece short enough to start quickly.
  static List<String> sentences(String text) =>
      stripMarkdown(text).split(RegExp(r'(?<=[.!?।])\s+|\n+')).map((s) => s.trim()).where((s) => s.isNotEmpty).toList();

  /// Speaks [text]; [onWords] reports how many words have been spoken so far (for the transcript),
  /// [onStart] fires when the first audio begins. Completes when done or [stop]ped.
  Future<void> speak(String text, {void Function(int words)? onWords, void Function()? onStart}) async {
    final run = ++_run;
    final parts = sentences(text);
    if (parts.isEmpty) return;
    final voice = SoraVoice.byName(session.voice);
    final rate = '${session.voiceSpeed >= 1 ? '+' : '-'}${((session.voiceSpeed - 1).abs() * 100).round()}%';
    Future<Uint8List?> fetch(String s) async {
      try {
        return await api.speak(s, voice: _bangla.hasMatch(s) ? voice.bn : voice.en, rate: rate);
      } catch (_) {
        return null;
      }
    }

    var spoken = 0;
    var started = false;
    Future<Uint8List?>? next = fetch(parts.first);
    for (var i = 0; i < parts.length; i++) {
      final audio = await next;
      if (run != _run) return;
      next = i + 1 < parts.length ? fetch(parts[i + 1]) : null;
      final words = parts[i].split(RegExp(r'\s+')).length;
      if (!started) {
        started = true;
        onStart?.call();
      }
      if (audio == null) {
        // Server voice unavailable: say the rest on the device.
        await _deviceSpeak(parts.sublist(i).join(' '), run, (w) => onWords?.call(spoken + w));
        return;
      }
      await _play(audio, run, words, (w) => onWords?.call(spoken + w));
      if (run != _run) return;
      spoken += words;
      onWords?.call(spoken);
    }
  }

  /// Plays one sentence, revealing its words evenly across the clip's length.
  Future<void> _play(Uint8List audio, int run, int words, void Function(int) onWords) async {
    final done = Completer<void>();
    final sub = _player.onPlayerComplete.listen((_) {
      if (!done.isCompleted) done.complete();
    });
    Timer? reveal;
    try {
      await _player.play(BytesSource(audio, mimeType: 'audio/mpeg'));
      final length = await _player.getDuration() ?? Duration(milliseconds: 380 * words);
      final step = length.inMilliseconds ~/ (words + 1);
      var shown = 0;
      reveal = Timer.periodic(Duration(milliseconds: step.clamp(60, 1000)), (_) {
        if (shown < words) onWords(++shown);
      });
      while (!done.isCompleted && run == _run) {
        await Future.any([done.future, Future<void>.delayed(const Duration(milliseconds: 120))]);
      }
    } catch (_) {
      // a broken clip just ends this sentence
    } finally {
      reveal?.cancel();
      await sub.cancel();
    }
  }

  Future<void> _deviceSpeak(String text, int run, void Function(int) onWords) async {
    if (!_ttsReady) {
      await _tts.awaitSpeakCompletion(true);
      _ttsReady = true;
    }
    var words = 0;
    _tts.setProgressHandler((_, start, end, word) {
      if (run == _run) onWords(++words);
    });
    try {
      await _tts.setLanguage(_bangla.hasMatch(text) ? 'bn-BD' : 'en-US');
      await _tts.setSpeechRate(0.5 * session.voiceSpeed);
      await _tts.speak(text);
    } catch (_) {}
  }

  // The Settings samples, kept for the app's run: each is fetched from the server once (a second or two
  // of TTS), so tapping through the voices plays at once. A few small clips.
  static final _samples = <String, Future<Uint8List>>{};

  Future<Uint8List> _sample(String name) {
    final v = SoraVoice.byName(name);
    final bn = session.voiceLanguage == 'bn';
    final voice = bn ? v.bn : v.en;
    return _samples[voice] ??= api
        .speak(bn ? 'হ্যালো, আমি Sora। আজ আপনাকে কীভাবে সাহায্য করতে পারি?' : "Hi, I'm Sora. How can I help you today?", voice: voice)
        .catchError((Object e) {
          _samples.remove(voice); // try again next time
          throw e;
        });
  }

  /// Fetches every voice's sample in the background (Settings opened), so the first tap is quick too.
  void warmPreviews() {
    for (final v in SoraVoice.all) {
      _sample(v.name).ignore();
    }
  }

  /// Short sample of a voice for the Settings list; a sample still playing stops right away.
  Future<void> preview(String name) async {
    final run = ++_run;
    try {
      await _player.stop();
      final audio = await _sample(name);
      if (run == _run) await _player.play(BytesSource(audio, mimeType: 'audio/mpeg'));
    } catch (_) {}
  }

  Future<void> stop() async {
    _run++;
    try {
      await _player.stop();
      await _tts.stop();
    } catch (_) {}
  }

  bool get busy => _player.state == PlayerState.playing;

  Future<void> dispose() async {
    await stop();
    await _player.dispose();
  }
}
