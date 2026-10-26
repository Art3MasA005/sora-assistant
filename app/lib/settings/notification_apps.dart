import 'package:flutter/material.dart';
import 'package:sora_phone/sora_phone.dart';

import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/overlays.dart';
import '../widgets/sora_widgets.dart';

/// The apps whose notifications go to the PC: the messaging apps, and others seen posting lately.
/// Each switch saves at once; [state] is the plugin's {enabled, access, allowed, apps}.
Future<void> showNotificationApps(BuildContext context, Map<String, dynamic> state) => showSoraSheet<void>(
      context,
      title: S.of(context).mirrorAppsTitle,
      builder: (_) => _Apps(state: state),
    );

class _Apps extends StatefulWidget {
  const _Apps({required this.state});

  final Map<String, dynamic> state;

  @override
  State<_Apps> createState() => _AppsState();
}

class _AppsState extends State<_Apps> {
  late Map<String, dynamic> _state = widget.state;

  Set<String> get _allowed => {for (final a in _state['allowed'] as List? ?? const []) '$a'};

  Future<void> _set(String package, bool on) async {
    final allowed = _allowed;
    on ? allowed.add(package) : allowed.remove(package);
    try {
      final next = await SoraPhone.notificationMirror(allowed: allowed.toList());
      if (mounted) setState(() => _state = next);
    } catch (_) {
      if (mounted) showToast(context, S.of(context).couldntChange);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final apps = [for (final a in _state['apps'] as List? ?? const []) Map<String, dynamic>.from(a as Map)];
    final allowed = _allowed;
    return ConstrainedBox(
      constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * .6),
      child: ListView.builder(
          shrinkWrap: true,
          itemCount: apps.length,
          itemBuilder: (_, i) {
            final app = apps[i];
            final package = app['package'] as String? ?? '';
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      app['label'] as String? ?? package,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: SoraType.ui(14.5, weight: FontWeight.w500, color: p.ink),
                    ),
                  ),
                  SoraSwitch(value: allowed.contains(package), onChanged: (on) => _set(package, on)),
                ],
              ),
            );
          },
      ),
    );
  }
}
