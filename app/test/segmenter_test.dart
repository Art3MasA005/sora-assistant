import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:sora/voice/wake_service.dart';

Uint8List _pcm(double seconds, double amp, {double freq = 220}) {
  final n = (16000 * seconds).round();
  final d = ByteData(n * 2);
  final rnd = math.Random(1);
  for (var i = 0; i < n; i++) {
    final noise = (rnd.nextDouble() - .5) * 0.004; // a quiet room
    final v = amp * math.sin(2 * math.pi * freq * i / 16000) + noise;
    d.setInt16(i * 2, (v * 32767).round().clamp(-32768, 32767), Endian.little);
  }
  return d.buffer.asUint8List();
}

void main() {
  test('one utterance between silences comes out once, with its pre-roll', () {
    final seg = SpeechSegmenter();
    final out = <Uint8List>[];
    final stream = [_pcm(1.5, 0), _pcm(1.0, 0.2), _pcm(1.5, 0)];
    for (final part in stream) {
      for (var i = 0; i < part.length; i += 1024) {
        final r = seg.add(Uint8List.sublistView(part, i, math.min(i + 1024, part.length)));
        if (r != null) out.add(r);
      }
    }
    expect(out, hasLength(1));
    final seconds = out.single.length / 2 / 16000;
    expect(seconds, greaterThan(1.0)); // speech + pre-roll + the quiet tail
    expect(seconds, lessThan(2.2));
  });

  test('wav header', () {
    final wav = wavFromPcm16(Uint8List(320));
    expect(String.fromCharCodes(wav.sublist(0, 4)), 'RIFF');
    expect(wav.length, 44 + 320);
  });
}
