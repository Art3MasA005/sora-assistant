import 'package:flutter/material.dart';

/// Sora's design tokens for one theme, from the Claude Design handoff (`sora-data.js` → `TH.dark` /
/// `TH.light`). Names follow the CSS variables: `--surf` → [surf], `--accSoft` → [accSoft] and so on.
@immutable
class SoraPalette extends ThemeExtension<SoraPalette> {
  const SoraPalette({
    required this.dark,
    required this.bg,
    required this.surf,
    required this.surf2,
    required this.glass2,
    required this.sheet,
    required this.line,
    required this.ink,
    required this.dim,
    required this.faint,
    required this.acc,
    required this.accInk,
    required this.accSoft,
    required this.accLine,
    required this.amber,
    required this.amberSoft,
    required this.amberLine,
    required this.ok,
    required this.err,
    required this.errSoft,
    required this.bubble,
    required this.bubbleInk,
    required this.scrim,
    required this.scrimLight,
    required this.segOn,
    required this.fadeTo,
    required this.menuGlass,
    required this.sheen,
    required this.headGlass,
    required this.shadow,
    required this.hi,
    required this.glassBrightness,
    required this.shade,
  });

  final bool dark;

  /// 1 dark, 0 light, in between while the theme fades from one to the other (the background).
  final double shade;
  final Color bg, surf, surf2, glass2, sheet, line, ink, dim, faint;
  final Color acc, accInk, accSoft, accLine;
  final Color amber, amberSoft, amberLine, ok, err, errSoft;
  final Color bubble, bubbleInk, scrim, scrimLight, segOn, fadeTo, menuGlass, sheen, headGlass;

  /// `--shadow`: the big drop shadow under sheets, dialogs and approval cards.
  final List<BoxShadow> shadow;

  /// `--hi`: the crisp highlight edge every glass surface carries.
  final GlassHighlight hi;

  /// The `brightness()` part of `--blur` (1.08 dark, 1.04 light).
  final double glassBrightness;

  static const darkTheme = SoraPalette(
    dark: true,
    bg: Color(0xFF000000),
    surf: Color(0x09FFFFFF), // .035
    surf2: Color(0x12FFFFFF), // .07
    glass2: Color(0x05FFFFFF), // .018
    sheet: Color(0x42080A10), // rgba(8,10,16,.26)
    line: Color(0x29FFFFFF), // .16
    ink: Color(0xFFEEF1F6),
    dim: Color(0xFF9AA2B4),
    faint: Color(0x4DFFFFFF), // .3
    acc: Color(0xFF5CC8FF),
    accInk: Color(0xFF00131D),
    accSoft: Color(0x215CC8FF), // .13
    accLine: Color(0x5C5CC8FF), // .36
    amber: Color(0xFFF5B544),
    amberSoft: Color(0x1AF5B544), // .10
    amberLine: Color(0x66F5B544), // .4
    ok: Color(0xFF3DD68C),
    err: Color(0xFFFF5A67),
    errSoft: Color(0x24FF5A67), // .14
    bubble: Color(0x1AFFFFFF), // .10
    bubbleInk: Color(0xFFEEF1F6),
    scrim: Color(0x66000000), // .4
    scrimLight: Color(0x1F000000), // .12
    segOn: Color(0x24FFFFFF), // .14
    fadeTo: Color(0xE60A0C12), // rgba(10,12,18,.9)
    menuGlass: Color(0x1F0E1018), // rgba(14,16,24,.12)
    sheen: Color(0x1FFFFFFF), // .12
    headGlass: Color(0x47000000), // .28
    shadow: [BoxShadow(color: Color(0x99000000), blurRadius: 50, offset: Offset(0, 18))],
    hi: GlassHighlight(
      top: Color(0x4DFFFFFF), // .30
      bottom: Color(0x0DFFFFFF), // .05
      ring: Color(0x1FFFFFFF), // .12
      ringWidth: 0.5,
    ),
    glassBrightness: 1.08,
    shade: 1,
  );

  static const lightTheme = SoraPalette(
    dark: false,
    bg: Color(0xFFF4F6FA),
    surf: Color(0x47FFFFFF), // .28
    surf2: Color(0x0D10131B), // rgba(16,19,27,.05)
    glass2: Color(0x4DFFFFFF), // .3
    sheet: Color(0x61FFFFFF), // .38
    line: Color(0x1410131B), // .08
    ink: Color(0xFF10131B),
    dim: Color(0xFF566074),
    faint: Color(0x4710131B), // .28
    acc: Color(0xFF4B4FE0),
    accInk: Color(0xFFFFFFFF),
    accSoft: Color(0x174B4FE0), // .09
    accLine: Color(0x4D4B4FE0), // .3
    amber: Color(0xFF9A6206),
    amberSoft: Color(0x99FFF0D2), // rgba(255,240,210,.6)
    amberLine: Color(0xFFEFCF94),
    ok: Color(0xFF12865A),
    err: Color(0xFFD42E3B),
    errSoft: Color(0xB3FDE1E5), // rgba(253,225,229,.7)
    bubble: Color(0xE010131B), // .88
    bubbleInk: Color(0xFFFFFFFF),
    scrim: Color(0x3310131B), // .2
    scrimLight: Color(0x0A10131B), // .04
    segOn: Color(0xD9FFFFFF), // .85
    fadeTo: Color(0xE6FFFFFF), // .9
    menuGlass: Color(0x33FFFFFF), // .2
    sheen: Color(0x99FFFFFF), // .6
    headGlass: Color(0x61F4F6FA), // rgba(244,246,250,.38)
    shadow: [BoxShadow(color: Color(0x2410131B), blurRadius: 50, offset: Offset(0, 18))],
    hi: GlassHighlight(
      top: Color(0xFFFFFFFF),
      bottom: Color(0x00FFFFFF),
      ring: Color(0x73FFFFFF), // .45
      ringWidth: 1,
      outer: BoxShadow(color: Color(0x0D10131B), blurRadius: 2, offset: Offset(0, 1)),
    ),
    glassBrightness: 1.04,
    shade: 0,
  );

  static SoraPalette of(BuildContext context) => Theme.of(context).extension<SoraPalette>()!;

  // Older names still used by screens that have not been rebuilt on the new design yet.
  Color get accent => acc;
  Color get accentDeep => acc;
  Color get accentSoft => accSoft;
  Color get surface => surf;
  Color get surfaceSoft => surf2;
  Color get danger => err;

  @override
  SoraPalette copyWith() => this;

  /// Light ⇄ dark fades every colour across (MaterialApp animates the theme); the ends are the
  /// two constant palettes themselves.
  @override
  SoraPalette lerp(covariant SoraPalette? other, double t) {
    if (other == null || t <= 0) return this;
    if (t >= 1) return other;
    Color c(Color a, Color b) => Color.lerp(a, b, t)!;
    return SoraPalette(
      dark: t < 0.5 ? dark : other.dark,
      bg: c(bg, other.bg),
      surf: c(surf, other.surf),
      surf2: c(surf2, other.surf2),
      glass2: c(glass2, other.glass2),
      sheet: c(sheet, other.sheet),
      line: c(line, other.line),
      ink: c(ink, other.ink),
      dim: c(dim, other.dim),
      faint: c(faint, other.faint),
      acc: c(acc, other.acc),
      accInk: c(accInk, other.accInk),
      accSoft: c(accSoft, other.accSoft),
      accLine: c(accLine, other.accLine),
      amber: c(amber, other.amber),
      amberSoft: c(amberSoft, other.amberSoft),
      amberLine: c(amberLine, other.amberLine),
      ok: c(ok, other.ok),
      err: c(err, other.err),
      errSoft: c(errSoft, other.errSoft),
      bubble: c(bubble, other.bubble),
      bubbleInk: c(bubbleInk, other.bubbleInk),
      scrim: c(scrim, other.scrim),
      scrimLight: c(scrimLight, other.scrimLight),
      segOn: c(segOn, other.segOn),
      fadeTo: c(fadeTo, other.fadeTo),
      menuGlass: c(menuGlass, other.menuGlass),
      sheen: c(sheen, other.sheen),
      headGlass: c(headGlass, other.headGlass),
      shadow: BoxShadow.lerpList(shadow, other.shadow, t)!,
      hi: GlassHighlight(
        top: c(hi.top, other.hi.top),
        bottom: c(hi.bottom, other.hi.bottom),
        ring: c(hi.ring, other.hi.ring),
        ringWidth: hi.ringWidth + (other.hi.ringWidth - hi.ringWidth) * t,
        outer: BoxShadow.lerp(hi.outer, other.hi.outer, t),
      ),
      glassBrightness: glassBrightness + (other.glassBrightness - glassBrightness) * t,
      shade: shade + (other.shade - shade) * t,
    );
  }
}

/// The `--hi` recipe: 1px inset highlight on top, a faint one at the bottom, a hairline ring inside,
/// and (light theme only) a tiny outer shadow.
@immutable
class GlassHighlight {
  const GlassHighlight({
    required this.top,
    required this.bottom,
    required this.ring,
    required this.ringWidth,
    this.outer,
  });

  final Color top, bottom, ring;
  final double ringWidth;
  final BoxShadow? outer;
}

/// Type styles. Outfit for Latin with Hind Siliguri as the Bangla fallback; JetBrains Mono for the
/// small uppercase section labels and status lines.
abstract final class SoraType {
  static const sansFamily = 'Outfit';
  static const banglaFamily = 'HindSiliguri';
  static const monoFamily = 'JetBrainsMono';
  static const fallback = [banglaFamily];

  static TextStyle ui(double size, {FontWeight weight = FontWeight.w400, Color? color, double? height}) =>
      TextStyle(
        fontFamily: sansFamily,
        fontFamilyFallback: fallback,
        fontSize: size,
        fontWeight: weight,
        fontVariations: [FontVariation.weight(weight.value.toDouble())],
        color: color,
        height: height,
      );

  /// `font: 600 10.5px 'JetBrains Mono'; letter-spacing: .12em; text-transform: uppercase`.
  /// Callers pass the text already upper-cased (Bangla has no case, so it is left as is).
  static TextStyle mono(
    double size, {
    FontWeight weight = FontWeight.w600,
    Color? color,
    double spacing = .12,
  }) => TextStyle(
    fontFamily: SoraType.monoFamily,
    fontFamilyFallback: fallback,
    fontSize: size,
    fontWeight: weight,
    fontVariations: [FontVariation.weight(weight.value.toDouble())],
    letterSpacing: size * spacing,
    color: color,
  );
}

ThemeData soraTheme(SoraPalette p) {
  final scheme = (p.dark ? const ColorScheme.dark() : const ColorScheme.light()).copyWith(
    primary: p.acc,
    onPrimary: p.accInk,
    secondary: p.acc,
    surface: p.bg,
    onSurface: p.ink,
    error: p.err,
    outline: p.line,
  );
  final base = ThemeData(brightness: p.dark ? Brightness.dark : Brightness.light, useMaterial3: true);
  OutlineInputBorder border(Color c) => OutlineInputBorder(
    borderRadius: BorderRadius.circular(14),
    borderSide: BorderSide(color: c),
  );
  return base.copyWith(
    colorScheme: scheme,
    extensions: [p],
    scaffoldBackgroundColor: p.bg,
    canvasColor: p.bg,
    textTheme: base.textTheme.apply(
      fontFamily: SoraType.sansFamily,
      fontFamilyFallback: SoraType.fallback,
      bodyColor: p.ink,
      displayColor: p.ink,
    ),
    textSelectionTheme: TextSelectionThemeData(cursorColor: p.acc, selectionColor: p.accSoft, selectionHandleColor: p.acc),
    appBarTheme: AppBarTheme(backgroundColor: Colors.transparent, foregroundColor: p.ink, elevation: 0),
    dividerColor: p.line,
    iconTheme: IconThemeData(color: p.ink),
    splashFactory: InkSparkle.splashFactory,
    highlightColor: Colors.transparent,
    hoverColor: p.surf2,
    listTileTheme: ListTileThemeData(iconColor: p.ink, textColor: p.ink),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: p.surf,
      hintStyle: TextStyle(color: p.faint),
      labelStyle: TextStyle(color: p.dim),
      helperStyle: TextStyle(color: p.dim),
      border: border(p.line),
      enabledBorder: border(p.line),
      focusedBorder: border(p.accLine),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: p.ink,
        foregroundColor: p.bg,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: p.dark ? const Color(0xFF15161A) : p.ink,
      contentTextStyle: TextStyle(color: p.dark ? p.ink : Colors.white),
      behavior: SnackBarBehavior.floating,
    ),
  );
}
