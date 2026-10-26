import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:material_symbols_icons/symbols.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:sora_phone/sora_phone.dart';

import '../core/api.dart';
import '../l10n/strings.dart';
import 'overlays.dart';
import 'screenshot_view.dart';

String _stamp() {
  final now = DateTime.now();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${now.year}${two(now.month)}${two(now.day)}-${two(now.hour)}${two(now.minute)}${two(now.second)}';
}

/// On the phone: Save (the gallery, Pictures/Sora), Send (any app: WhatsApp, Messenger…) and Copy
/// (the phone's clipboard, to paste in a chat).
List<ShotAction> phoneShotActions(S s) => [
  ShotAction(Symbols.download_rounded, s.save, (context, png) async {
    try {
      final where = await SoraPhone.run('save_image', {'png_base64': base64Encode(png)});
      if (context.mounted) showToast(context, s.savedTo(where));
    } on PlatformException catch (e) {
      if (context.mounted) showToast(context, e.message ?? s.genericError);
    }
  }),
  ShotAction(Symbols.share_rounded, s.send, (context, png) async {
    final file = File('${(await getTemporaryDirectory()).path}/Sora-${_stamp()}.png');
    await file.writeAsBytes(png);
    await SharePlus.instance.share(ShareParams(files: [XFile(file.path, mimeType: 'image/png')]));
  }),
  ShotAction(Symbols.content_copy_rounded, s.copy, (context, png) async {
    try {
      await SoraPhone.run('set_clipboard_image', {'png_base64': base64Encode(png)});
      if (context.mounted) showToast(context, s.copiedPhone);
    } on PlatformException catch (e) {
      if (context.mounted) showToast(context, e.message ?? s.genericError);
    }
  }),
];

/// On the PC: Save (Downloads\Sora) and Copy (this PC's clipboard, through the PC agent [pc]).
List<ShotAction> pcShotActions(S s, SoraApi api, Map<String, dynamic>? pc, {required String name}) => [
  ShotAction(Symbols.download_rounded, s.save, (context, png) async {
    final downloads = await getDownloadsDirectory();
    if (downloads == null) return;
    final dir = Directory('${downloads.path}${Platform.pathSeparator}Sora');
    await dir.create(recursive: true);
    final path = '${dir.path}${Platform.pathSeparator}$name-${_stamp()}.png';
    await File(path).writeAsBytes(png);
    if (context.mounted) showToast(context, s.savedTo(path));
  }),
  ShotAction(Symbols.content_copy_rounded, s.copy, (context, png) async {
    if (pc == null) {
      showToast(context, s.pcOffline);
      return;
    }
    try {
      await api.deviceCommand(pc['id'] as String, 'clipboard_image', {'png_base64': base64Encode(png)});
      if (context.mounted) showToast(context, s.copiedToPc);
    } catch (e) {
      if (context.mounted) showToast(context, e.toString());
    }
  }),
];
