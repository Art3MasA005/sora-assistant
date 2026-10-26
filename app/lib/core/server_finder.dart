import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

/// Finds the Sora server when the saved address stops answering — the home router gives the PC a
/// different address now and then (192.168.0.100 one day, .101 the next). Tries the saved address,
/// this computer (the Windows app, or a phone on USB with `adb reverse`), then — on the phone — every
/// address on its Wi-Fi network at port 8000. A server counts only if it says it is Sora and, when a
/// [token] is given, accepts it (so it is this owner's server).
///
/// Plain dart:io + http, so the background "Hey Sora" service can use it too.
abstract final class ServerFinder {
  static const port = 8000;
  static const local = 'http://127.0.0.1:$port';

  static Future<String?> find({String? token, String? current}) async {
    final tried = <String>{};
    for (final url in [?current, local]) {
      if (tried.add(_trim(url)) && await isSora(url, token: token)) return _trim(url);
    }
    if (!Platform.isAndroid) return null; // the Windows app talks to the server on its own PC
    return scanWifi(token: token, skip: tried);
  }

  /// Every address on the phone's local networks (Wi-Fi first), all at once; the first Sora wins.
  static Future<String?> scanWifi({String? token, Set<String> skip = const {}}) async {
    for (final prefix in await _prefixes()) {
      final hosts = [for (var i = 1; i < 255; i++) '$prefix.$i'];
      final open = await Future.wait(hosts.map(_portOpen));
      for (var i = 0; i < hosts.length; i++) {
        final url = 'http://${hosts[i]}:$port';
        if (open[i] && !skip.contains(url) && await isSora(url, token: token)) return url;
      }
    }
    return null;
  }

  /// `/api/health` answers as Sora, and [token] (if any) is accepted by `/api/me`.
  static Future<bool> isSora(String url, {String? token}) async {
    final base = _trim(url);
    final client = http.Client();
    try {
      final res = await client.get(Uri.parse('$base/api/health')).timeout(const Duration(seconds: 4));
      if (res.statusCode != 200) return false;
      final h = jsonDecode(utf8.decode(res.bodyBytes));
      if (h is! Map || !(h['name'] == 'sora' || h.containsKey('tools'))) return false;
      if (token == null) return true;
      final me = await client
          .get(Uri.parse('$base/api/me'), headers: {'Authorization': 'Bearer $token'})
          .timeout(const Duration(seconds: 4));
      return me.statusCode == 200;
    } catch (_) {
      return false;
    } finally {
      client.close();
    }
  }

  static String _trim(String url) => url.trim().replaceAll(RegExp(r'/+$'), '');

  static Future<bool> _portOpen(String host) async {
    try {
      final socket = await Socket.connect(host, port, timeout: const Duration(milliseconds: 900));
      socket.destroy();
      return true;
    } catch (_) {
      return false;
    }
  }

  /// "192.168.0" for each private IPv4 network the phone is on; Wi-Fi before mobile data and VPNs.
  static Future<List<String>> _prefixes() async {
    final List<NetworkInterface> list;
    try {
      list = await NetworkInterface.list(type: InternetAddressType.IPv4);
    } catch (_) {
      return const [];
    }
    int rank(NetworkInterface n) => n.name.startsWith('wlan') ? 0 : (n.name.startsWith('eth') ? 1 : 2);
    list.sort((a, b) => rank(a).compareTo(rank(b)));
    final out = <String>[];
    for (final n in list) {
      if (RegExp(r'^(rmnet|ccmni|tun|ppp|dummy|lo)').hasMatch(n.name)) continue;
      for (final a in n.addresses) {
        final p = a.address.split('.');
        final private = p[0] == '192' && p[1] == '168' ||
            p[0] == '10' ||
            p[0] == '172' && (int.tryParse(p[1]) ?? 0) >= 16 && (int.tryParse(p[1]) ?? 0) <= 31;
        final prefix = p.take(3).join('.');
        if (private && !out.contains(prefix)) out.add(prefix);
      }
    }
    return out;
  }
}
