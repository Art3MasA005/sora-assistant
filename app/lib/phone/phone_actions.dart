import 'dart:io' show Platform;

import 'package:flutter/services.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:sora_phone/sora_phone.dart';

/// Contacts (find "Ammu"'s number), Phone (call straight away, from the SIM asked for) and SMS (send a
/// text the owner approved). Asked once, while the app is on screen; from the background service it
/// can't ask, and the action says what is missing.
Future<void> askCallPermissions() async {
  if (!Platform.isAndroid) return;
  try {
    await [Permission.contacts, Permission.phone, Permission.sms].request();
  } catch (_) {
    // no activity (background service): nothing to ask with
  }
}

const _needsContacts = {'call', 'send_sms', 'find_contact', 'whatsapp_send'};

/// Carries out a phone action Sora asked for (a `client_action` event, or a command from the
/// server when the owner asked from the PC "do it on my phone"). Returns null when done, otherwise
/// a short reason to show or say.
Future<String?> runPhoneAction(String action, Map<String, dynamic> params) async {
  if (!Platform.isAndroid) return 'Phone actions run on the Android app.';
  if (_needsContacts.contains(action)) await askCallPermissions();
  try {
    await SoraPhone.run(action, params);
    return null;
  } on PlatformException catch (e) {
    return e.message ?? e.code;
  } on MissingPluginException {
    return "This build can't do phone actions.";
  }
}

/// Like [runPhoneAction], as a result message for the server's WebSocket.
Future<Map<String, dynamic>> phoneCommandResult(String? id, String action, Map<String, dynamic> params) async {
  if (!Platform.isAndroid) return {'type': 'result', 'id': id, 'ok': false, 'error': 'not an Android phone'};
  try {
    final data = await SoraPhone.run(action, params);
    return {'type': 'result', 'id': id, 'ok': true, 'data': data};
  } on PlatformException catch (e) {
    return {'type': 'result', 'id': id, 'ok': false, 'error': e.message ?? e.code};
  }
}
