import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../core/api.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/list_kit.dart';
import '../widgets/sora_widgets.dart';
import '../widgets/overlays.dart';

/// Knowledge: search, add a Note / Link / Upload, and the saved documents with Rename / Delete.
class KnowledgeScreen extends StatefulWidget {
  const KnowledgeScreen({super.key, required this.api, required this.onBack});

  final SoraApi api;
  final VoidCallback onBack;

  @override
  State<KnowledgeScreen> createState() => _KnowledgeScreenState();
}

class _KnowledgeScreenState extends State<KnowledgeScreen> {
  List<Map<String, dynamic>>? _items;
  bool _failed = false, _busy = false;
  String _q = '';
  Timer? _debounce;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final list = await widget.api.knowledge(q: _q.trim());
      if (mounted) {
        setState(() {
          _items = [for (final d in list) Map<String, dynamic>.from(d as Map)];
          _failed = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  void _search(String q) {
    _q = q;
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), _load);
  }

  /// Runs an add with an "Adding…" / "Added" toast, then reloads.
  Future<void> _adding(Future<void> Function() call) async {
    final s = S.of(context);
    setState(() => _busy = true);
    showToast(context, s.adding);
    final ok = await guard(context, call);
    if (!mounted) return;
    setState(() => _busy = false);
    if (ok) {
      showToast(context, s.added);
      _load();
    }
  }

  Future<void> _addNote() async {
    final s = S.of(context);
    final r = await showTextSheet(context, title: s.addNote, hint: s.notePh, minLines: 4);
    if (r == null || !mounted) return;
    final first = r.text.split('\n').first.trim();
    final title = first.length > 48 ? '${first.substring(0, 48)}…' : first;
    await _adding(() => widget.api.addNote(title, r.text));
  }

  Future<void> _addUrl() async {
    final s = S.of(context);
    final r = await showTextSheet(context, title: s.addUrl, hint: s.urlPh, minLines: 1);
    if (r == null || !mounted) return;
    final url = r.text.startsWith('http') ? r.text : 'https://${r.text}';
    await _adding(() => widget.api.addUrl(url));
  }

  Future<void> _upload() async {
    final s = S.of(context);
    final p = SoraPalette.of(context);
    final pick = await showSoraSheet<bool>(
      context,
      title: s.upload,
      builder: (ctx) => Pressable(
        onTap: () => Navigator.pop(ctx, true),
        child: CustomPaint(
          painter: _DashedBorder(p.accLine, 18),
          child: Container(
            height: 150,
            decoration: BoxDecoration(color: p.accSoft, borderRadius: BorderRadius.circular(18)),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                LIcon(Symbols.upload_file_rounded, size: 32, color: p.acc),
                const SizedBox(height: 8),
                Text(s.chooseFile, style: SoraType.ui(15, weight: FontWeight.w600, color: p.ink)),
                const SizedBox(height: 2),
                Text(s.uploadHint, style: SoraType.ui(12.5, color: p.dim)),
              ],
            ),
          ),
        ),
      ),
    );
    if (pick != true || !mounted) return;
    final file = await FilePicker.pickFile(type: FileType.custom, allowedExtensions: const ['pdf', 'docx', 'txt', 'md', 'html', 'htm']);
    if (file == null || !mounted) return;
    final bytes = await file.xFile.readAsBytes();
    await _adding(() => widget.api.uploadKnowledge(bytes, file.name));
  }

  Future<void> _more(Map<String, dynamic> d) => showActionSheet(
    context,
    title: d['title'] as String? ?? '',
    items: [
      SheetItem(
        icon: Symbols.edit_rounded,
        label: S.of(context).rename,
        onTap: () async {
          Navigator.pop(context);
          final r = await showTextSheet(context, title: S.of(context).rename, initial: d['title'] as String? ?? '', minLines: 1);
          if (r != null && mounted && await guard(context, () => widget.api.renameKnowledge(d['id'] as String, r.text))) _load();
        },
      ),
      SheetItem(
        icon: Symbols.delete_rounded,
        label: S.of(context).del,
        danger: true,
        onTap: () async {
          Navigator.pop(context);
          if (await guard(context, () => widget.api.deleteKnowledge(d['id'] as String))) _load();
        },
      ),
    ],
  );

  static IconData _icon(String? source) => switch (source) {
    'note' => Symbols.sticky_note_2_rounded,
    'url' => Symbols.link_rounded,
    'drive' => Symbols.add_to_drive_rounded,
    _ => Symbols.upload_file_rounded,
  };

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final items = _items;

    Widget tile(IconData icon, String label, VoidCallback onTap) => Expanded(
      child: Pressable(
        onTap: _busy ? null : onTap,
        child: Glass(
          height: 64,
          radius: 14,
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              LIcon(icon, size: 21, color: p.acc),
              const SizedBox(height: 4),
              Text(label, style: SoraType.ui(13, color: p.ink)),
            ],
          ),
        ),
      ),
    );

    return ListScreen(
      title: s.knowledge,
      onBack: widget.onBack,
      onRefresh: _load,
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Column(
            children: [
              SearchField(hint: s.searchKnow, onChanged: _search),
              const SizedBox(height: 10),
              Row(
                children: [
                  tile(Symbols.sticky_note_2_rounded, s.addNote, _addNote),
                  const SizedBox(width: 8),
                  tile(Symbols.link_rounded, s.addUrl, _addUrl),
                  const SizedBox(width: 8),
                  tile(Symbols.upload_file_rounded, s.upload, _upload),
                ],
              ),
            ],
          ),
        ),
        if (_failed && items == null)
          EmptyState(icon: Symbols.cloud_off_rounded, text: s.loadFailed)
        else if (items == null)
          Padding(padding: const EdgeInsets.all(48), child: Center(child: Spinner(size: 22, color: p.acc)))
        else if (items.isEmpty)
          _q.trim().isEmpty
              ? EmptyState(icon: Symbols.menu_book_rounded, text: s.emptyKnow)
              : Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 30),
                  child: Text(s.noMatch, textAlign: TextAlign.center, style: SoraType.ui(14, color: p.dim)),
                )
        else ...[
          const SizedBox(height: 8),
          for (final d in items)
            Rise(
              child: ListRow(
                padding: const EdgeInsets.fromLTRB(14, 10, 8, 10),
                child: Row(
                  children: [
                    IconTile(icon: _icon(d['source'] as String?), iconSize: 20),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            d['title'] as String? ?? '',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: SoraType.ui(14.5, weight: FontWeight.w500, color: p.ink),
                          ),
                          Text(
                            '${s.source(d['source'] as String? ?? '')} · ${s.ago(DateTime.tryParse(d['created_at'] as String? ?? '')?.toLocal())}',
                            style: SoraType.ui(12.5, color: p.dim),
                          ),
                        ],
                      ),
                    ),
                    GestureDetector(
                      onTap: () => _more(d),
                      behavior: HitTestBehavior.opaque,
                      child: SizedBox(width: 34, height: 34, child: Center(child: LIcon(Symbols.more_vert_rounded, size: 20, color: p.dim))),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ],
    );
  }
}

/// 1.5px dashed rounded border (the upload drop zone).
class _DashedBorder extends CustomPainter {
  _DashedBorder(this.color, this.radius);

  final Color color;
  final double radius;

  @override
  void paint(Canvas canvas, Size size) {
    final path = Path()..addRRect(RRect.fromRectAndRadius((Offset.zero & size).deflate(.75), Radius.circular(radius)));
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5
      ..color = color;
    for (final m in path.computeMetrics()) {
      for (var d = 0.0; d < m.length; d += 9) {
        canvas.drawPath(m.extractPath(d, d + 5), paint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _DashedBorder old) => old.color != color;
}
