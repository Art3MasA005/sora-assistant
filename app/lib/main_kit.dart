// Dev-only gallery of the design kit, for checking it against the Claude Design handoff:
//   flutter run -t lib/main_kit.dart
import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import 'auth/login_screen.dart';
import 'brand/sora_logo.dart';
import 'core/session.dart';
import 'l10n/strings.dart';
import 'theme.dart';
import 'widgets/sora_widgets.dart';

void main() => runApp(const _KitApp());

class _KitApp extends StatefulWidget {
  const _KitApp();

  @override
  State<_KitApp> createState() => _KitAppState();
}

class _KitAppState extends State<_KitApp> {
  bool dark = true;

  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    theme: soraTheme(dark ? SoraPalette.darkTheme : SoraPalette.lightTheme),
    builder: (context, child) => BackdropGroup(child: child!),
    home: _Kit(dark: dark, onTheme: (v) => setState(() => dark = v)),
  );
}

class _Kit extends StatefulWidget {
  const _Kit({required this.dark, required this.onTheme});

  final bool dark;
  final ValueChanged<bool> onTheme;

  @override
  State<_Kit> createState() => _KitState();
}

class _KitState extends State<_Kit> {
  String via = 'usb', lang = 'en';
  bool sw = true;
  int chip = 0;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Scaffold(
      body: SoraBackground(
        child: SafeArea(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 6, 16, 24),
            children: [
              Row(
                children: [
                  GlassIconButton(icon: Symbols.menu_rounded, tooltip: 'Menu', badge: 2, onTap: () {}),
                  const Spacer(),
                  Text('Sora', style: SoraType.ui(17, weight: FontWeight.w600)),
                  const Spacer(),
                  GlassIconButton(
                    icon: Symbols.login_rounded,
                    tooltip: 'Sign-in screen',
                    onTap: () async {
                      final session = await Session.load();
                      if (!context.mounted) return;
                      Navigator.of(context).push(
                        MaterialPageRoute<void>(builder: (_) => SoraStrings(code: session.language, child: LoginScreen(session: session))),
                      );
                    },
                  ),
                  const SizedBox(width: 8),
                  GlassIconButton(
                    icon: widget.dark ? Symbols.light_mode_rounded : Symbols.dark_mode_rounded,
                    tooltip: 'Theme',
                    onTap: () => widget.onTheme(!widget.dark),
                  ),
                ],
              ),
              const SizedBox(height: 18),
              Row(
                children: [
                  const SoraMark(size: 54),
                  const SizedBox(width: 12),
                  const SoraMark(size: 30),
                  const Spacer(),
                  SoraSegmented(pill: true, options: const [('en', 'EN'), ('bn', 'বাং')], value: lang, onChanged: (v) => setState(() => lang = v)),
                ],
              ),
              const SizedBox(height: 18),
              Glass(
                radius: 24,
                fill: p.glass2,
                strong: true,
                padding: const EdgeInsets.all(14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const MonoLabel('Connect via'),
                    const SizedBox(height: 8),
                    SoraSegmented(options: const [('usb', 'USB'), ('ts', 'Tailscale')], value: via, onChanged: (v) => setState(() => via = v)),
                    const SizedBox(height: 8),
                    Text('USB cable with adb reverse — the phone reaches the PC at 127.0.0.1.', style: SoraType.ui(12.5, color: p.dim, height: 1.45)),
                    const SizedBox(height: 14),
                    Text('আপনার PIN — বাংলা লেখা Hind Siliguri-তে', style: SoraType.ui(12.5, weight: FontWeight.w500, color: p.dim)),
                    const SizedBox(height: 6),
                    Glass(
                      height: 50,
                      radius: 14,
                      blur: false,
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      child: Row(
                        children: [
                          LIcon(Symbols.dns_rounded, size: 19, color: p.dim),
                          const SizedBox(width: 10),
                          Text('http://127.0.0.1:8000', style: SoraType.mono(13.5, weight: FontWeight.w400, spacing: 0, color: p.ink)),
                        ],
                      ),
                    ),
                    const SizedBox(height: 14),
                    const NoticeRow(text: 'Wrong PIN. 4 tries left.'),
                    const SizedBox(height: 14),
                    const InkButton(label: 'Connect', trailing: Symbols.arrow_forward_rounded),
                  ],
                ),
              ),
              const SizedBox(height: 18),
              Glass(
                radius: 24,
                fill: p.glass2,
                strong: true,
                shadow: true,
                sheen: true,
                padding: const EdgeInsets.all(14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        Container(
                          width: 30,
                          height: 30,
                          decoration: BoxDecoration(
                            color: p.accSoft,
                            borderRadius: BorderRadius.circular(10),
                            border: Border.all(color: p.accLine),
                          ),
                          child: LIcon(Symbols.mail_rounded, size: 17, color: p.acc, fill: true),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const MonoLabel('Needs your OK'),
                              Text('Gmail', style: SoraType.ui(12.5, color: p.dim)),
                            ],
                          ),
                        ),
                        Container(
                          width: 8,
                          height: 8,
                          decoration: BoxDecoration(
                            color: p.acc,
                            shape: BoxShape.circle,
                            boxShadow: [BoxShadow(color: p.accSoft, spreadRadius: 4)],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Text('Send the slides to Rafi?', style: SoraType.ui(16, weight: FontWeight.w600, height: 1.35)),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        const Expanded(flex: 2, child: GlassButton(label: 'No')),
                        const SizedBox(width: 10),
                        Expanded(flex: 3, child: InkButton(label: 'Yes', height: 46, radius: 15, fontSize: 15, onTap: () {})),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 18),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final (i, l) in ['All', 'People', 'Study', 'Preferences'].indexed)
                    SoraChip(label: l, selected: chip == i, onTap: () => setState(() => chip = i)),
                ],
              ),
              const SizedBox(height: 18),
              Glass(
                radius: 16,
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                child: Row(
                  children: [
                    LIcon(Symbols.record_voice_over_rounded, size: 20, color: p.acc),
                    const SizedBox(width: 12),
                    Expanded(child: Text('Read replies aloud', style: SoraType.ui(15))),
                    SoraSwitch(value: sw, onChanged: (v) => setState(() => sw = v)),
                  ],
                ),
              ),
              const SizedBox(height: 18),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  GlassIconButton(icon: Symbols.pause_rounded, tooltip: 'Pause', size: 54, iconSize: 24, onTap: () {}),
                  const SizedBox(width: 34),
                  Spinner(size: 22, color: p.acc),
                  const SizedBox(width: 34),
                  GlassIconButton(icon: Symbols.close_rounded, tooltip: 'Close', size: 54, iconSize: 24, onTap: () {}),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
