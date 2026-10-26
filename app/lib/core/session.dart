import 'dart:io' show Platform;

import 'package:flutter/material.dart' show ThemeMode;
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:sora_phone/sora_phone.dart';

/// Server address + this device's token (kept in the Android Keystore / Windows credential store).
class Session extends ChangeNotifier {
  Session._(this._store);

  static const _kServer = 'server_url';
  static const _kToken = 'device_token';
  static const _kConversation = 'conversation_id';
  static const _kTheme = 'theme_mode';
  static const _kLanguage = 'language';
  static const _kDeviceName = 'device_name';
  static const _kVoiceLang = 'voice_language';
  static const _kVoice = 'voice_name';
  static const _kSpeed = 'voice_speed';
  static const _kReadAloud = 'read_aloud';
  static const _kHandsFree = 'hands_free';
  static const _kCloseToTray = 'close_to_tray';
  static const _kPhoneNotifications = 'phone_notifications';

  final FlutterSecureStorage _store;
  String? serverUrl;
  String? token;

  /// The name this device signed in with (shown in Settings).
  String? deviceName;
  ThemeMode themeMode = ThemeMode.system;

  /// App language: 'en' (default) or 'bn'.
  String language = 'en';

  /// Voice settings: the language speech recognition starts in ('en' / 'bn'), Sora's voice
  /// (Nova, Orion, Tara, Aria) and speed (0.9, 1.0, 1.2), and whether important notifications are
  /// read aloud.
  String voiceLanguage = 'en';
  String voice = 'Nova';
  double voiceSpeed = 1.0;
  bool readAloud = true;

  /// "Hey Sora" in the background (Android): see WakeService.
  bool handsFree = false;

  /// Windows: closing the window leaves Sora in the notification area (default) instead of quitting.
  bool closeToTray = true;

  /// Windows: the phone's notifications in the Details panel (default on).
  bool phoneNotifications = true;

  /// Shared by the voice and chat screens so both continue the same thread.
  String? conversationId;

  bool get signedIn => serverUrl != null && token != null;

  static Future<Session> load() async {
    final s = Session._(const FlutterSecureStorage());
    s.serverUrl = await s._store.read(key: _kServer);
    s.token = await s._store.read(key: _kToken);
    s.deviceName = await s._store.read(key: _kDeviceName);
    s.conversationId = await s._store.read(key: _kConversation);
    final theme = await s._store.read(key: _kTheme);
    s.themeMode = ThemeMode.values.firstWhere((m) => m.name == theme, orElse: () => ThemeMode.system);
    s.language = await s._store.read(key: _kLanguage) == 'bn' ? 'bn' : 'en';
    s.voiceLanguage = await s._store.read(key: _kVoiceLang) ?? s.language;
    s.voice = await s._store.read(key: _kVoice) ?? 'Nova';
    s.voiceSpeed = double.tryParse(await s._store.read(key: _kSpeed) ?? '') ?? 1.0;
    s.readAloud = await s._store.read(key: _kReadAloud) != 'false';
    s.handsFree = await s._store.read(key: _kHandsFree) == 'true';
    s.closeToTray = await s._store.read(key: _kCloseToTray) != 'false';
    s.phoneNotifications = await s._store.read(key: _kPhoneNotifications) != 'false';
    return s;
  }

  Future<void> setVoiceLanguage(String code) async {
    voiceLanguage = code == 'bn' ? 'bn' : 'en';
    notifyListeners();
    await _store.write(key: _kVoiceLang, value: voiceLanguage);
  }

  Future<void> setVoice(String name) async {
    voice = name;
    notifyListeners();
    await _store.write(key: _kVoice, value: name);
  }

  Future<void> setVoiceSpeed(double speed) async {
    voiceSpeed = speed;
    notifyListeners();
    await _store.write(key: _kSpeed, value: '$speed');
  }

  Future<void> setReadAloud(bool on) async {
    readAloud = on;
    notifyListeners();
    await _store.write(key: _kReadAloud, value: '$on');
  }

  Future<void> setCloseToTray(bool on) async {
    closeToTray = on;
    notifyListeners();
    await _store.write(key: _kCloseToTray, value: '$on');
  }

  Future<void> setPhoneNotifications(bool on) async {
    phoneNotifications = on;
    notifyListeners();
    await _store.write(key: _kPhoneNotifications, value: '$on');
  }

  Future<void> setHandsFree(bool on) async {
    handsFree = on;
    notifyListeners();
    await _store.write(key: _kHandsFree, value: '$on');
  }

  Future<void> setLanguage(String code) async {
    language = code == 'bn' ? 'bn' : 'en';
    notifyListeners();
    await _store.write(key: _kLanguage, value: language);
  }

  Future<void> setThemeMode(ThemeMode mode) async {
    themeMode = mode;
    notifyListeners();
    await _store.write(key: _kTheme, value: mode.name);
  }

  Future<void> signIn(String server, String newToken, {String? device}) async {
    serverUrl = server;
    token = newToken;
    deviceName = device;
    await _store.write(key: _kServer, value: server);
    await _store.write(key: _kToken, value: newToken);
    if (device != null) await _store.write(key: _kDeviceName, value: device);
    notifyListeners();
  }

  /// The server answered at a new address (the PC got a different one from the router).
  Future<void> setServer(String url) async {
    serverUrl = url;
    notifyListeners();
    await _store.write(key: _kServer, value: url);
  }

  Future<void> setConversation(String? id) async {
    if (id == conversationId) return;
    conversationId = id;
    if (id == null) {
      await _store.delete(key: _kConversation);
    } else {
      await _store.write(key: _kConversation, value: id);
    }
  }

  Future<void> signOut() async {
    if (Platform.isAndroid) {
      try {
        await SoraPhone.link(null, null); // the background line stops too
      } catch (_) {}
    }
    token = null;
    conversationId = null;
    await _store.delete(key: _kToken);
    await _store.delete(key: _kConversation);
    notifyListeners();
  }
}
