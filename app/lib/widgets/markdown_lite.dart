import 'package:flutter/material.dart';

import '../theme.dart';

/// Renders the small subset of Markdown the assistant uses, styled like the design's `parseMd`
/// blocks: `#`–`###` headings (16.5/600), `- ` bullets with a 5px accent dot, `1. ` items with a
/// mono number badge, and inline **bold**, *italic* and `code` chips. 15px text, 1.6 line height,
/// 7px between blocks.
class MarkdownLite extends StatelessWidget {
  const MarkdownLite(this.text, {super.key, this.fontSize = 15});

  final String text;
  final double fontSize;

  static final _inline = RegExp(r'\*\*(.+?)\*\*|`([^`]+)`|(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])');
  static final _bullet = RegExp(r'^\s*[-*•]\s+');
  static final _numbered = RegExp(r'^\s*(\d+|[০-৯]+)[.)]\s+');
  static final _heading = RegExp(r'^\s*(#{1,3})\s+');
  static final _bangla = RegExp('[ঀ-৿]');

  // The last parsed messages. Handing back the very same widget lets Flutter skip rebuilding (and
  // re-laying out) every reply on screen while a new one streams in, many times a second.
  static final _cache = <(String, double, SoraPalette), Widget>{};
  static const _keep = 120;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final key = (text, fontSize, p);
    final hit = _cache.remove(key);
    if (hit != null) return _cache[key] = hit; // most recently used last
    final built = _build(p);
    _cache[key] = built;
    if (_cache.length > _keep) _cache.remove(_cache.keys.first);
    return built;
  }

  Widget _build(SoraPalette p) {
    final base = SoraType.ui(fontSize, color: p.ink, height: 1.6);
    final banglaText = _bangla.hasMatch(text);
    final blocks = <Widget>[];
    final lines = text.trim().split('\n');
    for (var li = 0; li < lines.length; li++) {
      final raw = lines[li];
      if (raw.trim().isEmpty) continue;
      if (_isRow(raw)) {
        final rows = <String>[];
        while (li < lines.length && _isRow(lines[li])) {
          rows.add(lines[li++]);
        }
        li--;
        blocks.add(_table(rows, base, p));
        continue;
      }
      final h = _heading.firstMatch(raw);
      if (h != null) {
        final style = SoraType.ui(fontSize + 1.5, weight: FontWeight.w600, color: p.ink, height: 1.35);
        blocks.add(Padding(padding: const EdgeInsets.only(top: 6), child: _rich(raw.substring(h.end), style, p)));
        continue;
      }
      if (_bullet.hasMatch(raw)) {
        blocks.add(
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 5,
                height: 5,
                margin: EdgeInsets.only(top: fontSize * 1.6 / 2 - 2.5),
                decoration: BoxDecoration(color: p.acc, shape: BoxShape.circle),
              ),
              const SizedBox(width: 10),
              Expanded(child: _rich(raw.replaceFirst(_bullet, ''), base, p)),
            ],
          ),
        );
        continue;
      }
      final n = _numbered.firstMatch(raw);
      if (n != null) {
        var label = n.group(1)!;
        if (banglaText) label = label.replaceAllMapped(RegExp('[0-9]'), (m) => '০১২৩৪৫৬৭৮৯'[int.parse(m[0]!)]);
        blocks.add(
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                constraints: const BoxConstraints(minWidth: 20),
                height: 20,
                margin: const EdgeInsets.only(top: 2),
                padding: const EdgeInsets.symmetric(horizontal: 4),
                alignment: Alignment.center,
                decoration: BoxDecoration(color: p.accSoft, borderRadius: BorderRadius.circular(6)),
                child: Text(label, style: SoraType.mono(11.5, color: p.acc, spacing: 0).copyWith(height: 1)),
              ),
              const SizedBox(width: 10),
              Expanded(child: _rich(raw.substring(n.end), base, p)),
            ],
          ),
        );
        continue;
      }
      blocks.add(_rich(raw.trim(), base, p));
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (var i = 0; i < blocks.length; i++) ...[if (i > 0) const SizedBox(height: 7), blocks[i]],
      ],
    );
  }

  static final _divider = RegExp(r'^\s*\|[\s:|-]+\|\s*$');

  static bool _isRow(String line) {
    final t = line.trim();
    return t.startsWith('|') && t.endsWith('|') && t.length > 1;
  }

  static List<String> _cells(String row) {
    final t = row.trim();
    return t.substring(1, t.length - 1).split('|').map((c) => c.trim()).toList();
  }

  /// A Markdown table as a bordered card: tinted header row, hairlines between rows. Narrow columns
  /// (like "#") size to their content; the rest share the width and wrap.
  Widget _table(List<String> rows, TextStyle base, SoraPalette p) {
    final hasHeader = rows.length > 1 && _divider.hasMatch(rows[1]);
    final parsed = rows.where((r) => !_divider.hasMatch(r)).map(_cells).toList();
    if (parsed.isEmpty) return const SizedBox.shrink();
    final n = parsed.map((r) => r.length).reduce((a, b) => a > b ? a : b);
    final cellStyle = base.copyWith(fontSize: 13.5, height: 1.45);
    final headStyle = SoraType.ui(12.5, weight: FontWeight.w600, color: p.dim, height: 1.4);
    return Container(
      decoration: BoxDecoration(color: p.surf, borderRadius: BorderRadius.circular(14), border: Border.all(color: p.line)),
      clipBehavior: Clip.antiAlias,
      child: Table(
        columnWidths: {
          for (var c = 0; c < n; c++)
            c: parsed.every((r) => c >= r.length || r[c].length <= 4) ? const IntrinsicColumnWidth() : const FlexColumnWidth(),
        },
        border: TableBorder(horizontalInside: BorderSide(color: p.line)),
        children: [
          for (final (i, r) in parsed.indexed)
            TableRow(
              decoration: hasHeader && i == 0 ? BoxDecoration(color: p.surf2) : null,
              children: [
                for (var c = 0; c < n; c++)
                  Padding(
                    padding: EdgeInsets.fromLTRB(c == 0 ? 12 : 6, 9, c == n - 1 ? 12 : 6, 9),
                    child: hasHeader && i == 0
                        ? Text(c < r.length ? stripMarkdown(r[c]) : '', style: headStyle)
                        : _rich(c < r.length ? r[c] : '', cellStyle, p),
                  ),
              ],
            ),
        ],
      ),
    );
  }

  Widget _rich(String line, TextStyle style, SoraPalette p) =>
      Text.rich(TextSpan(style: style, children: inlineSpans(line, style, p)));

  static List<InlineSpan> inlineSpans(String line, TextStyle style, SoraPalette p) {
    final out = <InlineSpan>[];
    var last = 0;
    for (final m in _inline.allMatches(line)) {
      if (m.start > last) out.add(TextSpan(text: line.substring(last, m.start)));
      if (m.group(1) != null) {
        out.add(TextSpan(text: m.group(1), style: style.copyWith(fontWeight: FontWeight.w600, fontVariations: const [FontVariation.weight(600)])));
      } else if (m.group(2) != null) {
        out.add(
          WidgetSpan(
            alignment: PlaceholderAlignment.middle,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
              decoration: BoxDecoration(
                color: p.surf2,
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: p.line),
              ),
              child: Text(
                m.group(2)!,
                style: SoraType.mono((style.fontSize ?? 15) * .86, weight: FontWeight.w400, spacing: 0, color: p.ink),
              ),
            ),
          ),
        );
      } else {
        out.add(TextSpan(text: m.group(3), style: const TextStyle(fontStyle: FontStyle.italic)));
      }
      last = m.end;
    }
    if (last < line.length) out.add(TextSpan(text: line.substring(last)));
    return out;
  }
}

/// Plain text for speech and copying: drops the Markdown markers.
String stripMarkdown(String text) => text
    .replaceAllMapped(RegExp(r'\*\*(.+?)\*\*'), (m) => m.group(1)!)
    .replaceAllMapped(RegExp(r'`([^`]+)`'), (m) => m.group(1)!)
    .replaceAll(RegExp(r'^#{1,3}\s+', multiLine: true), '')
    .replaceAll(RegExp(r'^\s*[-*•]\s+', multiLine: true), '');
