import 'api.dart';
import 'session.dart';

/// Tells the server the app's language, so email summaries in notifications are written in it (and
/// recent ones are translated when it changes): once at start (only if the server has none yet, so
/// the phone and the PC don't undo each other) and whenever the owner changes it.
class LanguageSync {
  LanguageSync(this.session, this.api);

  final Session session;
  final SoraApi api;
  String? _sent;

  void start() {
    _sent = session.language;
    session.addListener(_check);
    _send(initial: true);
  }

  void stop() => session.removeListener(_check);

  void _check() {
    if (session.token == null || session.language == _sent) return;
    _sent = session.language;
    _send(initial: false);
  }

  Future<void> _send({required bool initial}) async {
    try {
      await api.setLanguage(session.language, onlyIfUnset: initial);
    } catch (_) {
      // server off: the start-up one waits for next time; email summaries keep the last language
    }
  }
}
