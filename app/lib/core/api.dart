import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'session.dart';

class ApiException implements Exception {
  ApiException(this.status, this.message);
  final int status;
  final String message;
  bool get unauthorized => status == 401;
  @override
  String toString() => message;
}

/// One event from the agent stream (see docs/api.md): conversation, delta, message, tool_start,
/// tool_result, confirmation_required, action_resolved, client_action, attachment, done, error.
class AgentEvent {
  AgentEvent(this.type, this.data);
  final String type;
  final Map<String, dynamic> data;
}

class SoraApi {
  SoraApi(this.session, {http.Client? client}) : _http = client ?? http.Client();

  final Session session;
  final http.Client _http;

  Uri _u(String path, [Map<String, String>? query]) =>
      Uri.parse('${session.serverUrl!.replaceAll(RegExp(r'/+$'), '')}$path').replace(queryParameters: query);

  Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    if (session.token != null) 'Authorization': 'Bearer ${session.token}',
  };

  static String get deviceKind => Platform.isWindows ? 'windows' : 'android';

  Future<dynamic> _send(String method, String path, {Object? body, Map<String, String>? query}) async {
    final req = http.Request(method, _u(path, query))..headers.addAll(_headers);
    if (body != null) req.body = jsonEncode(body);
    final res = await http.Response.fromStream(await _http.send(req).timeout(const Duration(seconds: 30)));
    final text = utf8.decode(res.bodyBytes);
    if (res.statusCode >= 400) throw ApiException(res.statusCode, _detail(text, res.statusCode));
    return text.isEmpty ? null : jsonDecode(text);
  }

  static String _detail(String body, int status) {
    try {
      final d = jsonDecode(body);
      if (d is Map && d['detail'] != null) return d['detail'].toString();
    } catch (_) {}
    return 'Server error ($status)';
  }

  // ---------------------------------------------------------------- auth

  /// Exchanges the owner PIN for a token for this device. Does not store anything.
  static Future<String> login(String server, String pin, String deviceName) async {
    final base = server.replaceAll(RegExp(r'/+$'), '');
    final res = await http
        .post(
          Uri.parse('$base/api/auth/login'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'password': pin, 'device_name': deviceName, 'device_kind': deviceKind}),
        )
        .timeout(const Duration(seconds: 15));
    final text = utf8.decode(res.bodyBytes);
    if (res.statusCode >= 400) throw ApiException(res.statusCode, _detail(text, res.statusCode));
    return (jsonDecode(text) as Map)['token'] as String;
  }

  Future<void> logout() => _send('POST', '/api/auth/logout');

  Future<Map<String, dynamic>> health() async => Map<String, dynamic>.from(await _send('GET', '/api/health'));

  // ---------------------------------------------------------------- chat

  Stream<AgentEvent> chat(String message, {String? conversationId, bool voice = false}) =>
      _stream('/api/chat', {'message': message, 'conversation_id': conversationId, 'voice': voice});

  Stream<AgentEvent> decide(String actionId, bool approve, {bool voice = false}) =>
      _stream('/api/actions/$actionId', {'approve': approve, 'voice': voice});

  /// Server-Sent Events: lines of `event: x` / `data: {...}` separated by blank lines.
  Stream<AgentEvent> _stream(String path, Map<String, dynamic> body) async* {
    final req = http.Request('POST', _u(path))
      ..headers.addAll(_headers)
      ..headers['Accept'] = 'text/event-stream'
      ..body = jsonEncode(body);
    final res = await _http.send(req).timeout(const Duration(seconds: 30));
    if (res.statusCode >= 400) {
      final text = await res.stream.bytesToString();
      throw ApiException(res.statusCode, _detail(text, res.statusCode));
    }
    yield* parseSse(res.stream.transform(utf8.decoder).transform(const LineSplitter()));
  }

  static Stream<AgentEvent> parseSse(Stream<String> lines) async* {
    await for (final line in lines) {
      if (!line.startsWith('data:')) continue;
      final data = jsonDecode(line.substring(5).trim()) as Map<String, dynamic>;
      yield AgentEvent(data['type'] as String? ?? 'message', data);
    }
  }

  /// Who the apps are signed in for: `name` (OWNER_NAME), `email` (Google account), `device`.
  Future<Map<String, dynamic>> me() async => Map<String, dynamic>.from(await _send('GET', '/api/me'));

  Future<List<dynamic>> conversations() async => await _send('GET', '/api/conversations') as List<dynamic>;

  Future<Map<String, dynamic>> conversation(String id) async =>
      Map<String, dynamic>.from(await _send('GET', '/api/conversations/$id'));

  Future<List<dynamic>> pendingActions() async => await _send('GET', '/api/actions/pending') as List<dynamic>;

  // ---------------------------------------------------------------- voice

  /// Server text-to-speech (Edge neural voices) as MP3 bytes. [rate] like "+0%" / "-10%".
  Future<Uint8List> speak(String text, {String? voice, String rate = '+0%'}) async {
    final req = http.Request('POST', _u('/api/voice/speak'))
      ..headers.addAll(_headers)
      ..body = jsonEncode({'text': text, 'voice': voice, 'rate': rate});
    final res = await http.Response.fromStream(await _http.send(req).timeout(const Duration(seconds: 30)));
    if (res.statusCode >= 400) throw ApiException(res.statusCode, _detail(utf8.decode(res.bodyBytes), res.statusCode));
    return res.bodyBytes;
  }

  /// Server speech-to-text (Whisper) for a WAV recording. Without [language] the server picks
  /// Bangla or English by itself.
  Future<String> transcribe(Uint8List wav, {String? language}) async {
    final req = http.MultipartRequest('POST', _u('/api/voice/transcribe'))
      ..headers.addAll({if (session.token != null) 'Authorization': 'Bearer ${session.token}'})
      ..files.add(http.MultipartFile.fromBytes('audio', wav, filename: 'voice.wav'));
    if (language != null) req.fields['language'] = language;
    final res = await http.Response.fromStream(await _http.send(req).timeout(const Duration(seconds: 60)));
    final text = utf8.decode(res.bodyBytes);
    if (res.statusCode >= 400) throw ApiException(res.statusCode, _detail(text, res.statusCode));
    return ((jsonDecode(text) as Map)['text'] as String? ?? '').trim();
  }

  // ---------------------------------------------------------------- "Hey Sora" training samples

  /// `{positive: {total, this_device}, negative: {...}}`
  Future<Map<String, dynamic>> wakeSamples() async =>
      Map<String, dynamic>.from(await _send('GET', '/api/voice/wake-samples'));

  /// Saves a recording of the owner saying "Hey Sora" ([kind] `positive`) or something else (`negative`).
  Future<Map<String, dynamic>> addWakeSample(Uint8List wav, String kind) async {
    final req = http.MultipartRequest('POST', _u('/api/voice/wake-samples'))
      ..headers.addAll({if (session.token != null) 'Authorization': 'Bearer ${session.token}'})
      ..fields['kind'] = kind
      ..files.add(http.MultipartFile.fromBytes('audio', wav, filename: 'sample.wav'));
    final res = await http.Response.fromStream(await _http.send(req).timeout(const Duration(seconds: 30)));
    final text = utf8.decode(res.bodyBytes);
    if (res.statusCode >= 400) throw ApiException(res.statusCode, _detail(text, res.statusCode));
    return Map<String, dynamic>.from(jsonDecode(text) as Map);
  }

  Future<Map<String, dynamic>> undoWakeSample() async =>
      Map<String, dynamic>.from(await _send('DELETE', '/api/voice/wake-samples/last'));

  // ---------------------------------------------------------------- conversations

  Future<Map<String, dynamic>> patchConversation(String id, {String? title, bool? pinned, bool? archived}) async =>
      Map<String, dynamic>.from(
        await _send('PATCH', '/api/conversations/$id', body: {'title': ?title, 'pinned': ?pinned, 'archived': ?archived}),
      );

  Future<void> deleteConversation(String id) => _send('DELETE', '/api/conversations/$id');

  // ---------------------------------------------------------------- notifications + email rules

  Future<List<dynamic>> notifications({bool unread = false}) async =>
      await _send('GET', '/api/notifications', query: unread ? {'unread': 'true'} : null) as List<dynamic>;

  Future<void> markRead(String id) => _send('POST', '/api/notifications/$id/read');

  Future<void> markAllRead() => _send('POST', '/api/notifications/read-all');

  Future<void> deleteNotification(String id) => _send('DELETE', '/api/notifications/$id');

  Future<void> deleteAllNotifications() => _send('DELETE', '/api/notifications');

  /// The app's language, for what Sora writes on its own (email summaries). [onlyIfUnset]: the app
  /// is starting up, so it doesn't undo a choice made on the other device.
  Future<void> setLanguage(String code, {bool onlyIfUnset = false}) =>
      _send('PUT', '/api/preferences/language', body: {'language': code, 'only_if_unset': onlyIfUnset});

  Future<List<dynamic>> emailRules() async => await _send('GET', '/api/email-rules') as List<dynamic>;

  Future<void> addEmailRule(String rule) => _send('POST', '/api/email-rules', body: {'rule': rule});

  Future<void> switchEmailRule(String id, bool active) => _send('PATCH', '/api/email-rules/$id', body: {'active': active});

  Future<void> deleteEmailRule(String id) => _send('DELETE', '/api/email-rules/$id');

  // ---------------------------------------------------------------- reminders

  Future<List<dynamic>> reminders() async =>
      await _send('GET', '/api/reminders', query: {'include_done': 'true'}) as List<dynamic>;

  Future<void> addReminder(String text, DateTime due, String repeat) =>
      _send('POST', '/api/reminders', body: {'text': text, 'due_at': _local(due), 'repeat': repeat});

  Future<void> patchReminder(String id, {String? status, String? text}) =>
      _send('PATCH', '/api/reminders/$id', body: {'status': ?status, 'text': ?text});

  Future<void> deleteReminder(String id) => _send('DELETE', '/api/reminders/$id');

  // ---------------------------------------------------------------- the phone's notifications (kept in memory on the server)

  /// {toast: shown as Windows toasts, items: newest first}
  Future<Map<String, dynamic>> phoneNotifications() async =>
      Map<String, dynamic>.from(await _send('GET', '/api/phone-notifications'));

  Future<void> setPhoneNotificationToast(bool on) => _send('PUT', '/api/phone-notifications/settings', body: {'toast': on});

  Future<void> clearPhoneNotifications() => _send('DELETE', '/api/phone-notifications');

  // ---------------------------------------------------------------- routines (made and changed in the chat)

  Future<List<dynamic>> routines() async => await _send('GET', '/api/routines') as List<dynamic>;

  Future<Map<String, dynamic>> patchRoutine(String id, {bool? enabled, bool? speak}) async =>
      Map<String, dynamic>.from(await _send('PATCH', '/api/routines/$id', body: {'enabled': ?enabled, 'speak': ?speak}));

  Future<void> runRoutine(String id) => _send('POST', '/api/routines/$id/run');

  Future<void> deleteRoutine(String id) => _send('DELETE', '/api/routines/$id');

  /// ISO local time without an offset (the server reads it in the owner's time zone).
  static String _local(DateTime t) => t.toIso8601String().split('.').first;

  // ---------------------------------------------------------------- memories + instructions

  Future<List<dynamic>> memories() async => await _send('GET', '/api/memories') as List<dynamic>;

  Future<void> addMemory(String content, String category) =>
      _send('POST', '/api/memories', body: {'content': content, 'category': category});

  Future<void> patchMemory(String id, {String? content, String? category}) =>
      _send('PATCH', '/api/memories/$id', body: {'content': ?content, 'category': ?category});

  Future<void> deleteMemory(String id) => _send('DELETE', '/api/memories/$id');

  // ---------------------------------------------------------------- people (contacts with relation, nicknames, birthday)

  Future<List<dynamic>> people() async => await _send('GET', '/api/people') as List<dynamic>;

  /// [person]: name, relation, phones, emails, aliases, birthday (YYYY-MM-DD or null), notes.
  Future<void> addPerson(Map<String, dynamic> person) => _send('POST', '/api/people', body: person);

  Future<void> updatePerson(String id, Map<String, dynamic> person) => _send('PUT', '/api/people/$id', body: person);

  Future<void> deletePerson(String id) => _send('DELETE', '/api/people/$id');

  Future<Map<String, dynamic>> assistantSettings() async =>
      Map<String, dynamic>.from(await _send('GET', '/api/settings/assistant'));

  Future<void> saveAssistantSettings(String instructions, String tone) =>
      _send('PUT', '/api/settings/assistant', body: {'instructions': instructions, 'tone': tone});

  // ---------------------------------------------------------------- knowledge

  Future<List<dynamic>> knowledge({String? q}) async =>
      await _send('GET', '/api/knowledge', query: q == null || q.isEmpty ? null : {'q': q}) as List<dynamic>;

  Future<void> addNote(String title, String content) =>
      _send('POST', '/api/knowledge/notes', body: {'title': title, 'content': content});

  Future<void> addUrl(String url) => _send('POST', '/api/knowledge/url', body: {'url': url});

  Future<void> uploadKnowledge(Uint8List bytes, String filename) async {
    final req = http.MultipartRequest('POST', _u('/api/knowledge/upload'))
      ..headers.addAll({if (session.token != null) 'Authorization': 'Bearer ${session.token}'})
      ..files.add(http.MultipartFile.fromBytes('file', bytes, filename: filename));
    final res = await http.Response.fromStream(await _http.send(req).timeout(const Duration(minutes: 3)));
    if (res.statusCode >= 400) throw ApiException(res.statusCode, _detail(utf8.decode(res.bodyBytes), res.statusCode));
  }

  Future<void> renameKnowledge(String id, String title) => _send('PATCH', '/api/knowledge/$id', body: {'title': title});

  Future<void> deleteKnowledge(String id) => _send('DELETE', '/api/knowledge/$id');

  // ---------------------------------------------------------------- devices

  Future<List<dynamic>> devices() async => await _send('GET', '/api/devices') as List<dynamic>;

  Future<void> renameDevice(String id, String name) => _send('PATCH', '/api/devices/$id', body: {'name': name});

  Future<void> revokeDevice(String id) => _send('DELETE', '/api/devices/$id');

  /// Runs a PC action directly (Lock, Screenshot…), without asking the LLM.
  Future<dynamic> deviceCommand(String id, String action, [Map<String, dynamic> params = const {}]) async =>
      ((await _send('POST', '/api/devices/$id/command', body: {'action': action, 'params': params})) as Map)['result'];

  // ---------------------------------------------------------------- shared clipboard

  /// `{enabled, items: [{id, kind: text|image, text | name, from: phone|pc, device, at}]}`, newest first.
  Future<Map<String, dynamic>> clipboard() async => Map<String, dynamic>.from(await _send('GET', '/api/clipboard'));

  /// Puts an item from the history on the PC's clipboard again.
  Future<void> copyClipboardItem(String id) => _send('POST', '/api/clipboard/$id/copy');

  Future<void> deleteClipboardItem(String id) => _send('DELETE', '/api/clipboard/$id');

  /// Empties the history (the clipboards themselves keep what is on them).
  Future<void> clearClipboard() => _send('DELETE', '/api/clipboard');

  Future<void> setClipboardSync(bool on) => _send('PUT', '/api/clipboard/settings', body: {'enabled': on});

  String clipboardImageUrl(String id) => _u('/api/clipboard/$id/image').toString();

  Map<String, String> get authHeader => {if (session.token != null) 'Authorization': 'Bearer ${session.token}'};

  // ---------------------------------------------------------------- this PC

  /// Whether the server and the PC agent start when the owner signs in to Windows:
  /// `{supported, enabled}`.
  Future<Map<String, dynamic>> autostart() async => Map<String, dynamic>.from(await _send('GET', '/api/system/autostart'));

  Future<Map<String, dynamic>> setAutostart(bool on) async =>
      Map<String, dynamic>.from(await _send('PUT', '/api/system/autostart', body: {'enabled': on}));

  /// Turns Sora off on the PC: the PC agent (and its mic), then the server (Windows app only).
  Future<void> stopSora() async => _send('POST', '/api/system/stop');

  /// "Hey Sora" on the PC agent [pcId]: `{enabled, available, problem}`; [on] switches it.
  Future<Map<String, dynamic>> heySora(String pcId, {bool? on}) async => Map<String, dynamic>.from(
    await deviceCommand(pcId, 'hey_sora', {if (on != null) 'value': on ? 1 : 0}) as Map,
  );

  // ---------------------------------------------------------------- Google connections

  Future<Map<String, dynamic>> googleConnection() async {
    final list = await _send('GET', '/api/connections') as List<dynamic>;
    return Map<String, dynamic>.from(list.first as Map);
  }

  Future<String> startGoogle(List<String> services) async {
    final res = await _send('POST', '/api/connections/google/start', body: {'services': services});
    return (res as Map)['auth_url'] as String;
  }

  Future<void> disconnectGoogle() => _send('DELETE', '/api/connections/google');

  Future<Map<String, dynamic>> setServiceEnabled(String service, bool enabled) async => Map<String, dynamic>.from(
    await _send('PATCH', '/api/connections/google/services/$service', body: {'enabled': enabled}),
  );
}
