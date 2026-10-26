import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:onnxruntime/onnxruntime.dart';
import 'package:path_provider/path_provider.dart';

/// Hears "Hey Sora" on the phone itself, so the background listener asks the server's Whisper only
/// when the name was said — the same steps as pc_agent/wake_model.py (openWakeWord's streaming
/// code). Every 80 ms of 16 kHz audio (1280 samples, plus the 480 before it):
///   melspectrogram.onnx → 8 mel frames (each /10 + 2)
///   embedding_model.onnx on the last 76 mel frames → 96 numbers
///   hey_sora.onnx on the last 16 of those (1.28 s) → how sure it is, 0..1
///
/// The files come from the server (`/api/voice/wake-model`, made by scripts/wakeword/train.py) and
/// are kept on the phone; a retrained model is downloaded by itself. Uses dart:ffi only, so it works
/// inside the background service.
class WakeModel {
  WakeModel._(this._mel, this._emb, this._wake, this.threshold) {
    reset();
  }

  static const _chunk = 1280, _context = 480, _melFrames = 76, _featureFrames = 16;

  final OrtSession _mel, _emb, _wake;

  /// The score that counts as hearing the name (from the server, WAKE_THRESHOLD).
  final double threshold;

  final _run = OrtRunOptions();
  final List<Float32List> _mels = [], _feats = [];
  Float32List _raw = Float32List(_context);
  Float32List _pending = Float32List(0);
  int _warm = 0;

  /// The model from the server (downloaded when it changed), or null when there is none yet or the
  /// server can't be reached and nothing is kept on the phone.
  static Future<WakeModel?> load(String server, String token) async {
    final dir = Directory('${(await getApplicationSupportDirectory()).path}/wakeword');
    final infoFile = File('${dir.path}/model.json');
    Map<String, dynamic>? info;
    try {
      final res = await http
          .get(Uri.parse('$server/api/voice/wake-model'), headers: {'Authorization': 'Bearer $token'})
          .timeout(const Duration(seconds: 15));
      if (res.statusCode == 200) {
        info = jsonDecode(res.body) as Map<String, dynamic>;
        final kept = await infoFile.exists() ? jsonDecode(await infoFile.readAsString()) as Map : null;
        if (kept?['version'] != info['version']) {
          await dir.create(recursive: true);
          for (final name in (info['files'] as List).cast<String>()) {
            final file = await http
                .get(Uri.parse('$server/api/voice/wake-model/$name'), headers: {'Authorization': 'Bearer $token'})
                .timeout(const Duration(seconds: 60));
            if (file.statusCode != 200) return null;
            await File('${dir.path}/$name').writeAsBytes(file.bodyBytes);
          }
          await infoFile.writeAsString(jsonEncode(info));
        }
      } else if (res.statusCode == 404) {
        return null; // not trained yet
      }
    } catch (_) {
      // away from home: use the copy kept on the phone, if any
    }
    if (!await infoFile.exists()) return null;
    info ??= jsonDecode(await infoFile.readAsString()) as Map<String, dynamic>;
    try {
      return open(dir.path, (info['threshold'] as num?)?.toDouble() ?? 0.5);
    } catch (_) {
      return null;
    }
  }

  /// The three model files in [folder].
  static WakeModel open(String folder, double threshold) {
    OrtEnv.instance.init();
    OrtSession session(String name) {
      final options = OrtSessionOptions()
        ..setIntraOpNumThreads(1)
        ..setInterOpNumThreads(1);
      // from bytes: the plugin's fromFile passes Windows paths in the wrong encoding
      return OrtSession.fromBuffer(File('$folder/$name').readAsBytesSync(), options);
    }

    return WakeModel._(session('melspectrogram.onnx'), session('embedding_model.onnx'), session('hey_sora.onnx'), threshold);
  }

  /// Forget what was heard (after a wake, or after Sora spoke). Starts from background-like
  /// features, as openWakeWord does.
  void reset() {
    _mels
      ..clear()
      ..addAll(List.generate(_melFrames, (_) => Float32List(32)..fillRange(0, 32, 1)));
    _feats.clear();
    _raw = Float32List(_context);
    _pending = Float32List(0);
    final noise = math.Random(0);
    for (var i = 0; i < 20; i++) {
      _step(Float32List.fromList(List.generate(_chunk, (_) => (noise.nextInt(2000) - 1000).toDouble())));
    }
    _warm = 0;
  }

  /// Feed little-endian 16-bit PCM from the mic; returns the highest score among the 80 ms steps it
  /// completed (0 if none).
  double add(Uint8List pcm16) {
    final view = ByteData.sublistView(pcm16);
    final n = pcm16.length ~/ 2;
    final all = Float32List(_pending.length + n)..setRange(0, _pending.length, _pending);
    for (var i = 0; i < n; i++) {
      all[_pending.length + i] = view.getInt16(i * 2, Endian.little).toDouble();
    }
    var best = 0.0;
    var at = 0;
    while (all.length - at >= _chunk) {
      best = math.max(best, _step(Float32List.sublistView(all, at, at + _chunk)));
      at += _chunk;
    }
    _pending = Float32List.fromList(Float32List.sublistView(all, at));
    return best;
  }

  double _step(Float32List chunk) {
    final audio = Float32List(_context + _chunk)
      ..setRange(0, _context, _raw)
      ..setRange(_context, _context + _chunk, chunk);
    _raw = Float32List.fromList(Float32List.sublistView(audio, _chunk));

    final mel = _infer(_mel, 'input', audio, [1, audio.length]); // 8 x 32
    for (var r = 0; r + 32 <= mel.length; r += 32) {
      _mels.add(Float32List.fromList([for (var c = 0; c < 32; c++) mel[r + c] / 10 + 2]));
    }
    if (_mels.length > _melFrames * 2) _mels.removeRange(0, _mels.length - _melFrames * 2);

    final window = Float32List(_melFrames * 32);
    for (var i = 0; i < _melFrames; i++) {
      window.setRange(i * 32, i * 32 + 32, _mels[_mels.length - _melFrames + i]);
    }
    _feats.add(Float32List.fromList(_infer(_emb, 'input_1', window, [1, _melFrames, 32, 1])));
    if (_feats.length > _featureFrames * 2) _feats.removeRange(0, _feats.length - _featureFrames * 2);

    _warm++;
    if (_feats.length < _featureFrames || _warm < 5) return 0; // the first few frames aren't reliable
    final x = Float32List(_featureFrames * 96);
    for (var i = 0; i < _featureFrames; i++) {
      x.setRange(i * 96, i * 96 + 96, _feats[_feats.length - _featureFrames + i]);
    }
    return _infer(_wake, 'input', x, [1, _featureFrames, 96]).first;
  }

  List<double> _infer(OrtSession session, String input, Float32List data, List<int> shape) {
    final tensor = OrtValueTensor.createTensorWithDataList(data, shape);
    final outputs = session.run(_run, {input: tensor});
    tensor.release();
    final out = <double>[];
    void flatten(Object? v) {
      if (v is List) {
        for (final e in v) {
          flatten(e);
        }
      } else if (v is num) {
        out.add(v.toDouble());
      }
    }

    flatten(outputs.first?.value);
    for (final o in outputs) {
      o?.release();
    }
    return out;
  }

  void dispose() {
    _run.release();
    _mel.release();
    _emb.release();
    _wake.release();
  }
}
