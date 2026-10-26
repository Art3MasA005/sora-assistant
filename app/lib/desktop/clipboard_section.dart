import 'dart:async';

import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../core/api.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/overlays.dart';
import '../widgets/sora_widgets.dart';
import 'desktop_kit.dart';

/// Details panel → Clipboard: what was copied on the phone or this PC lately (text, or a phone
/// screenshot), newest first. The newest is already on this PC's clipboard (Ctrl+V); the copy button
/// puts an older one back.
class ClipboardSection extends StatefulWidget {
  const ClipboardSection({super.key, required this.api});

  final SoraApi api;

  @override
  State<ClipboardSection> createState() => _ClipboardSectionState();
}

class _ClipboardSectionState extends State<ClipboardSection> {
  Timer? _poll;
  List<Map<String, dynamic>> _items = [];
  bool _enabled = true;
  String? _copying;

  @override
  void initState() {
    super.initState();
    _load();
    _poll = Timer.periodic(const Duration(seconds: 3), (_) => _load());
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final c = await widget.api.clipboard();
      final items = [for (final i in c['items'] as List) Map<String, dynamic>.from(i as Map)];
      final enabled = c['enabled'] != false;
      // every 3 s: rebuild only when something was copied (or the switch changed)
      final same =
          enabled == _enabled &&
          items.length == _items.length &&
          [for (var k = 0; k < items.length; k++) items[k]['id'] == _items[k]['id']].every((x) => x);
      if (!mounted || same) return;
      setState(() {
        _enabled = enabled;
        _items = items;
      });
    } catch (_) {}
  }

  Future<void> _copy(Map<String, dynamic> item) async {
    final s = S.of(context);
    setState(() => _copying = item['id'] as String);
    try {
      await widget.api.copyClipboardItem(item['id'] as String);
      if (mounted) showToast(context, s.copiedToPc);
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message);
    } catch (_) {
      if (mounted) showToast(context, s.serverUnreachable);
    } finally {
      if (mounted) setState(() => _copying = null);
    }
  }

  Future<void> _delete(Map<String, dynamic> item) async {
    setState(() => _items = [..._items]..remove(item));
    try {
      await widget.api.deleteClipboardItem(item['id'] as String);
    } catch (_) {
      _load(); // it comes back as it is on the server
    }
  }

  Future<void> _clear() async {
    final before = _items;
    setState(() => _items = []);
    try {
      await widget.api.clearClipboard();
    } catch (_) {
      if (mounted) setState(() => _items = before);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(child: MonoLabel(s.clipboard)),
            if (_items.isNotEmpty)
              Hover(
                tooltip: s.clearClipboardHint,
                onTap: _clear,
                builder: (_, hover) => Text(
                  s.clear,
                  style: SoraType.ui(12, weight: FontWeight.w500, color: hover ? p.err : p.dim),
                ),
              ),
          ],
        ),
        const SizedBox(height: 8),
        if (!_enabled || _items.isEmpty)
          DashedBox(
            child: Text(_enabled ? s.clipboardEmpty : s.clipboardOff, style: SoraType.ui(13, color: p.dim, height: 1.45)),
          )
        else
          // all the server keeps (20): three show, the rest are a scroll away
          ScrollBox(
            children: [
              // keyed: a new copy fades in at the top, the others keep their place
              for (final item in _items)
                Rise(
                  key: ValueKey(item['id']),
                  offset: 6,
                  child: Padding(padding: const EdgeInsets.only(bottom: 8), child: _item(item, p, s)),
                ),
            ],
          ),
      ],
    );
  }

  Widget _item(Map<String, dynamic> item, SoraPalette p, S s) {
    final phone = item['from'] == 'phone';
    final image = item['kind'] == 'image';
    final at = DateTime.tryParse(item['at'] as String? ?? '')?.toLocal();
    return Glass(
      radius: 14,
      padding: const EdgeInsets.fromLTRB(12, 10, 6, 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (image)
                  ClipRRect(
                    borderRadius: BorderRadius.circular(8),
                    child: Image.network(
                      widget.api.clipboardImageUrl(item['id'] as String),
                      headers: widget.api.authHeader,
                      height: 90,
                      width: double.infinity,
                      fit: BoxFit.cover,
                      errorBuilder: (_, _, _) => Text(item['name'] as String? ?? '', style: SoraType.ui(13, color: p.dim)),
                    ),
                  )
                else
                  Text(
                    item['text'] as String? ?? '',
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                    style: SoraType.ui(13, color: p.ink, height: 1.4),
                  ),
                const SizedBox(height: 6),
                Row(
                  children: [
                    LIcon(phone ? Symbols.smartphone_rounded : Symbols.computer_rounded, size: 13, color: p.dim),
                    const SizedBox(width: 4),
                    Flexible(
                      child: Text(
                        '${phone ? s.fromPhone : s.fromPc} · ${s.ago(at)}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: SoraType.ui(11.5, color: p.dim),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          Column(
            children: [
              Tooltip(
                message: s.copy,
                child: Pressable(
                  onTap: _copying == null ? () => _copy(item) : null,
                  child: SizedBox(
                    width: 32,
                    height: 32,
                    child: Center(
                      child: _copying == item['id']
                          ? Spinner(size: 14, color: p.dim)
                          : LIcon(Symbols.content_copy_rounded, size: 17, color: p.dim),
                    ),
                  ),
                ),
              ),
              Hover(
                tooltip: s.del,
                onTap: () => _delete(item),
                builder: (_, hover) => SizedBox(
                  width: 32,
                  height: 32,
                  child: Center(child: LIcon(Symbols.delete_rounded, size: 17, color: hover ? p.err : p.dim)),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
