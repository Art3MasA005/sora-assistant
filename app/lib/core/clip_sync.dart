import 'dart:convert';
import 'dart:io' show Platform;
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:sora_phone/sora_phone.dart';

/// The phone's side of the shared clipboard: what the owner copies (and new screenshots) goes to the
/// Sora server, which puts it on the PC's clipboard. Runs in the app and in the "Hey Sora" service —
/// whichever is running (plain http, no Session, so the background service can use it).
abstract final class ClipSync {
  /// Turns the phone side on or off as the owner set it on the server (Settings → Clipboard), and
  /// sends what gets copied. [server] and [token] are read each time (the address may change).
  static Future<void> start({required String? Function() server, required String? Function() token}) async {
    if (!Platform.isAndroid) return;
    Future<http.Response?> send(http.BaseRequest Function(String base) build) async {
      final base = server()?.replaceAll(RegExp(r'/+$'), ''), t = token();
      if (base == null || t == null) return null;
      final req = build(base)..headers['Authorization'] = 'Bearer $t';
      try {
        return await http.Response.fromStream(await req.send().timeout(const Duration(seconds: 60)));
      } catch (_) {
        return null; // away from home: this copy isn't shared
      }
    }

    SoraPhone.listen(
      onCopied: (text) async {
        await send((base) => http.Request('POST', Uri.parse('$base/api/clipboard'))
          ..headers['Content-Type'] = 'application/json'
          ..body = jsonEncode({'text': text}));
      },
      onScreenshot: (Uint8List bytes, String name) async {
        await send((base) => http.MultipartRequest('POST', Uri.parse('$base/api/clipboard/image'))
          ..fields['name'] = name
          ..files.add(http.MultipartFile.fromBytes('image', bytes, filename: name)));
      },
    );
    final res = await send((base) => http.Request('GET', Uri.parse('$base/api/clipboard/settings')));
    var on = false;
    if (res != null && res.statusCode == 200) on = (jsonDecode(res.body) as Map)['enabled'] == true;
    await setOn(on);
  }

  /// Whether the phone notices copies and screenshots at all.
  static Future<void> setOn(bool on) async {
    if (!Platform.isAndroid) return;
    try {
      await SoraPhone.run('clipboard_sync', {'on': on});
    } catch (_) {}
  }
}
