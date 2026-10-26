import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../brand/sora_logo.dart';
import '../core/api.dart';
import '../core/server_finder.dart';
import '../core/session.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/sora_widgets.dart';
import '../widgets/overlays.dart';

/// Sign-in from the design: language pill, glowing mark, "Connect via" USB / Tailscale, server
/// address, PIN and device name in one glass card, and the ink Connect button.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.session});

  final Session session;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  static const _usbUrl = 'http://127.0.0.1:8000';

  /// The PC on the home network (it has the server's firewall rule; the app allows plain http to it).
  /// Only a starting guess: the router changes the PC's address now and then, so the app looks for
  /// the server on the Wi-Fi ([ServerFinder]) and fills in the address it finds.
  static const _wifiUrl = 'http://192.168.0.101:8000';

  SoraPalette get p => SoraPalette.of(context);
  S get s => S.of(context);

  late final _server = TextEditingController(
    text: widget.session.serverUrl ?? (Platform.isAndroid ? _wifiUrl : _usbUrl),
  );
  final _pin = TextEditingController();
  late final _device = TextEditingController(
    text: widget.session.deviceName ?? (Platform.isWindows ? 'Windows PC' : 'Android phone'),
  );
  late String _via = _isLocal(_server.text) ? 'usb' : (_isLan(_server.text) ? 'wifi' : 'ts');
  String _tailscaleUrl = 'http://';
  bool _busy = false, _showPin = false, _finding = false;
  String? _error;
  bool _lockedOut = false;
  Timer? _unlock;

  static bool _isLocal(String url) => RegExp(r'//(127\.0\.0\.1|localhost)\b').hasMatch(url);
  static bool _isLan(String url) => RegExp(r'//(192\.168\.|10\.)').hasMatch(url);

  @override
  void initState() {
    super.initState();
    if (_via == 'ts') _tailscaleUrl = _server.text;
    if (_via == 'wifi' && Platform.isAndroid) _findOnWifi();
  }

  Future<void> _findOnWifi() async {
    if (_finding) return;
    setState(() => _finding = true);
    final url = await ServerFinder.scanWifi();
    if (!mounted) return;
    setState(() {
      _finding = false;
      if (url != null && _via == 'wifi') _server.text = url;
    });
  }

  @override
  void dispose() {
    _unlock?.cancel();
    _server.dispose();
    _pin.dispose();
    _device.dispose();
    super.dispose();
  }

  void _setVia(String via) {
    if (via == _via) return;
    setState(() {
      if (_via == 'ts') _tailscaleUrl = _server.text;
      _via = via;
      _server.text = switch (via) { 'usb' => _usbUrl, 'wifi' => _wifiUrl, _ => _tailscaleUrl };
    });
    if (via == 'wifi' && Platform.isAndroid) _findOnWifi();
  }

  Future<void> _connect() async {
    if (_busy || _lockedOut) return;
    final pin = _pin.text.trim();
    if (pin.length < 6) {
      setState(() => _error = s.pinShort);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final server = _server.text.trim().replaceAll(RegExp(r'/+$'), '');
      final device = _device.text.trim();
      final token = await SoraApi.login(server, pin, device);
      await widget.session.signIn(server, token, device: device);
    } on ApiException catch (e) {
      if (e.status == 429) {
        final secs = int.tryParse(RegExp(r'(\d+)s').firstMatch(e.message)?.group(1) ?? '') ?? 300;
        _lockedOut = true;
        _unlock?.cancel();
        _unlock = Timer(Duration(seconds: secs), () {
          if (mounted) setState(() => _lockedOut = false);
        });
        setState(() => _error = s.locked((secs / 60).ceil()));
      } else {
        setState(() => _error = e.unauthorized ? s.wrongPin : e.message);
      }
    } catch (_) {
      setState(() => _error = s.serverUnreachable);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SoraBackground(
        child: SafeArea(
          child: CustomScrollView(
            slivers: [
              SliverFillRemaining(
                hasScrollBody: false,
                child: Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 440),
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(20, 6, 20, 18),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Align(
                            alignment: Alignment.centerRight,
                            child: ListenableBuilder(
                              listenable: widget.session,
                              builder: (context, _) => SoraSegmented(
                                pill: true,
                                options: const [('en', 'EN'), ('bn', 'বাং')],
                                value: widget.session.language,
                                onChanged: widget.session.setLanguage,
                              ),
                            ),
                          ),
                          const SizedBox(height: 22),
                          _brand(),
                          const SizedBox(height: 24),
                          _card(),
                          const Spacer(),
                          const SizedBox(height: 18),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              LIcon(Symbols.verified_user_rounded, size: 15, color: p.dim),
                              const SizedBox(width: 6),
                              Flexible(
                                child: Text(s.secure, textAlign: TextAlign.center, style: SoraType.ui(12.5, color: p.dim)),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _brand() => Column(
    children: [
      SizedBox(
        width: 68,
        height: 68,
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            Positioned(
              left: -14,
              top: -14,
              right: -14,
              bottom: -14,
              child: DecoratedBox(
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: RadialGradient(colors: [p.accSoft, p.accSoft.withAlpha(0)], stops: const [0, .7]),
                ),
              ),
            ),
            Positioned(
              left: -4,
              top: -4,
              right: -4,
              bottom: -4,
              child: DecoratedBox(
                decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: p.accLine)),
              ),
            ),
            const SoraMark(size: 68),
          ],
        ),
      ),
      const SizedBox(height: 16),
      Text(
        s.signTitle,
        textAlign: TextAlign.center,
        style: SoraType.ui(28, weight: FontWeight.w500, color: p.ink, height: 1.15).copyWith(letterSpacing: 28 * -.02),
      ),
      const SizedBox(height: 10),
      ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 280),
        child: Text(s.signInSubtitle, textAlign: TextAlign.center, style: SoraType.ui(14.5, color: p.dim, height: 1.5)),
      ),
    ],
  );

  Widget _card() => Glass(
    radius: 24,
    fill: p.glass2,
    strong: true,
    blur: false, // on the plain background
    padding: const EdgeInsets.all(14),
    child: AutofillGroup(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          MonoLabel(s.connVia),
          const SizedBox(height: 8),
          SoraSegmented(
            options: const [('wifi', 'Wi-Fi'), ('usb', 'USB'), ('ts', 'Tailscale')],
            value: _via,
            onChanged: _setVia,
          ),
          const SizedBox(height: 8),
          Text(
            switch (_via) { 'usb' => s.usbHelp, 'wifi' => s.wifiHelp, _ => s.tsHelp },
            style: SoraType.ui(12.5, color: p.dim, height: 1.45),
          ),
          const SizedBox(height: 14),
          _label(s.server),
          _field(
            icon: Symbols.dns_rounded,
            trailing: _finding && _via == 'wifi'
                ? Tooltip(
                    message: s.findingServer,
                    child: SizedBox(width: 34, height: 34, child: Center(child: Spinner(size: 16, color: p.dim))),
                  )
                : null,
            child: TextField(
              controller: _server,
              keyboardType: TextInputType.url,
              autocorrect: false,
              style: SoraType.mono(13.5, weight: FontWeight.w400, spacing: 0, color: p.ink),
              decoration: _bare(_via == 'ts' ? 'http://100.x.y.z:8000' : null),
            ),
          ),
          const SizedBox(height: 14),
          _label(s.pin),
          _field(
            icon: Symbols.lock_rounded,
            error: _error != null,
            trailing: GestureDetector(
              onTap: () => setState(() => _showPin = !_showPin),
              child: Semantics(
                button: true,
                label: s.showPin,
                child: SizedBox(
                  width: 34,
                  height: 34,
                  child: Center(
                    child: LIcon(
                      _showPin ? Symbols.visibility_off_rounded : Symbols.visibility_rounded,
                      size: 19,
                      color: p.dim,
                    ),
                  ),
                ),
              ),
            ),
            child: TextField(
              controller: _pin,
              obscureText: !_showPin,
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              autofillHints: const [AutofillHints.password],
              style: SoraType.ui(16, color: p.ink).copyWith(letterSpacing: 16 * .18),
              decoration: _bare(s.pinPh),
              onChanged: (_) {
                if (_error != null && !_lockedOut) setState(() => _error = null);
              },
              onSubmitted: (_) => _connect(),
            ),
          ),
          const SizedBox(height: 14),
          _label(s.deviceName),
          _field(
            icon: Symbols.smartphone_rounded,
            child: TextField(controller: _device, style: SoraType.ui(15, color: p.ink), decoration: _bare(null)),
          ),
          if (_error != null) ...[
            const SizedBox(height: 14),
            Rise(
              duration: const Duration(milliseconds: 250),
              child: NoticeRow(text: _error!, icon: _lockedOut ? Symbols.timer_rounded : Symbols.error_rounded),
            ),
          ],
          const SizedBox(height: 16),
          InkButton(
            label: _busy ? s.connecting : s.connect,
            trailing: Symbols.arrow_forward_rounded,
            busy: _busy,
            disabled: _lockedOut,
            onTap: _connect,
          ),
        ],
      ),
    ),
  );

  Widget _label(String text) => Padding(
    padding: const EdgeInsets.only(bottom: 6),
    child: Text(text, style: SoraType.ui(12.5, weight: FontWeight.w500, color: p.dim)),
  );

  InputDecoration _bare(String? hint) => InputDecoration(
    hintText: hint,
    hintStyle: SoraType.ui(15, color: p.faint),
    isCollapsed: true,
    filled: false,
    border: InputBorder.none,
    enabledBorder: InputBorder.none,
    focusedBorder: InputBorder.none,
  );

  /// 50px input box: `--surf` fill, `--line` border (red on error), leading icon.
  Widget _field({required IconData icon, required Widget child, Widget? trailing, bool error = false}) => Container(
    height: 50,
    padding: EdgeInsets.fromLTRB(12, 0, trailing != null ? 4 : 12, 0),
    decoration: BoxDecoration(
      color: p.surf,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: error ? p.err : p.line),
    ),
    child: Row(
      children: [
        LIcon(icon, size: 19, color: p.dim),
        const SizedBox(width: 10),
        Expanded(child: child),
        ?trailing,
      ],
    ),
  );
}
