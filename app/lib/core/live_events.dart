import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:web_socket_channel/io.dart';

import 'session.dart';

/// The Windows app's live line to the server: what the server pushes (a phone notification…) arrives
/// in [events] when it happens, instead of being asked for every few seconds. One idle WebSocket,
/// reconnecting with a growing pause; the server's pings keep it open.
class LiveEvents {
  LiveEvents(this.session);

  final Session session;
  final _events = StreamController<Map<String, dynamic>>.broadcast();
  IOWebSocketChannel? _ws;
  bool _on = false;

  Stream<Map<String, dynamic>> get events => _events.stream;

  void start() {
    if (_on) return;
    _on = true;
    _run();
  }

  void stop() {
    _on = false;
    _ws?.sink.close();
    _ws = null;
  }

  Future<void> _run() async {
    var pause = 2;
    while (_on) {
      final server = session.serverUrl, token = session.token;
      if (server != null && token != null) {
        try {
          final url = server.replaceFirst(RegExp(r'^http'), 'ws').replaceAll(RegExp(r'/+$'), '');
          final ws = IOWebSocketChannel.connect(Uri.parse('$url/ws'), headers: {'Authorization': 'Bearer $token'});
          await ws.ready;
          _ws = ws;
          pause = 2;
          await for (final raw in ws.stream) {
            final msg = jsonDecode(raw as String) as Map<String, dynamic>;
            switch (msg['type']) {
              case 'ping':
                ws.sink.add(jsonEncode({'type': 'pong'}));
              case 'command':
                // Meant for the PC agent when it isn't running: say so now rather than let it time out.
                ws.sink.add(jsonEncode({'type': 'result', 'id': msg['id'], 'ok': false, 'error': "the Sora PC agent isn't running"}));
              default:
                _events.add(msg);
            }
          }
        } catch (_) {
          // server off or at a new address (the shell finds it): try again soon
        }
        _ws = null;
      }
      if (!_on) break;
      await Future<void>.delayed(Duration(seconds: pause));
      pause = math.min(pause * 2, 60);
    }
  }
}
