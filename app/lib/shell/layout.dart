import 'dart:io' show Platform;

import 'package:flutter/widgets.dart';

/// Phone or desktop layout. The Windows app draws one graphite background behind its title bar,
/// sidebars and main column, so screens inside it leave their own background out; sheets become
/// centred dialogs and lists keep to a readable width.
class SoraLayout extends InheritedWidget {
  const SoraLayout({super.key, required this.desktop, required super.child});

  final bool desktop;

  /// Whether this platform gets the desktop app (Windows today).
  static bool get platformIsDesktop => Platform.isWindows || Platform.isLinux || Platform.isMacOS;

  static bool isDesktop(BuildContext context) => context.dependOnInheritedWidgetOfExactType<SoraLayout>()?.desktop ?? false;

  @override
  bool updateShouldNotify(SoraLayout oldWidget) => desktop != oldWidget.desktop;
}
