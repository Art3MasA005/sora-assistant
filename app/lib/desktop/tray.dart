import 'package:tray_manager/tray_manager.dart';
import 'package:window_manager/window_manager.dart';

import '../core/session.dart';

/// Windows: Sora's icon in the notification area (the taskbar's "Show hidden icons"). Closing the
/// window (✕, Alt+F4) hides it there instead of quitting, unless the owner switched that off in
/// Settings; clicking the icon brings the window back, and its menu opens Sora, turns Sora off
/// (signed in) or quits the app. A hidden window draws nothing; the server and the PC agent are
/// separate processes either way.
class SoraTray with TrayListener, WindowListener {
  SoraTray._();

  static final instance = SoraTray._();

  Session? _session;

  /// Set by the signed-in shell: stops the server and the PC agent, then quits (Settings' "Turn
  /// Sora off").
  Future<void> Function()? _turnOff;

  Future<void> init(Session session) async {
    _session = session;
    await trayManager.setIcon('assets/brand/sora-tray.ico');
    await trayManager.setToolTip('Sora');
    await _menu();
    trayManager.addListener(this);
    windowManager.addListener(this);
    await windowManager.setPreventClose(true);
    session.addListener(_menu); // the language
  }

  set turnOff(Future<void> Function()? f) {
    _turnOff = f;
    _menu();
  }

  bool get _bangla => _session?.language == 'bn';

  Future<void> _menu() => trayManager.setContextMenu(
    Menu(
      items: [
        MenuItem(key: 'open', label: _bangla ? 'Sora খুলুন' : 'Open Sora'),
        MenuItem.separator(),
        if (_turnOff != null) MenuItem(key: 'off', label: _bangla ? 'Sora বন্ধ করুন' : 'Turn Sora off'),
        MenuItem(key: 'quit', label: _bangla ? 'অ্যাপ বন্ধ করুন' : 'Quit the app'),
      ],
    ),
  );

  Future<void> show() async {
    if (await windowManager.isMinimized()) await windowManager.restore();
    await windowManager.show();
    await windowManager.focus();
  }

  /// Closes the app for real (the server keeps running; "Turn Sora off" stops that too).
  Future<void> quit() async {
    await trayManager.destroy(); // or the icon lingers until the mouse passes over it
    await windowManager.setPreventClose(false);
    await windowManager.destroy();
  }

  @override
  void onTrayIconMouseDown() => show();

  @override
  void onTrayIconRightMouseDown() => trayManager.popUpContextMenu();

  @override
  void onTrayMenuItemClick(MenuItem menuItem) {
    switch (menuItem.key) {
      case 'open':
        show();
      case 'off':
        _turnOff?.call();
      case 'quit':
        quit();
    }
  }

  @override
  void onWindowClose() {
    if (_session?.closeToTray ?? true) {
      windowManager.hide();
    } else {
      quit();
    }
  }
}
