import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../core/api.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/list_kit.dart';
import '../widgets/sora_widgets.dart';
import '../widgets/overlays.dart';

/// Memories: the "How Sora should respond" card (custom instructions + tone), then everything
/// Sora remembers, grouped by the design's four categories. Tap a memory to edit or delete it.
class MemoriesScreen extends StatefulWidget {
  const MemoriesScreen({super.key, required this.api, required this.onBack});

  final SoraApi api;
  final VoidCallback onBack;

  @override
  State<MemoriesScreen> createState() => _MemoriesScreenState();
}

/// The design's categories, and the server's category names they map from / save as.
const _cats = ['people', 'study', 'prefs', 'personal'];

String _catOf(String? server) => switch (server) {
  'person' || 'people' => 'people',
  'study' || 'work' => 'study',
  'preference' || 'prefs' => 'prefs',
  _ => 'personal',
};

String _serverCat(String cat) => switch (cat) {
  'people' => 'person',
  'study' => 'study',
  'prefs' => 'preference',
  _ => 'general',
};

IconData _catIcon(String cat) => switch (cat) {
  'people' => Symbols.group_rounded,
  'study' => Symbols.school_rounded,
  'prefs' => Symbols.tune_rounded,
  _ => Symbols.person_rounded,
};

class _MemoriesScreenState extends State<MemoriesScreen> {
  List<Map<String, dynamic>>? _items;
  String _instructions = '', _tone = 'Warm';
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final results = await Future.wait([widget.api.memories(), widget.api.assistantSettings()]);
      if (!mounted) return;
      final settings = results[1] as Map<String, dynamic>;
      setState(() {
        _items = [for (final m in results[0] as List) Map<String, dynamic>.from(m as Map)];
        _instructions = settings['instructions'] as String? ?? '';
        _tone = settings['tone'] as String? ?? 'Warm';
        _failed = false;
      });
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  Future<void> _editInstructions() async {
    final s = S.of(context);
    final r = await showTextSheet(
      context,
      title: s.instrSheet,
      hint: s.instrPh,
      initial: _instructions,
      allowEmpty: true,
      a: SheetChoice<Object?>([for (final t in const ['Warm', 'Concise', 'Formal']) (t, s.tone(t))], _tone),
    );
    if (r == null || !mounted) return;
    final tone = r.a as String? ?? _tone;
    if (await guard(context, () => widget.api.saveAssistantSettings(r.text, tone))) {
      setState(() {
        _instructions = r.text;
        _tone = tone;
      });
    }
  }

  Future<void> _edit(Map<String, dynamic>? m) async {
    final s = S.of(context);
    final r = await showTextSheet(
      context,
      title: m == null ? s.addMem : s.editMem,
      hint: s.memPh,
      initial: m?['content'] as String? ?? '',
      canDelete: m != null,
      a: SheetChoice<Object?>([for (final c in _cats) (c, s.category(c))], m == null ? 'personal' : _catOf(m['category'] as String?)),
    );
    if (r == null || !mounted) return;
    final ok = await guard(context, () async {
      if (r.delete) {
        await widget.api.deleteMemory(m!['id'] as String);
      } else if (m == null) {
        await widget.api.addMemory(r.text, _serverCat(r.a as String));
      } else {
        await widget.api.patchMemory(m['id'] as String, content: r.text, category: _serverCat(r.a as String));
      }
    });
    if (ok) _load();
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final items = _items;

    Widget row(Map<String, dynamic> m) {
      final cat = _catOf(m['category'] as String?);
      final when = DateTime.tryParse(m['updated_at'] as String? ?? m['created_at'] as String? ?? '')?.toLocal();
      return Rise(
        child: ListRow(
          onTap: () => _edit(m),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              IconTile(icon: _catIcon(cat), size: 36, radius: 11, iconSize: 18),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(m['content'] as String? ?? '', style: SoraType.ui(14.5, color: p.ink, height: 1.45)),
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        Tag(s.category(cat), color: p.ink, bg: p.surf2, size: 12),
                        const SizedBox(width: 8),
                        Text(s.ago(when), style: SoraType.ui(12, color: p.dim)),
                      ],
                    ),
                  ],
                ),
              ),
              Padding(padding: const EdgeInsets.only(top: 2, left: 8), child: LIcon(Symbols.edit_rounded, size: 18, color: p.dim)),
            ],
          ),
        ),
      );
    }

    return ListScreen(
      title: s.memories,
      onBack: widget.onBack,
      onRefresh: _load,
      action: HeaderAction(icon: Symbols.add_rounded, label: s.addMem, onTap: () => _edit(null)),
      children: [
        if (_failed && items == null)
          EmptyState(icon: Symbols.cloud_off_rounded, text: s.loadFailed)
        else if (items == null)
          Padding(padding: const EdgeInsets.all(48), child: Center(child: Spinner(size: 22, color: p.acc)))
        else ...[
          _instructionsCard(p, s),
          if (items.isEmpty)
            EmptyState(icon: Symbols.psychology_rounded, text: s.emptyMem)
          else ...[
            ListSection('${s.memories} · ${s.num(items.length)}'),
            for (final m in items) row(m),
          ],
        ],
      ],
    );
  }

  Widget _instructionsCard(SoraPalette p, S s) => Container(
    margin: const EdgeInsets.fromLTRB(16, 2, 16, 8),
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: p.accSoft, borderRadius: BorderRadius.circular(18), border: Border.all(color: p.accLine)),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            LIcon(Symbols.tune_rounded, size: 18, color: p.acc),
            const SizedBox(width: 8),
            Expanded(child: Text(s.instrTitle, style: SoraType.ui(14, weight: FontWeight.w600, color: p.ink))),
            Pressable(
              onTap: _editInstructions,
              child: Container(
                height: 30,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                alignment: Alignment.center,
                decoration: BoxDecoration(color: p.glass2, borderRadius: BorderRadius.circular(15), border: Border.all(color: p.accLine)),
                child: Text(s.edit, style: SoraType.ui(12.5, weight: FontWeight.w600, color: p.acc)),
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Text(
          _instructions.isEmpty ? s.instrEmpty : _instructions,
          style: SoraType.ui(14, color: _instructions.isEmpty ? p.dim : p.ink, height: 1.5),
        ),
        const SizedBox(height: 8),
        Tag(s.tone(_tone), color: p.acc, bg: p.glass2),
      ],
    ),
  );
}
