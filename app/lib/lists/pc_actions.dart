import 'dart:convert';
import 'dart:io' show Platform;

import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../core/api.dart';
import '../l10n/strings.dart';
import '../widgets/list_kit.dart';
import '../widgets/overlays.dart';
import '../widgets/screenshot_view.dart';
import '../widgets/shot_actions.dart';

/// Quick actions on an online PC agent (Devices screen and the desktop Details panel): Lock,
/// Screenshot, Volume, and Sleep, which asks first. [device] is a row from `/api/devices`.

/// Runs a PC action; returns its result, or null after showing why it failed.
Future<Object?> pcCommand(
  BuildContext context,
  SoraApi api,
  Map<String, dynamic> device,
  String action, [
  Map<String, dynamic> params = const {},
]) async {
  try {
    return await api.deviceCommand(device['id'] as String, action, params) ?? true;
  } on ApiException catch (e) {
    if (context.mounted) showToast(context, e.status == 409 ? S.of(context).pcOffline : e.message);
  } catch (e) {
    if (context.mounted) showToast(context, e.toString());
  }
  return null;
}

Future<void> pcLock(BuildContext context, SoraApi api, Map<String, dynamic> device) async {
  if (await pcCommand(context, api, device, 'lock') != null && context.mounted) showToast(context, S.of(context).pcLocked);
}

Future<void> pcScreenshot(BuildContext context, SoraApi api, Map<String, dynamic> device) async {
  final s = S.of(context);
  showToast(context, s.working);
  final r = await pcCommand(context, api, device, 'screenshot');
  final b64 = r is Map ? r['png_base64'] as String? : null;
  if (b64 == null || !context.mounted) return;
  await showScreenshot(
    context,
    png: base64Decode(b64),
    title: '${s.screenshot} · ${device['name']}',
    actions: Platform.isAndroid ? phoneShotActions(s) : pcShotActions(s, api, device, name: 'pc'),
  );
}

Future<void> pcVolume(BuildContext context, SoraApi api, Map<String, dynamic> device) {
  final s = S.of(context);
  Future<void> run(BuildContext ctx, String target) async {
    Navigator.pop(ctx);
    final r = await pcCommand(context, api, device, 'volume', {'target': target, 'value': 5});
    if (r != null && context.mounted) showToast(context, '${s.volume} ✓');
  }

  return showSoraSheet<void>(
    context,
    title: '${s.volume} · ${device['name']}',
    builder: (ctx) => Row(
      children: [
        Expanded(
          child: SheetTile(icon: Symbols.volume_down_rounded, label: s.volumeDown, onTap: () => run(ctx, 'down')),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: SheetTile(icon: Symbols.volume_up_rounded, label: s.volumeUp, onTap: () => run(ctx, 'up')),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: SheetTile(icon: Symbols.volume_off_rounded, label: s.mute, onTap: () => run(ctx, 'mute')),
        ),
      ],
    ),
  );
}

Future<void> pcSleep(BuildContext context, SoraApi api, Map<String, dynamic> device) async {
  final s = S.of(context);
  final ok = await showConfirmSheet(
    context,
    title: s.needsApproval,
    text: s.sleepQ('${device['name']}'),
    confirm: s.yes,
    approvalLabel: 'PC · ${device['name']}',
  );
  if (ok && context.mounted && await pcCommand(context, api, device, 'sleep') != null && context.mounted) {
    showToast(context, '${s.done} ✓');
  }
}
