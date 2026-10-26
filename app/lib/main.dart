import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:window_manager/window_manager.dart';

import 'auth/login_screen.dart';
import 'brand/splash_screen.dart';
import 'core/api.dart';
import 'core/session.dart';
import 'desktop/desktop_shell.dart';
import 'desktop/orb_overlay.dart';
import 'desktop/tray.dart';
import 'desktop/title_bar.dart';
import 'l10n/strings.dart';
import 'theme.dart';
import 'voice/wake_service.dart';
import 'shell/home_shell.dart';
import 'shell/layout.dart';
import 'widgets/overlays.dart';

Future<void> main(List<String> args) async {
  WidgetsFlutterBinding.ensureInitialized();
  // The PC agent's corner orb for "Hey Sora" (desktop/orb_overlay.dart): its own small window, not the app.
  if (args.contains('--orb')) return runOrbOverlay(args);
  await initializeDateFormatting(); // English and Bangla dates in lists and cards
  WakeService.initPort();
  final session = await Session.load();
  if (SoraLayout.platformIsDesktop) {
    await _setUpWindow();
    await SoraTray.instance.init(session); // ✕ hides to the notification area
  }
  runApp(SoraApp(session: session));
}

/// Windows: the app draws its own title bar (DesktopTitleBar), so the native one is hidden.
Future<void> _setUpWindow() async {
  await windowManager.ensureInitialized();
  const options = WindowOptions(
    title: 'Sora',
    size: Size(1280, 800),
    minimumSize: Size(960, 620),
    center: true,
    backgroundColor: Color(0xFF0B0B0D),
    titleBarStyle: TitleBarStyle.hidden,
  );
  await windowManager.waitUntilReadyToShow(options, () async {
    await windowManager.show();
    await windowManager.focus();
  });
}

class SoraApp extends StatelessWidget {
  const SoraApp({super.key, required this.session});

  final Session session;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: session,
      builder: (_, _) => MaterialApp(
        title: 'Sora',
        debugShowCheckedModeBanner: false,
        theme: soraTheme(SoraPalette.lightTheme),
        darkTheme: soraTheme(SoraPalette.darkTheme),
        themeMode: session.themeMode,
        // light ⇄ dark fades (SoraPalette.lerp) instead of snapping
        themeAnimationDuration: const Duration(milliseconds: 380),
        themeAnimationCurve: Curves.easeInOut,
        // English by default; Bangla from the menu.
        locale: Locale(session.language),
        supportedLocales: const [Locale('en'), Locale('bn')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        // One backdrop group so the many glass surfaces share a single backdrop read.
        builder: (context, child) => SoraLayout(
          desktop: SoraLayout.platformIsDesktop,
          child: SoraStrings(
            code: session.language,
            child: BackdropGroup(child: ToastHost(child: child!)),
          ),
        ),
        home: _Root(session: session),
      ),
    );
  }
}

/// Splash animation first, then sign-in or the app (chat is home). On desktop the splash and
/// sign-in sit inside the window frame; the signed-in DesktopShell draws its own.
class _Root extends StatefulWidget {
  const _Root({required this.session});

  final Session session;

  @override
  State<_Root> createState() => _RootState();
}

class _RootState extends State<_Root> {
  late final api = SoraApi(widget.session);
  bool _splashDone = false;

  @override
  void initState() {
    super.initState();
    // Android won't start a microphone service at boot, so "Hey Sora" comes back when the app opens.
    final s = widget.session;
    if (s.handsFree && s.signedIn) WakeService.start(bangla: s.language == 'bn');
  }

  @override
  Widget build(BuildContext context) {
    final session = widget.session;
    final desktop = SoraLayout.isDesktop(context);
    final Widget page = !_splashDone
        ? SoraSplash(onDone: () => setState(() => _splashDone = true))
        : session.signedIn
        ? (desktop
              ? DesktopShell(key: ValueKey(session.token), session: session, api: api)
              : HomeShell(key: ValueKey(session.token), session: session, api: api))
        : LoginScreen(session: session);
    if (desktop && !(_splashDone && session.signedIn)) {
      return DesktopFrame(child: AnimatedSwitcher(duration: const Duration(milliseconds: 450), child: page));
    }
    return AnimatedSwitcher(duration: const Duration(milliseconds: 450), child: page);
  }
}
