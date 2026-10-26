import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../l10n/strings.dart';
import '../shell/layout.dart';
import '../theme.dart';
import 'sora_widgets.dart';

/// Something to do with the (possibly cropped) screenshot: Save, Send, Copy…
class ShotAction {
  const ShotAction(this.icon, this.label, this.run);

  final IconData icon;
  final String label;
  final Future<void> Function(BuildContext context, Uint8List png) run;
}

/// Shows a screenshot to look at, crop (drag over the part to keep) and pass on with [actions].
/// On the phone it opens full screen, pinch to zoom (a sheet would follow the finger and bounce);
/// on the PC as a dialog.
Future<void> showScreenshot(BuildContext context, {required Uint8List png, required String title, required List<ShotAction> actions}) {
  final view = ScreenshotView(png: png, title: title, actions: actions);
  if (SoraLayout.isDesktop(context)) {
    return showDialog<void>(context: context, barrierColor: Colors.black54, builder: (_) => view);
  }
  return Navigator.of(context).push(
    PageRouteBuilder<void>(
      opaque: true,
      transitionDuration: const Duration(milliseconds: 200),
      reverseTransitionDuration: const Duration(milliseconds: 160),
      pageBuilder: (_, _, _) => view,
      transitionsBuilder: (_, a, _, child) => FadeTransition(opacity: a, child: child),
    ),
  );
}

class ScreenshotView extends StatefulWidget {
  const ScreenshotView({super.key, required this.png, required this.title, required this.actions});

  final Uint8List png;
  final String title;
  final List<ShotAction> actions;

  @override
  State<ScreenshotView> createState() => _ScreenshotViewState();
}

class _ScreenshotViewState extends State<ScreenshotView> {
  late Uint8List _png = widget.png;
  // Decoded once: a new Image.memory on every rebuild would reload (and flash) the picture.
  late MemoryImage _shown = MemoryImage(_png);
  ui.Image? _image;
  bool _cropping = false;
  String? _busy; // the action running
  Offset? _from, _to; // the selection, in the shown image's coordinates
  final _zoom = TransformationController();

  @override
  void initState() {
    super.initState();
    decodeImageFromList(_png).then((image) {
      if (mounted) setState(() => _image = image);
    });
  }

  @override
  void dispose() {
    _zoom.dispose();
    super.dispose();
  }

  Future<void> _run(ShotAction a) async {
    setState(() => _busy = a.label);
    try {
      await a.run(context, _png);
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  void _toggleCrop() => setState(() {
    _cropping = !_cropping;
    _from = _to = null;
    _zoom.value = Matrix4.identity(); // the selection is drawn on the unzoomed picture
  });

  /// Cuts the picture to the selection ([shown] is the size it is drawn at).
  Future<void> _applyCrop(Size shown) async {
    final image = _image, a = _from, b = _to;
    if (image == null || a == null || b == null) return;
    final scale = image.width / shown.width;
    final r = Rect.fromPoints(a, b).intersect(Offset.zero & shown);
    if (r.width < 8 || r.height < 8) return;
    final src = Rect.fromLTRB(r.left * scale, r.top * scale, r.right * scale, r.bottom * scale);
    final recorder = ui.PictureRecorder();
    Canvas(recorder).drawImageRect(image, src, Offset.zero & src.size, Paint()..filterQuality = FilterQuality.high);
    final cropped = await recorder.endRecording().toImage(src.width.round(), src.height.round());
    final data = await cropped.toByteData(format: ui.ImageByteFormat.png);
    if (data == null || !mounted) return;
    setState(() {
      _png = data.buffer.asUint8List();
      _shown = MemoryImage(_png);
      _image = cropped;
      _cropping = false;
      _from = _to = null;
    });
  }

  Widget _picture(SoraPalette p, S s) {
    final image = _image;
    if (image == null) return Center(child: Spinner(size: 24, color: p.acc));
    return Center(
      child: AspectRatio(
        aspectRatio: image.width / image.height,
        child: LayoutBuilder(
          builder: (context, box) {
            final shown = Size(box.maxWidth, box.maxHeight);
            Offset clamp(Offset o) => Offset(o.dx.clamp(0, shown.width).toDouble(), o.dy.clamp(0, shown.height).toDouble());
            final picture = ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: Image(image: _shown, fit: BoxFit.fill, gaplessPlayback: true),
            );
            if (!_cropping) {
              return InteractiveViewer(transformationController: _zoom, minScale: 1, maxScale: 6, child: picture);
            }
            return GestureDetector(
              behavior: HitTestBehavior.opaque,
              onPanStart: (d) => setState(() => _from = _to = clamp(d.localPosition)),
              onPanUpdate: (d) => setState(() => _to = clamp(d.localPosition)),
              child: MouseRegion(
                cursor: SystemMouseCursors.precise,
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    picture,
                    if (_from != null && _to != null) CustomPaint(painter: _CropPainter(Rect.fromPoints(_from!, _to!), p.acc)),
                    if (_from != null && _to != null)
                      Positioned(
                        right: 8,
                        bottom: 8,
                        child: GlassButton(
                          label: s.applyCrop,
                          icon: Symbols.crop_rounded,
                          height: 36,
                          fontSize: 13,
                          onTap: () => _applyCrop(shown),
                        ),
                      ),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }

  List<Widget> _buttons(S s, {required bool expand}) {
    Widget button(IconData icon, String label, VoidCallback? onTap) {
      final b = GlassButton(label: label, icon: icon, height: 40, fontSize: 13.5, onTap: onTap);
      return expand ? Expanded(child: b) : b;
    }

    return [
      button(_cropping ? Symbols.close_rounded : Symbols.crop_rounded, _cropping ? s.cancel : s.crop, _toggleCrop),
      for (final a in widget.actions) ...[
        const SizedBox(width: 8),
        button(_busy == a.label ? Symbols.hourglass_top_rounded : a.icon, a.label, _busy == null ? () => _run(a) : null),
      ],
    ];
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final header = Row(
      children: [
        Expanded(
          child: Text(
            _cropping ? s.cropHint : widget.title,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: SoraType.ui(15, weight: FontWeight.w600, color: p.ink),
          ),
        ),
        IconButton(
          tooltip: s.close,
          onPressed: () => Navigator.pop(context),
          icon: LIcon(Symbols.close_rounded, size: 22, color: p.dim),
        ),
      ],
    );

    if (SoraLayout.isDesktop(context)) {
      final screen = MediaQuery.sizeOf(context);
      return Dialog(
        backgroundColor: Colors.transparent,
        insetPadding: const EdgeInsets.all(24),
        child: Glass(
          radius: 20,
          fill: p.bg,
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              header,
              const SizedBox(height: 8),
              ConstrainedBox(
                constraints: BoxConstraints(maxHeight: screen.height - 220, maxWidth: screen.width - 120, minHeight: 200),
                child: _picture(p, s),
              ),
              const SizedBox(height: 12),
              Row(mainAxisAlignment: MainAxisAlignment.end, children: _buttons(s, expand: false)),
            ],
          ),
        ),
      );
    }

    return Scaffold(
      backgroundColor: p.bg,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 4, 14, 12),
          child: Column(
            children: [
              header,
              Expanded(child: _picture(p, s)),
              const SizedBox(height: 12),
              Row(children: _buttons(s, expand: true)),
            ],
          ),
        ),
      ),
    );
  }
}

/// Dims everything outside the selection and outlines it.
class _CropPainter extends CustomPainter {
  _CropPainter(this.rect, this.color);

  final Rect rect;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final outside = Path()
      ..fillType = PathFillType.evenOdd
      ..addRect(Offset.zero & size)
      ..addRect(rect);
    canvas.drawPath(outside, Paint()..color = Colors.black.withValues(alpha: 0.5));
    canvas.drawRect(
      rect,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
  }

  @override
  bool shouldRepaint(_CropPainter old) => old.rect != rect || old.color != color;
}
