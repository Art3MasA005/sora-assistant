import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../core/api.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/list_kit.dart';
import '../widgets/overlays.dart';
import '../widgets/sora_widgets.dart';

/// People: the owner's contacts with who they are to them (boss, Ammu, a friend), numbers, emails,
/// nicknames and birthday. Sora calls, texts and emails them by any of those names. The search
/// filters what is loaded (no request per keystroke); the list is built as it scrolls.
class PeopleScreen extends StatefulWidget {
  const PeopleScreen({super.key, required this.api, required this.onBack});

  final SoraApi api;
  final VoidCallback onBack;

  @override
  State<PeopleScreen> createState() => _PeopleScreenState();
}

class _PeopleScreenState extends State<PeopleScreen> {
  List<Map<String, dynamic>>? _items;
  List<Map<String, dynamic>> _shown = const [];
  final _birthdays = <String, int>{}; // id -> days until, for the next week
  String _query = '';
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final list = [for (final p in await widget.api.people()) Map<String, dynamic>.from(p as Map)];
      if (!mounted) return;
      setState(() {
        _items = list;
        _failed = false;
        _note();
      });
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  /// What the list shows (the search) and whose birthday is near: worked out once per change, not per build.
  void _note() {
    final items = _items ?? const [];
    final q = _query.trim().toLowerCase();
    _shown = q.isEmpty ? items : items.where((p) => _haystack(p).contains(q)).toList();
    _birthdays.clear();
    final today = DateUtils.dateOnly(DateTime.now());
    for (final p in items) {
      final b = DateTime.tryParse(p['birthday'] as String? ?? '');
      if (b == null) continue;
      var next = DateTime(today.year, b.month, b.day);
      if (next.isBefore(today)) next = DateTime(today.year + 1, b.month, b.day);
      final days = next.difference(today).inDays;
      if (days <= 7) _birthdays[p['id'] as String] = days;
    }
  }

  static String _haystack(Map<String, dynamic> p) => [
    p['name'],
    p['relation'],
    p['notes'],
    ...?(p['aliases'] as List?),
    ...?(p['phones'] as List?),
    ...?(p['emails'] as List?),
  ].whereType<String>().join(' ').toLowerCase();

  void _search(String q) {
    if (q == _query) return;
    setState(() {
      _query = q;
      _note();
    });
  }

  Future<void> _edit(Map<String, dynamic>? person) async {
    final s = S.of(context);
    final r = await showSoraSheet<Object>(
      context,
      title: person == null ? s.addPerson : s.editPerson,
      builder: (_) => _PersonForm(person: person),
    );
    if (r == null || !mounted) return;
    if (r == _PersonForm.remove) {
      final name = person!['name'] as String? ?? '';
      final ok = await showConfirmSheet(context, title: s.removePerson, text: s.removePersonQ(name), confirm: s.removePerson, danger: true);
      if (!ok || !mounted) return;
      if (await guard(context, () => widget.api.deletePerson(person['id'] as String))) _load();
      return;
    }
    final body = r as Map<String, dynamic>;
    final ok = await guard(
      context,
      () => person == null ? widget.api.addPerson(body) : widget.api.updatePerson(person['id'] as String, body),
    );
    if (ok) _load();
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final items = _items;

    return ListScreen(
      title: s.people,
      onBack: widget.onBack,
      onRefresh: _load,
      action: HeaderAction(icon: Symbols.person_add_rounded, label: s.addPerson, onTap: () => _edit(null)),
      itemCount: items == null ? 0 : _shown.length,
      itemBuilder: (context, i) => _row(p, s, _shown[i]),
      children: [
        if (_failed && items == null)
          EmptyState(icon: Symbols.cloud_off_rounded, text: s.loadFailed)
        else if (items == null)
          Padding(
            padding: const EdgeInsets.all(48),
            child: Center(child: Spinner(size: 22, color: p.acc)),
          )
        else if (items.isEmpty)
          EmptyState(icon: Symbols.group_rounded, text: s.emptyPeople)
        else ...[
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
            child: SearchField(hint: s.searchPeople, onChanged: _search),
          ),
          if (_shown.isEmpty)
            EmptyState(icon: Symbols.search_off_rounded, text: s.noMatch)
          else
            ListSection('${s.people} · ${s.num(_shown.length)}'),
        ],
      ],
    );
  }

  Widget _row(SoraPalette p, S s, Map<String, dynamic> person) {
    final name = person['name'] as String? ?? '';
    final phones = (person['phones'] as List?)?.cast<String>() ?? const [];
    final emails = (person['emails'] as List?)?.cast<String>() ?? const [];
    final relation = person['relation'] as String? ?? '';
    final reach = phones.isNotEmpty ? phones.first : (emails.isNotEmpty ? emails.first : '');
    final soon = _birthdays[person['id']];
    return ListRow(
      key: ValueKey(person['id']),
      onTap: () => _edit(person),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: p.accSoft,
              shape: BoxShape.circle,
              border: Border.all(color: p.accLine),
            ),
            child: Text(
              name.isEmpty ? '?' : name.characters.first.toUpperCase(),
              style: SoraType.ui(16, weight: FontWeight.w600, color: p.acc),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: SoraType.ui(15, weight: FontWeight.w600, color: p.ink),
                ),
                if (relation.isNotEmpty || reach.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(
                    [relation, reach].where((t) => t.isNotEmpty).join(' · '),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: SoraType.ui(12.5, color: p.dim),
                  ),
                ],
                if (soon != null) ...[const SizedBox(height: 4), Tag(s.birthdayIn(soon), color: p.acc, bg: p.accSoft, size: 12)],
              ],
            ),
          ),
          LIcon(Symbols.chevron_right_rounded, size: 20, color: p.dim),
        ],
      ),
    );
  }
}

/// The add / edit form. Pops a body for the API, [remove], or nothing (cancelled).
class _PersonForm extends StatefulWidget {
  const _PersonForm({required this.person});

  final Map<String, dynamic>? person;

  static const remove = 'remove';

  @override
  State<_PersonForm> createState() => _PersonFormState();
}

class _PersonFormState extends State<_PersonForm> {
  late final Map<String, dynamic> _p = widget.person ?? const {};
  late final _name = TextEditingController(text: _p['name'] as String? ?? '');
  late final _relation = TextEditingController(text: _p['relation'] as String? ?? '');
  late final _phones = TextEditingController(text: _joined('phones'));
  late final _emails = TextEditingController(text: _joined('emails'));
  late final _aliases = TextEditingController(text: _joined('aliases'));
  late final _notes = TextEditingController(text: _p['notes'] as String? ?? '');
  late DateTime? _birthday = DateTime.tryParse(_p['birthday'] as String? ?? '');
  bool _nameMissing = false;

  String _joined(String key) => ((_p[key] as List?)?.cast<String>() ?? const []).join(', ');

  static List<String> _split(String text) => text.split(RegExp(r'[,;\n]')).map((t) => t.trim()).where((t) => t.isNotEmpty).toList();

  @override
  void dispose() {
    for (final c in [_name, _relation, _phones, _emails, _aliases, _notes]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _pickBirthday() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: _birthday ?? DateTime(now.year - 25, now.month, now.day),
      firstDate: DateTime(1900),
      lastDate: now,
      initialEntryMode: DatePickerEntryMode.calendarOnly,
    );
    if (picked != null && mounted) setState(() => _birthday = picked);
  }

  void _save() {
    final name = _name.text.trim();
    if (name.isEmpty) {
      setState(() => _nameMissing = true);
      return;
    }
    final b = _birthday;
    Navigator.pop(context, <String, dynamic>{
      'name': name,
      'relation': _relation.text.trim(),
      'phones': _split(_phones.text),
      'emails': _split(_emails.text),
      'aliases': _split(_aliases.text),
      'birthday': b == null
          ? null
          : '${b.year.toString().padLeft(4, '0')}-${b.month.toString().padLeft(2, '0')}-${b.day.toString().padLeft(2, '0')}',
      'notes': _notes.text.trim(),
    });
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final b = _birthday;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _Field(
          label: s.personName,
          hint: s.personNameHint,
          controller: _name,
          autofocus: widget.person == null,
          error: _nameMissing ? s.nameNeeded : null,
        ),
        _Field(label: s.relation, hint: s.relationHint, controller: _relation),
        _Field(label: s.phones, hint: s.phonesHint, controller: _phones, keyboard: TextInputType.phone),
        _Field(label: s.emails, hint: s.emailsHint, controller: _emails, keyboard: TextInputType.emailAddress),
        _Field(label: s.nicknames, hint: s.nicknamesHint, controller: _aliases),
        _Label(s.birthday),
        Row(
          children: [
            Expanded(
              child: Pressable(
                onTap: _pickBirthday,
                child: Glass(
                  height: 46,
                  radius: 14,
                  padding: const EdgeInsets.symmetric(horizontal: 14),
                  child: Row(
                    children: [
                      LIcon(Symbols.cake_rounded, size: 19, color: p.dim),
                      const SizedBox(width: 10),
                      Text(
                        b == null ? s.pickDate : MaterialLocalizations.of(context).formatMediumDate(b),
                        style: SoraType.ui(14.5, color: b == null ? p.faint : p.ink),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            if (b != null) ...[
              const SizedBox(width: 8),
              Pressable(
                onTap: () => setState(() => _birthday = null),
                semanticLabel: s.clear,
                child: Glass(
                  width: 46,
                  height: 46,
                  radius: 14,
                  child: Center(child: LIcon(Symbols.close_rounded, size: 19, color: p.dim)),
                ),
              ),
            ],
          ],
        ),
        const SizedBox(height: 12),
        _Field(label: s.notes, hint: s.notesHint, controller: _notes, lines: 3),
        const SizedBox(height: 4),
        Row(
          children: [
            if (widget.person != null) ...[
              Pressable(
                onTap: () => Navigator.pop(context, _PersonForm.remove),
                semanticLabel: s.removePerson,
                child: Glass(
                  width: 48,
                  height: 48,
                  radius: 14,
                  child: Center(child: LIcon(Symbols.delete_rounded, size: 21, color: p.err)),
                ),
              ),
              const SizedBox(width: 10),
            ],
            Expanded(
              flex: 2,
              child: GlassButton(label: s.cancel, height: 48, radius: 14, onTap: () => Navigator.pop(context)),
            ),
            const SizedBox(width: 10),
            Expanded(
              flex: 3,
              child: AccentButton(label: s.save, onTap: _save),
            ),
          ],
        ),
      ],
    );
  }
}

class _Label extends StatelessWidget {
  const _Label(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(left: 4, bottom: 6),
    child: Text(
      text,
      style: SoraType.ui(12.5, weight: FontWeight.w600, color: SoraPalette.of(context).dim),
    ),
  );
}

/// A labelled glass text field, the text sheets' style.
class _Field extends StatelessWidget {
  const _Field({
    required this.label,
    required this.hint,
    required this.controller,
    this.keyboard,
    this.lines = 1,
    this.autofocus = false,
    this.error,
  });

  final String label, hint;
  final TextEditingController controller;
  final TextInputType? keyboard;
  final int lines;
  final bool autofocus;
  final String? error;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Label(label),
          Glass(
            radius: 14,
            borderColor: error != null ? p.err : null,
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            child: TextField(
              controller: controller,
              autofocus: autofocus,
              keyboardType: lines > 1 ? TextInputType.multiline : keyboard,
              minLines: lines,
              maxLines: lines > 1 ? 6 : 1,
              style: SoraType.ui(14.5, color: p.ink, height: 1.45),
              decoration: InputDecoration(
                hintText: hint,
                hintStyle: SoraType.ui(14.5, color: p.faint, height: 1.45),
                isCollapsed: true,
                filled: false,
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
              ),
            ),
          ),
          if (error != null)
            Padding(
              padding: const EdgeInsets.only(left: 4, top: 4),
              child: Text(error!, style: SoraType.ui(12.5, color: p.err)),
            ),
        ],
      ),
    );
  }
}
