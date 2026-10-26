import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:record/record.dart';

/// What the endpointer decided after the latest chunk of audio.
enum Endpoint { listening, finished, noSpeech }

/// Decides when the owner has finished talking: speech followed by [silence] of quiet.
/// The quiet level is learnt from the room (it only rises while nobody is speaking), so a fan or
/// traffic doesn't keep the recording open.
class SpeechEndpointer {
  SpeechEndpointer({
    this.silence = const Duration(milliseconds: 1300),
    this.noSpeech = const Duration(seconds: 8),
    this.maxLength = const Duration(seconds: 60),
  });

  final Duration silence, noSpeech, maxLength;

  double? _floor;
  double _speechMs = 0, _quietMs = 0, _totalMs = 0;
  bool heard = false;

  /// The room's quiet level in dBFS.
  double get floor => _floor ?? -60;

  /// Speech is anything clearly above the room's quiet level.
  double get threshold => math.max(floor + 10, -50);

  /// Feeds one chunk's loudness ([db] in dBFS) lasting [ms] milliseconds.
  Endpoint add(double db, double ms) {
    _floor ??= db;
    _totalMs += ms;
    if (db < _floor!) {
      _floor = db;
    }
    if (db > threshold) {
      _speechMs += ms;
      _quietMs = 0;
      if (_speechMs >= 250) heard = true;
    } else {
      _floor = _floor! * 0.95 + db * 0.05; // slowly follow a room that gets louder
      _quietMs += ms;
      if (!heard) _speechMs = math.max(0, _speechMs - ms);
    }
    if (heard && _quietMs >= silence.inMilliseconds) return Endpoint.finished;
    if (_totalMs >= maxLength.inMilliseconds) return heard ? Endpoint.finished : Endpoint.noSpeech;
    if (!heard && _totalMs >= noSpeech.inMilliseconds) return Endpoint.noSpeech;
    return Endpoint.listening;
  }
}

/// Records the owner's voice as 16 kHz mono PCM for server speech-to-text (Whisper), reporting
/// loudness for the orb and stopping by itself when they finish talking.
class VoiceRecorder {
  /// [raw]: the microphone as the "Hey Sora" listener hears it (no noise suppression, no speech
  /// tuning), for recording training samples. The other values set when a recording ends.
  VoiceRecorder({
    this.raw = false,
    this.silence = const Duration(milliseconds: 1300),
    this.noSpeech = const Duration(seconds: 8),
    this.maxLength = const Duration(seconds: 60),
  });

  static const sampleRate = 16000;

  final bool raw;
  final Duration silence, noSpeech, maxLength;
  final _rec = AudioRecorder();
  StreamSubscription<Uint8List>? _sub;
  BytesBuilder _pcm = BytesBuilder(copy: false);
  late SpeechEndpointer _end = SpeechEndpointer(silence: silence, noSpeech: noSpeech, maxLength: maxLength);
  bool _active = false;

  bool get recording => _active;

  Future<bool> hasPermission() => _rec.hasPermission();

  /// Starts recording. [onLevel] gets 0..1 loudness; [onEnd] fires once with [Endpoint.finished]
  /// (they spoke, then went quiet) or [Endpoint.noSpeech] (nothing said). The first [skip] of audio
  /// is dropped: right after Sora has spoken, the end of its own voice (still in the speakers, or
  /// echoing in the room) would otherwise count as the owner talking and end the recording at once.
  Future<void> start({
    required void Function(double level) onLevel,
    required void Function(Endpoint) onEnd,
    Duration skip = Duration.zero,
  }) async {
    await cancel();
    _pcm = BytesBuilder(copy: false);
    _end = SpeechEndpointer(silence: silence, noSpeech: noSpeech, maxLength: maxLength);
    final stream = await _rec.startStream(
      raw
          // the same settings as the background listener (WakeService)
          ? const RecordConfig(encoder: AudioEncoder.pcm16bits, sampleRate: sampleRate, numChannels: 1, echoCancel: true)
          : const RecordConfig(
              encoder: AudioEncoder.pcm16bits,
              sampleRate: sampleRate,
              numChannels: 1,
              echoCancel: true,
              noiseSuppress: true,
              androidConfig: AndroidRecordConfig(audioSource: AndroidAudioSource.voiceRecognition),
            ),
    );
    _active = true;
    var skipMs = skip.inMilliseconds.toDouble();
    _sub = stream.listen((chunk) {
      if (!_active) return;
      if (skipMs > 0) {
        skipMs -= chunk.length / 2 / sampleRate * 1000;
        return;
      }
      _pcm.add(chunk);
      final db = levelDb(chunk);
      onLevel(((db - _end.floor - 4) / 30).clamp(0.0, 1.0));
      final state = _end.add(db, chunk.length / 2 / sampleRate * 1000);
      if (state != Endpoint.listening) {
        _active = false;
        onEnd(state);
      }
    });
  }

  /// Stops and returns the recording as a WAV file, or null when no speech was heard (unless
  /// [keepQuiet]: the owner tapped send, so let the server judge a quiet recording).
  Future<Uint8List?> stop({bool keepQuiet = false}) async {
    _active = false;
    await _sub?.cancel();
    _sub = null;
    await _rec.stop();
    final pcm = _pcm.takeBytes();
    if (!_end.heard && !(keepQuiet && pcm.length > sampleRate)) return null; // keep at least 0.5 s
    return wav(pcm, sampleRate);
  }

  Future<void> cancel() async {
    _active = false;
    await _sub?.cancel();
    _sub = null;
    if (await _rec.isRecording()) await _rec.cancel();
  }

  Future<void> dispose() async {
    await cancel();
    await _rec.dispose();
  }

  /// Loudness of 16-bit little-endian PCM in dBFS (-90 for silence).
  static double levelDb(Uint8List pcm) {
    final n = pcm.length ~/ 2;
    if (n == 0) return -90;
    final data = ByteData.sublistView(pcm);
    var sum = 0.0;
    for (var i = 0; i < n; i++) {
      final v = data.getInt16(i * 2, Endian.little);
      sum += v * v;
    }
    final rms = math.sqrt(sum / n);
    return rms < 1 ? -90 : 20 * math.log(rms / 32768) / math.ln10;
  }

  /// Wraps raw 16-bit mono PCM in a WAV header.
  static Uint8List wav(Uint8List pcm, int rate) {
    final h = ByteData(44);
    void tag(int at, String s) {
      for (var i = 0; i < 4; i++) {
        h.setUint8(at + i, s.codeUnitAt(i));
      }
    }

    tag(0, 'RIFF');
    h.setUint32(4, 36 + pcm.length, Endian.little);
    tag(8, 'WAVE');
    tag(12, 'fmt ');
    h.setUint32(16, 16, Endian.little);
    h.setUint16(20, 1, Endian.little); // PCM
    h.setUint16(22, 1, Endian.little); // mono
    h.setUint32(24, rate, Endian.little);
    h.setUint32(28, rate * 2, Endian.little);
    h.setUint16(32, 2, Endian.little);
    h.setUint16(34, 16, Endian.little);
    tag(36, 'data');
    h.setUint32(40, pcm.length, Endian.little);
    return (BytesBuilder(copy: false)
          ..add(h.buffer.asUint8List())
          ..add(pcm))
        .takeBytes();
  }
}
