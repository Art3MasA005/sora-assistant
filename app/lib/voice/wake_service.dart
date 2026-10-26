import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:record/record.dart';
import 'package:sora_phone/sora_phone.dart';
import 'package:web_socket_channel/io.dart';

import '../core/clip_sync.dart';
import '../core/server_finder.dart';
import '../phone/phone_actions.dart';
import 'wake_model.dart';

/// "Hey Sora" on the phone, hands-free, like on the PC: an Android foreground service (with its
/// notification) keeps the mic open. The on-device "Hey Sora" model ([WakeModel]) listens for the
/// name; a bit of speech it heard the name in goes to the Sora server's /api/voice/wake, which checks
/// it again with Whisper and hears what followed (without a model yet, every bit of speech goes). After the wake word it chimes and holds the conversation itself —
/// listens, answers out loud, listens again — until 8 s of quiet or bye / thanks / ধন্যবাদ. Nothing is
/// shown on screen, so it also works with the phone locked; the conversation is in the chat history.
///
/// The Voice screen pauses it while open (two recorders would fight over the mic).
///
/// It also keeps the phone connected to the server (WebSocket), so "do it on my phone" from the PC
/// reaches it, and carries out the phone actions Sora asks for in a hands-free conversation.
abstract final class WakeService {
  static bool get supported => Platform.isAndroid;

  static void initPort() {
    if (supported) FlutterForegroundTask.initCommunicationPort();
  }

  static void _init(bool bangla) => FlutterForegroundTask.init(
    androidNotificationOptions: AndroidNotificationOptions(
      channelId: 'sora_hands_free',
      channelName: bangla ? 'হেই সোরা' : 'Hey Sora',
      channelDescription: bangla ? 'সোরা আপনার ডাকের অপেক্ষায় শুনছে' : 'Shown while Sora listens for its name',
      onlyAlertOnce: true,
      channelImportance: NotificationChannelImportance.LOW,
      priority: NotificationPriority.LOW,
    ),
    iosNotificationOptions: const IOSNotificationOptions(showNotification: false),
    foregroundTaskOptions: ForegroundTaskOptions(
      eventAction: ForegroundTaskEventAction.nothing(),
      autoRunOnBoot: false, // Android does not let a microphone service start from boot
      allowWakeLock: true,
      allowWifiLock: true,
    ),
  );

  /// Starts listening. Must be called while the app is on screen (Android 14 rule for the mic).
  /// Returns false if a permission was refused.
  static Future<bool> start({required bool bangla}) async {
    if (!supported) return false;
    if (await FlutterForegroundTask.checkNotificationPermission() != NotificationPermission.granted) {
      await FlutterForegroundTask.requestNotificationPermission();
    }
    if (!await AudioRecorder().hasPermission()) return false;
    await askCallPermissions(); // so "call Ammu" works hands-free too
    if (!await FlutterForegroundTask.isIgnoringBatteryOptimizations) {
      await FlutterForegroundTask.requestIgnoreBatteryOptimization(); // or Android stops it after a while
    }
    _init(bangla);
    if (await FlutterForegroundTask.isRunningService) return true;
    final r = await FlutterForegroundTask.startService(
      serviceId: 4711,
      serviceTypes: [ForegroundServiceTypes.microphone],
      notificationTitle: bangla ? 'বলুন “হেই সোরা”' : 'Say “Hey Sora”',
      notificationText: bangla ? 'সোরা শুনছে' : 'Sora is listening for its name',
      callback: wakeTaskCallback,
    );
    return r is ServiceRequestSuccess;
  }

  static Future<void> stop() async {
    if (supported && await FlutterForegroundTask.isRunningService) await FlutterForegroundTask.stopService();
  }

  /// The service is running (and holds the phone's line to the server).
  static Future<bool> get running async => supported && await FlutterForegroundTask.isRunningService;

  /// The Voice screen opened/closed: free the mic for it, then take it back.
  static void pause() {
    if (supported) FlutterForegroundTask.sendDataToTask('pause');
  }

  static void resume() {
    if (supported) FlutterForegroundTask.sendDataToTask('resume');
  }
}

@pragma('vm:entry-point')
void wakeTaskCallback() => FlutterForegroundTask.setTaskHandler(_WakeTask());

const _rate = 16000;
const _followUp = Duration(seconds: 8);
const _newConversationAfter = Duration(minutes: 15);

class _WakeTask extends TaskHandler {
  final _rec = AudioRecorder();
  final _player = AudioPlayer();
  final _seg = SpeechSegmenter();
  final _http = http.Client();
  StreamSubscription<Uint8List>? _sub;
  IOWebSocketChannel? _ws;
  bool _stopping = false;
  String? _server, _token, _conversation;
  bool _bangla = false, _busy = false, _paused = false;
  int _misses = 0; // failed connections in a row
  WakeModel? _wake; // null: no model yet, every bit of speech goes to the server
  // Time counted in mic samples, so it stays right when the phone is busy.
  int _samples = 0, _nameHeardAt = -1 << 40;
  DateTime _lastTurn = DateTime.fromMillisecondsSinceEpoch(0);
  DateTime? _listenUntil; // set while in a conversation
  // The glow round the screen's edge (EdgeGlow on the phone): what it shows, and when the voice's level
  // was last sent to it (a few times a second is plenty).
  String _glowState = 'off';
  int _glowLevelAt = 0;

  static const _store = FlutterSecureStorage();

  @override
  Future<void> onStart(DateTime timestamp, TaskStarter starter) async {
    _server = await _store.read(key: 'server_url');
    _token = await _store.read(key: 'device_token');
    _conversation = await _store.read(key: 'conversation_id');
    _bangla = await _store.read(key: 'language') == 'bn';
    if (_server == null || _token == null) {
      await FlutterForegroundTask.stopService();
      return;
    }
    await _micOn();
    unawaited(_connect());
    unawaited(_loadModel());
    unawaited(ClipSync.start(server: () => _server, token: () => _token));
  }

  /// The on-device model from the server (again when it was retrained).
  Future<void> _loadModel() async {
    final model = await WakeModel.load(_server!.replaceAll(RegExp(r'/+$'), ''), _token!);
    if (model == null) return;
    _wake?.dispose();
    _wake = model;
  }

  // ------------------------------------------------------------ commands from the server

  /// Stays connected to the server's WebSocket (reconnecting with a growing pause) and runs the
  /// phone actions it sends — e.g. when the owner says on the PC "open YouTube on my phone".
  Future<void> _connect() async {
    var pause = 2;
    while (!_stopping) {
      if (await SoraPhone.linkActive()) {
        // the accessibility service holds the phone's line (and runs the commands)
        await Future<void>.delayed(const Duration(seconds: 10));
        continue;
      }
      try {
        final url = _server!.replaceFirst(RegExp(r'^http'), 'ws').replaceAll(RegExp(r'/+$'), '');
        final ws = IOWebSocketChannel.connect(Uri.parse('$url/ws'), headers: {'Authorization': 'Bearer $_token'});
        await ws.ready;
        _ws = ws;
        if (pause > 2 || _wake == null) unawaited(_loadModel()); // back after a while: maybe retrained
        pause = 2;
        _misses = 0;
        await for (final raw in ws.stream) {
          final msg = jsonDecode(raw as String) as Map<String, dynamic>;
          switch (msg['type']) {
            case 'ping':
              ws.sink.add(jsonEncode({'type': 'pong'}));
            case 'command':
              final result = await phoneCommandResult(
                msg['id'] as String?,
                msg['action'] as String? ?? '',
                Map<String, dynamic>.from(msg['params'] as Map? ?? const {}),
              );
              ws.sink.add(jsonEncode(result));
          }
        }
      } catch (_) {
        // server unreachable (away from home, restarted, or at a new address): try again soon
        await _findServer();
      }
      _ws = null;
      if (_stopping) break;
      await Future<void>.delayed(Duration(seconds: pause));
      pause = math.min(pause * 2, 60);
    }
  }

  /// The server stopped answering. The app may have found it at a new address already (it saves
  /// it); otherwise, after a few misses, look for it on the Wi-Fi here — the PC may have got a new
  /// address from the router while the app was closed.
  Future<void> _findServer() async {
    final saved = await _store.read(key: 'server_url');
    if (saved != null && saved != _server) {
      _server = saved;
      return;
    }
    if (++_misses < 3) return;
    _misses = 0;
    final found = await ServerFinder.find(token: _token, current: _server);
    if (found != null && found != _server) {
      _server = found;
      await _store.write(key: 'server_url', value: found);
    }
  }

  /// Phone actions in a hands-free answer ("open YouTube"): done quietly; a failure is said.
  Future<void> _runActions(Map<String, dynamic> r) async {
    for (final e in (r['events'] as List? ?? const [])) {
      if (e is Map && e['type'] == 'client_action') {
        final problem = await runPhoneAction(
          e['action'] as String? ?? '',
          Map<String, dynamic>.from(e['params'] as Map? ?? const {}),
        );
        if (problem != null) await _say(problem);
      }
    }
  }

  Future<void> _say(String text) async {
    try {
      final res = await _http
          .post(
            Uri.parse('${_server!.replaceAll(RegExp(r'/+$'), '')}/api/voice/speak'),
            headers: {'Authorization': 'Bearer $_token', 'Content-Type': 'application/json'},
            body: jsonEncode({'text': text}),
          )
          .timeout(const Duration(seconds: 30));
      if (res.statusCode == 200) await _play(res.bodyBytes, 'audio/mpeg');
    } catch (_) {}
  }

  Future<void> _micOn() async {
    if (_sub != null) return;
    _seg.reset();
    final stream = await _rec.startStream(
      const RecordConfig(encoder: AudioEncoder.pcm16bits, sampleRate: _rate, numChannels: 1, echoCancel: true),
    );
    _sub = stream.listen(_onPcm);
  }

  Future<void> _micOff() async {
    await _sub?.cancel();
    _sub = null;
    await _rec.stop();
  }

  void _onPcm(Uint8List bytes) {
    if (_busy || _paused) return; // heard while Sora talks or thinks: mostly its own voice
    _samples += bytes.length ~/ 2;
    final wake = _wake;
    if (wake != null && _listenUntil == null && wake.add(bytes) > wake.threshold) {
      _nameHeardAt = _samples;
      _glow('listening'); // it heard its name: show so at once, before the server has had its say
    }
    if (_glowState == 'listening') _glowLevel(bytes);
    final segment = _seg.add(bytes);
    if (segment != null) {
      _busy = true;
      unawaited(_handle(segment).whenComplete(() {
        _busy = false;
        _seg.reset();
      }));
    } else if (_listenUntil != null && DateTime.now().isAfter(_listenUntil!) && !_seg.inSpeech) {
      unawaited(_endConversation());
    }
  }

  // ------------------------------------------------------------ the conversation

  Future<void> _handle(Uint8List pcm) async {
    final seconds = pcm.length / 2 / _rate;
    if (seconds < 0.35) return;
    if (_listenUntil == null) {
      // With the model: only speech it heard the name in (the name ends a little before the pause
      // that ends the bit of speech).
      if (_wake != null && (_samples - _nameHeardAt) / _rate > seconds + 1.0) return;
      // Waiting for the wake word: only the start of a long stretch of speech matters.
      if (DateTime.now().difference(_lastTurn) > _newConversationAfter) _conversation = null;
      final clip = pcm.length > _rate * 2 * 4 ? Uint8List.sublistView(pcm, 0, _rate * 2 * 4) : pcm;
      if (_glowState != 'off') _glow('thinking'); // only once the model heard the name: not for every bit of speech
      final r = await _post('/api/voice/wake', clip);
      _wake?.reset(); // start fresh, whatever Whisper said
      if (r == null || r['wake'] != true) {
        _glow('off');
        return;
      }
      if ((r['reply'] as String? ?? '').isNotEmpty) {
        _glow('speaking');
        await _speak(r);
      } else if (r['status'] == 'listening') {
        await _chime(up: true);
      }
      await _runActions(r);
      _startListening();
      return;
    }
    _glow('thinking');
    final r = await _post('/api/voice/turn', pcm);
    if (r == null) {
      await _chime(up: false);
      _startListening();
      return;
    }
    if (r['status'] == 'end') return _endConversation();
    if ((r['reply'] as String? ?? '').isNotEmpty) {
      _glow('speaking');
      await _speak(r);
    }
    await _runActions(r);
    _startListening();
  }

  void _startListening() {
    _listenUntil = DateTime.now().add(_followUp);
    _seg.conversation = true;
    _glow('listening');
    FlutterForegroundTask.updateService(
      notificationTitle: _bangla ? 'সোরা শুনছে…' : 'Sora is listening…',
      notificationText: _bangla ? 'বলুন, অথবা “ধন্যবাদ” বলে শেষ করুন' : 'Talk, or say “thanks” to finish',
    );
  }

  Future<void> _endConversation() async {
    _listenUntil = null;
    _glow('off');
    _seg.conversation = false;
    _wake?.reset();
    _lastTurn = DateTime.now();
    FlutterForegroundTask.updateService(
      notificationTitle: _bangla ? 'বলুন “হেই সোরা”' : 'Say “Hey Sora”',
      notificationText: _bangla ? 'সোরা শুনছে' : 'Sora is listening for its name',
    );
    _busy = true;
    await _chime(up: false);
    _busy = false;
  }

  void _glow(String state) {
    if (state == _glowState) return;
    _glowState = state;
    unawaited(SoraPhone.edgeGlow(state));
  }

  /// The voice's loudness for the glow while it listens: RMS of the PCM16 chunk, sent about 8 times a second.
  void _glowLevel(Uint8List bytes) {
    final now = DateTime.now().millisecondsSinceEpoch;
    if (now - _glowLevelAt < 120 || bytes.length < 2) return;
    _glowLevelAt = now;
    final data = ByteData.sublistView(bytes);
    var sum = 0.0;
    for (var i = 0; i + 1 < bytes.length; i += 2) {
      final v = data.getInt16(i, Endian.little) / 32768;
      sum += v * v;
    }
    final rms = math.sqrt(sum / (bytes.length ~/ 2));
    unawaited(SoraPhone.edgeGlow('listening', level: (rms * 8).clamp(0.0, 1.0)));
  }

  Future<Map<String, dynamic>?> _post(String path, Uint8List pcm) async {
    try {
      final req = http.MultipartRequest('POST', Uri.parse('${_server!.replaceAll(RegExp(r'/+$'), '')}$path'))
        ..headers['Authorization'] = 'Bearer $_token'
        ..files.add(http.MultipartFile.fromBytes('audio', wavFromPcm16(pcm), filename: 'speech.wav'));
      if (_conversation != null) req.fields['conversation_id'] = _conversation!;
      final res = await http.Response.fromStream(await _http.send(req).timeout(const Duration(seconds: 90)));
      if (res.statusCode != 200) return null;
      return jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    } catch (_) {
      return null; // server unreachable (away from home without Tailscale): stay quiet
    }
  }

  Future<void> _speak(Map<String, dynamic> r) async {
    final id = r['conversation_id'] as String?;
    if (id != null && id != _conversation) {
      _conversation = id;
      await _store.write(key: 'conversation_id', value: id); // the app opens the same thread
    }
    _lastTurn = DateTime.now();
    final audio = r['audio_mp3_base64'] as String?;
    if (audio != null) await _play(base64Decode(audio), 'audio/mpeg');
  }

  Future<void> _chime({required bool up}) => _play(chimeWav(up ? [660, 880] : [880, 660]), 'audio/wav');

  Future<void> _play(Uint8List bytes, String mime) async {
    final done = _player.onPlayerComplete.first;
    await _player.play(BytesSource(bytes, mimeType: mime));
    await done.timeout(const Duration(minutes: 2), onTimeout: () {});
    await Future<void>.delayed(const Duration(milliseconds: 250)); // let the room go quiet
  }

  // ------------------------------------------------------------ lifecycle

  @override
  void onReceiveData(Object data) {
    if (data == 'pause') {
      _paused = true;
      _listenUntil = null;
      _glow('off');
      unawaited(_micOff());
    } else if (data == 'resume') {
      _paused = false;
      unawaited(_micOn());
    }
  }

  @override
  void onRepeatEvent(DateTime timestamp) {}

  @override
  void onNotificationPressed() => FlutterForegroundTask.launchApp();

  @override
  Future<void> onDestroy(DateTime timestamp, bool isTimeout) async {
    _stopping = true;
    _glow('off');
    _wake?.dispose();
    await _ws?.sink.close();
    await _micOff();
    await _player.dispose();
    _rec.dispose();
    _http.close();
  }
}

/// Cuts a 16 kHz PCM16 mic stream into utterances by loudness: speech starts when the level stays
/// well above the room's noise floor for 80 ms and ends after 700 ms of quiet (or at 8 s). 300 ms
/// before the start is kept so the first word isn't clipped.
class SpeechSegmenter {
  static const _frame = 320; // 20 ms
  static const _startFrames = 4, _preFrames = 15, _maxFrames = 400;

  /// Quiet frames that end an utterance: 0.7 s while waiting for "Hey Sora" (answers quickly), more
  /// in a conversation ([conversation]) so a breath after a name ("আব্বুকে… ফোন দাও") doesn't cut it.
  int _endFrames = 35;
  set conversation(bool on) => _endFrames = on ? 60 : 35;

  final _pending = BytesBuilder(copy: false);
  final List<Uint8List> _pre = [];
  final _speech = BytesBuilder(copy: false);
  double _noise = 0.004;
  int _loud = 0, _quiet = 0, _frames = 0;
  bool inSpeech = false;
  Uint8List _carry = Uint8List(0);

  void reset() {
    _pre.clear();
    _speech.clear();
    _pending.clear();
    _carry = Uint8List(0);
    _loud = _quiet = _frames = 0;
    inSpeech = false;
  }

  /// Feed mic bytes; returns a finished utterance (PCM16) when one ends.
  Uint8List? add(Uint8List bytes) {
    final all = BytesBuilder(copy: false)
      ..add(_carry)
      ..add(bytes);
    final data = all.takeBytes();
    const frameBytes = _frame * 2;
    var offset = 0;
    Uint8List? out;
    while (offset + frameBytes <= data.length) {
      final frame = Uint8List.sublistView(data, offset, offset + frameBytes);
      offset += frameBytes;
      out = _frameIn(Uint8List.fromList(frame)) ?? out;
    }
    _carry = Uint8List.fromList(Uint8List.sublistView(data, offset));
    return out;
  }

  Uint8List? _frameIn(Uint8List frame) {
    final view = ByteData.sublistView(frame);
    var sum = 0.0;
    for (var i = 0; i < _frame; i++) {
      final v = view.getInt16(i * 2, Endian.little) / 32768.0;
      sum += v * v;
    }
    final rms = math.sqrt(sum / _frame);
    final threshold = math.max(_noise * 3.2, 0.012);
    if (!inSpeech) {
      _noise = _noise * 0.995 + rms * 0.005; // follows the room while nobody talks
      _pre.add(frame);
      if (_pre.length > _preFrames) _pre.removeAt(0);
      _loud = rms > threshold ? _loud + 1 : 0;
      if (_loud >= _startFrames) {
        inSpeech = true;
        _quiet = 0;
        _frames = 0;
        for (final f in _pre) {
          _speech.add(f);
        }
        _pre.clear();
      }
      return null;
    }
    _speech.add(frame);
    _frames++;
    _quiet = rms < threshold * 0.7 ? _quiet + 1 : 0;
    if (_quiet >= _endFrames || _frames >= _maxFrames) {
      inSpeech = false;
      _loud = 0;
      return _speech.takeBytes();
    }
    return null;
  }
}

/// PCM16 mono 16 kHz → a WAV file.
Uint8List wavFromPcm16(Uint8List pcm, {int rate = _rate}) {
  final b = BytesBuilder();
  void str(String s) => b.add(ascii.encode(s));
  void u32(int v) => b.add((ByteData(4)..setUint32(0, v, Endian.little)).buffer.asUint8List());
  void u16(int v) => b.add((ByteData(2)..setUint16(0, v, Endian.little)).buffer.asUint8List());
  str('RIFF');
  u32(36 + pcm.length);
  str('WAVEfmt ');
  u32(16);
  u16(1);
  u16(1);
  u32(rate);
  u32(rate * 2);
  u16(2);
  u16(16);
  str('data');
  u32(pcm.length);
  b.add(pcm);
  return b.takeBytes();
}

/// A soft two-note chime as WAV: rising = listening, falling = done.
Uint8List chimeWav(List<double> freqs, {int ms = 110}) {
  const rate = 24000;
  final n = rate * ms ~/ 1000;
  final pcm = ByteData(freqs.length * n * 2);
  var k = 0;
  for (final f in freqs) {
    for (var i = 0; i < n; i++) {
      final env = math.min(1.0, math.min(i, n - i) / (rate * 0.016));
      pcm.setInt16(k++ * 2, (math.sin(2 * math.pi * f * i / rate) * env * 0.18 * 32767).round(), Endian.little);
    }
  }
  return wavFromPcm16(pcm.buffer.asUint8List(), rate: rate);
}
