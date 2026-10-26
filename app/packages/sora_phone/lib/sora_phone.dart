import 'dart:async';
import 'dart:convert';

import 'package:flutter/services.dart';

/// Sora's phone actions (Android). Works in the app and in the background "Hey Sora" service.
abstract final class SoraPhone {
  static const _channel = MethodChannel('sora_phone');

  /// Runs [action] (open_app, close_app, open_url, media, volume, flashlight, set_alarm, set_timer, call,
  /// send_sms, navigate, play_music, open_settings, lock, screenshot). Returns a short result; throws
  /// [PlatformException] with a message the assistant can repeat when it can't.
  static Future<String> run(String action, Map<String, dynamic> params) async =>
      await _channel.invokeMethod<String>('run', {'action': action, 'params': params}) ?? 'done';

  /// Whether the owner turned Sora on in Settings → Accessibility (needed for screenshots and lock).
  static Future<bool> accessibilityEnabled() async => await _channel.invokeMethod<bool>('accessibilityEnabled') ?? false;

  static Future<void> openAccessibilitySettings() => _channel.invokeMethod('openAccessibilitySettings');

  /// The phone's own line to the server, kept by the accessibility service with the app closed (like
  /// Phone Link): where the server is and this phone's token; nulls when signed out.
  static Future<void> link(String? server, String? token, {bool? bangla}) =>
      _channel.invokeMethod('link', {'server': server, 'token': token, 'bangla': bangla});

  /// The phone's notifications on the PC: `enabled` (the owner's switch, off by default), `access`
  /// (Notification access is allowed), `allowed` (the packages sent) and `apps` ({package, label}:
  /// the allowed ones and the ones seen lately, to choose from). Give one to change it.
  static Future<Map<String, dynamic>> notificationMirror({bool? enabled, List<String>? allowed}) async => Map<String, dynamic>.from(
    await _channel.invokeMethod<Map>('notificationMirror', {'enabled': enabled, 'allowed': allowed}) ?? const {},
  );

  /// Settings → Notification access, at Sora's switch where the phone allows.
  static Future<void> openNotificationAccess() => _channel.invokeMethod('openNotificationAccess');

  /// That line's settings: `connected` (false after the notification's Disconnect), `notify` (the
  /// "Connected to the PC" notification), and `online` (up right now). Give one to change it.
  static Future<Map<String, dynamic>> linkSettings({bool? connected, bool? notify}) async =>
      Map<String, dynamic>.from(await _channel.invokeMethod<Map>('linkSettings', {'connected': connected, 'notify': notify}) ?? const {});

  /// That line runs (signed in): the app and the "Hey Sora" service then don't open their own (one
  /// per device: a second one would replace the first).
  /// The glow round the screen's edge while Sora talks hands-free: [state] "listening" (with the
  /// voice's [level], 0..1), "thinking", "speaking" or "off". False when it can't show (Sora is off in
  /// Accessibility).
  static Future<bool> edgeGlow(String state, {double level = 0}) async {
    try {
      return await _channel.invokeMethod<bool>('edgeGlow', {'state': state, 'level': level}) ?? false;
    } on MissingPluginException {
      return false;
    }
  }

  static Future<bool> linkActive() async {
    try {
      return await _channel.invokeMethod<bool>('linkActive') ?? false;
    } on MissingPluginException {
      return false;
    }
  }

  /// Clipboard sync: [onCopied] gets text the owner copied (seen through Sora's accessibility
  /// service), [onScreenshot] a new screenshot's bytes and file name. The newest Flutter engine
  /// (the app, or the "Hey Sora" service) receives them.
  static void listen({
    required Future<void> Function(String text) onCopied,
    required Future<void> Function(Uint8List bytes, String name) onScreenshot,
  }) {
    _onCopied = onCopied;
    _onScreenshot = onScreenshot;
    _handle();
  }

  /// What the server says over the background line for the app's screens ({"type": "device_status", …}).
  static Stream<Map<String, dynamic>> get events {
    _handle();
    return _events.stream;
  }

  static Future<void> Function(String text)? _onCopied;
  static Future<void> Function(Uint8List bytes, String name)? _onScreenshot;
  static final _events = StreamController<Map<String, dynamic>>.broadcast();
  static bool _handling = false;

  // One handler for everything the plugin calls in with (a channel has only one).
  static void _handle() {
    if (_handling) return;
    _handling = true;
    _channel.setMethodCallHandler((call) async {
      switch (call.method) {
        case 'clipboard':
          await _onCopied?.call(call.arguments as String);
        case 'screenshot':
          final args = Map<String, dynamic>.from(call.arguments as Map);
          await _onScreenshot?.call(args['bytes'] as Uint8List, args['name'] as String? ?? 'screenshot.png');
        case 'event':
          try {
            _events.add(Map<String, dynamic>.from(jsonDecode(call.arguments as String) as Map));
          } catch (_) {}
      }
      return null;
    });
  }
}
