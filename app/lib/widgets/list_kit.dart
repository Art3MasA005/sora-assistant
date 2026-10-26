import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../l10n/strings.dart';
import '../theme.dart';
import 'sora_widgets.dart';
import 'overlays.dart';

/// Scaffold shared by the list screens: background, [ScreenHeader], pull-to-refresh body.
class ListScreen extends StatelessWidget {
  const ListScreen({
    super.key,
    required this.title,
    required this.onBack,
    required this.onRefresh,
    required this.children,
    this.action,
    this.itemCount = 0,
    this.itemBuilder,
  });

  final String title;
  final VoidCallback onBack;
  final Future<void> Function() onRefresh;
  final List<Widget> children;
  final Widget? action;

  /// A long list after [children], built only as it scrolls into view.
  final int itemCount;
  final IndexedWidgetBuilder? itemBuilder;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SoraBackground(
        child: SafeArea(
          child: Column(
            children: [
              ScreenHeader(title: title, onBack: onBack, action: action),
              Expanded(
                child: RefreshIndicator(
                  color: p.acc,
                  backgroundColor: p.dark ? const Color(0xFF15161A) : Colors.white,
                  onRefresh: onRefresh,
                  child: ListView.builder(
                    physics: const AlwaysScrollableScrollPhysics(),
                    padding: const EdgeInsets.only(bottom: 24),
                    itemCount: children.length + (itemBuilder == null ? 0 : itemCount),
                    itemBuilder: (context, i) => i < children.length ? children[i] : itemBuilder!(context, i - children.length),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// A list row with the design's press state (a glass highlight under the finger).
class ListRow extends StatefulWidget {
  const ListRow({super.key, required this.child, this.onTap, this.padding = const EdgeInsets.fromLTRB(12, 10, 8, 10)});

  final Widget child;
  final VoidCallback? onTap;
  final EdgeInsetsGeometry padding;

  @override
  State<ListRow> createState() => _ListRowState();
}

class _ListRowState extends State<ListRow> {
  bool _down = false;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: widget.onTap,
      onTapDown: widget.onTap == null ? null : (_) => setState(() => _down = true),
      onTapUp: widget.onTap == null ? null : (_) => setState(() => _down = false),
      onTapCancel: () => setState(() => _down = false),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        margin: const EdgeInsets.symmetric(horizontal: 8),
        padding: widget.padding,
        decoration: BoxDecoration(color: _down ? p.surf2 : p.surf2.withAlpha(0), borderRadius: BorderRadius.circular(16)),
        child: widget.child,
      ),
    );
  }
}

/// Square glass tile holding a row's icon (40px, radius 12 by default).
class IconTile extends StatelessWidget {
  const IconTile({super.key, required this.icon, this.size = 40, this.radius = 12, this.iconSize = 19, this.color, this.fill, this.bg, this.fillIcon = false});

  final IconData icon;
  final double size, radius, iconSize;
  final Color? color, fill, bg;
  final bool fillIcon;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    if (bg != null) {
      return Container(
        width: size,
        height: size,
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(radius)),
        child: Center(child: LIcon(icon, size: iconSize, color: color ?? p.acc, fill: fillIcon)),
      );
    }
    return Glass(
      width: size,
      height: size,
      radius: radius,
      fill: fill,
      blur: false,
      child: Center(child: LIcon(icon, size: iconSize, color: color ?? p.acc, fill: fillIcon)),
    );
  }
}

/// 44px glass search box.
class SearchField extends StatelessWidget {
  const SearchField({super.key, required this.hint, required this.onChanged, this.controller});

  final String hint;
  final ValueChanged<String> onChanged;
  final TextEditingController? controller;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Glass(
      height: 44,
      radius: 14,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: Row(
        children: [
          LIcon(Symbols.search_rounded, size: 20, color: p.dim),
          const SizedBox(width: 8),
          Expanded(
            child: TextField(
              controller: controller,
              onChanged: onChanged,
              style: SoraType.ui(14.5, color: p.ink),
              decoration: InputDecoration(
                hintText: hint,
                hintStyle: SoraType.ui(14.5, color: p.faint),
                isCollapsed: true,
                filled: false,
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Small rounded label (status, category, "Important").
class Tag extends StatelessWidget {
  const Tag(this.text, {super.key, required this.color, required this.bg, this.size = 11.5});

  final String text;
  final Color color, bg;
  final double size;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
    decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(8)),
    child: Text(text, maxLines: 1, style: SoraType.ui(size, weight: FontWeight.w600, color: color, height: 1.2)),
  );
}

/// Mono section label inside a list (`PINNED`, `RECENT`, `MEMORIES · 6`).
class ListSection extends StatelessWidget {
  const ListSection(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) =>
      Padding(padding: const EdgeInsets.fromLTRB(20, 14, 20, 4), child: MonoLabel(text, weight: FontWeight.w500));
}

/// One chip group in a text sheet: options as (value, label).
class SheetChoice<T> {
  const SheetChoice(this.options, this.initial);

  final List<(T, String)> options;
  final T initial;
}

/// The design's text sheet: a multi-line field, up to two rows of chips, and Delete / Cancel / Save.
/// Returns the text and the chosen chips, or null when cancelled; `delete: true` when deleted.
Future<({String text, Object? a, Object? b, bool delete})?> showTextSheet(
  BuildContext context, {
  required String title,
  String hint = '',
  String initial = '',
  SheetChoice<Object?>? a,
  SheetChoice<Object?>? b,
  bool canDelete = false,
  bool allowEmpty = false,
  int minLines = 3,
}) {
  final controller = TextEditingController(text: initial);
  var selA = a?.initial, selB = b?.initial;
  return showSoraSheet(
    context,
    title: title,
    builder: (ctx) {
      final p = SoraPalette.of(ctx);
      final s = S.of(ctx);
      return StatefulBuilder(
        builder: (ctx, set) {
          Widget chips(SheetChoice<Object?> c, Object? sel, void Function(Object?) pick) => Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [for (final (v, l) in c.options) SoraChip(label: l, selected: v == sel, onTap: () => set(() => pick(v)))],
          );
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Glass(
                radius: 16,
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                child: TextField(
                  controller: controller,
                  autofocus: true,
                  minLines: minLines,
                  maxLines: 8,
                  style: SoraType.ui(15, color: p.ink, height: 1.5),
                  decoration: InputDecoration(
                    hintText: hint,
                    hintStyle: SoraType.ui(15, color: p.faint, height: 1.5),
                    isCollapsed: true,
                    filled: false,
                    border: InputBorder.none,
                    enabledBorder: InputBorder.none,
                    focusedBorder: InputBorder.none,
                  ),
                ),
              ),
              if (a != null) ...[const SizedBox(height: 14), chips(a, selA, (v) => selA = v)],
              if (b != null) ...[const SizedBox(height: 14), chips(b, selB, (v) => selB = v)],
              const SizedBox(height: 14),
              Row(
                children: [
                  if (canDelete) ...[
                    Pressable(
                      onTap: () => Navigator.pop(ctx, (text: '', a: null, b: null, delete: true)),
                      child: Glass(width: 48, height: 48, radius: 14, child: Center(child: LIcon(Symbols.delete_rounded, size: 21, color: p.err))),
                    ),
                    const SizedBox(width: 10),
                  ],
                  Expanded(flex: 2, child: GlassButton(label: s.cancel, height: 48, radius: 14, onTap: () => Navigator.pop(ctx))),
                  const SizedBox(width: 10),
                  Expanded(
                    flex: 3,
                    child: AccentButton(
                      label: s.save,
                      onTap: () {
                        final v = controller.text.trim();
                        if (v.isEmpty && !allowEmpty) return;
                        Navigator.pop(ctx, (text: v, a: selA, b: selB, delete: false));
                      },
                    ),
                  ),
                ],
              ),
            ],
          );
        },
      );
    },
  );
}

/// A list of actions in a sheet; returns nothing (each item runs its own callback).
Future<void> showActionSheet(BuildContext context, {required String title, required List<SheetItem> items}) =>
    showSoraSheet<void>(context, title: title, builder: (_) => Column(children: items));

/// Confirmation sheet: explanation, Cancel and a confirm button (red when [danger]). An
/// [approval] sheet uses the amber "PC · …" header and No / Yes, like the design's sleep prompt.
Future<bool> showConfirmSheet(
  BuildContext context, {
  required String title,
  required String text,
  required String confirm,
  bool danger = false,
  String? approvalLabel,
}) async {
  final ok = await showSoraSheet<bool>(
    context,
    title: title,
    builder: (ctx) {
      final p = SoraPalette.of(ctx);
      final s = S.of(ctx);
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (approvalLabel != null) ...[
            Row(
              children: [
                LIcon(Symbols.shield_rounded, size: 18, color: p.amber),
                const SizedBox(width: 8),
                Text(approvalLabel.toUpperCase(), style: SoraType.ui(12, weight: FontWeight.w600, color: p.amber).copyWith(letterSpacing: .5)),
              ],
            ),
            const SizedBox(height: 14),
          ],
          Text(text, style: SoraType.ui(15, color: p.dim, height: 1.5)),
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                flex: 2,
                child: GlassButton(label: approvalLabel != null ? s.no : s.cancel, height: 48, radius: 14, onTap: () => Navigator.pop(ctx, false)),
              ),
              const SizedBox(width: 12),
              Expanded(flex: 3, child: AccentButton(label: confirm, danger: danger, onTap: () => Navigator.pop(ctx, true))),
            ],
          ),
        ],
      );
    },
  );
  return ok ?? false;
}

/// Filled accent button (`--accGrad` / `--accInk`), or red for destructive confirmations.
class AccentButton extends StatelessWidget {
  const AccentButton({super.key, required this.label, required this.onTap, this.danger = false, this.height = 48});

  final String label;
  final VoidCallback onTap;
  final bool danger;
  final double height;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    return Pressable(
      onTap: onTap,
      child: Container(
        height: height,
        alignment: Alignment.center,
        decoration: BoxDecoration(color: danger ? p.err : p.acc, borderRadius: BorderRadius.circular(14)),
        child: Text(label, style: SoraType.ui(15, weight: FontWeight.w600, color: danger ? Colors.white : p.accInk)),
      ),
    );
  }
}

/// Small accent pill button (e.g. "Connect", "Edit").
class PillButton extends StatelessWidget {
  const PillButton({super.key, required this.label, required this.onTap, this.filled = false, this.height = 34, this.color});

  final String label;
  final VoidCallback? onTap;
  final bool filled;
  final double height;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final c = color ?? p.acc;
    return Pressable(
      onTap: onTap,
      child: Container(
        height: height,
        padding: const EdgeInsets.symmetric(horizontal: 13),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: filled ? c : p.glass2,
          borderRadius: BorderRadius.circular(height / 2),
          border: filled ? null : Border.all(color: color != null ? c : p.accLine),
        ),
        child: Text(label, style: SoraType.ui(13, weight: FontWeight.w600, color: filled ? (color != null ? const Color(0xFF1A1200) : p.accInk) : c)),
      ),
    );
  }
}

/// Runs an API call and shows its error as a toast; returns true on success.
Future<bool> guard(BuildContext context, Future<void> Function() call) async {
  try {
    await call();
    return true;
  } catch (e) {
    if (context.mounted) showToast(context, e.toString());
    return false;
  }
}
