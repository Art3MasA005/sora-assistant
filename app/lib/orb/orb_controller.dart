import 'dart:math' as math;

import 'package:flutter/painting.dart';

enum OrbState { idle, listening, thinking, speaking, error }

/// Drives the particle orb: state colours, smoothed loudness and pitch.
/// Feed it [setInput] from the microphone or TTS, call [tick] every frame.
class OrbController {
  OrbController({this.light = false}) {
    final idle = (light ? _lightPalette : _darkPalette)[OrbState.idle]!;
    a.setAll(0, idle[0]);
    b.setAll(0, idle[1]);
  }

  /// Light backgrounds need deeper, normally-blended colours (additive glow vanishes on white).
  /// Switching it mid-run is fine: colours ease toward the new palette.
  bool light;
  OrbState state = OrbState.idle;

  Map<OrbState, List<List<double>>> get _palette => light ? _lightPalette : _darkPalette;

  // For the white design: violet / periwinkle / magenta, a little darker so dots read on white.
  static const Map<OrbState, List<List<double>>> _lightPalette = {
    OrbState.idle: [
      [256, 72, 62],
      [222, 82, 64],
    ],
    OrbState.listening: [
      [252, 80, 60],
      [204, 86, 56],
    ],
    OrbState.thinking: [
      [272, 74, 58],
      [238, 72, 62],
    ],
    OrbState.speaking: [
      [296, 70, 58],
      [330, 80, 62],
    ],
    OrbState.error: [
      [356, 75, 55],
      [16, 85, 55],
    ],
  };

  // Two colours per state (HSL), blended across the sphere; pitch nudges the hue.
  static const Map<OrbState, List<List<double>>> _darkPalette = {
    OrbState.idle: [
      [228, 78, 52],
      [192, 88, 58],
    ],
    OrbState.listening: [
      [204, 95, 55],
      [172, 92, 56],
    ],
    OrbState.thinking: [
      [266, 82, 60],
      [222, 86, 60],
    ],
    OrbState.speaking: [
      [304, 82, 60],
      [334, 90, 64],
    ],
    OrbState.error: [
      [356, 86, 56],
      [16, 92, 56],
    ],
  };
  static const Map<OrbState, double> _swirl = {
    OrbState.idle: 0.0,
    OrbState.listening: 0.1,
    OrbState.thinking: 1.1,
    OrbState.speaking: 0.25,
    OrbState.error: 0.0,
  };

  double _targetLevel = 0, _targetPitch = 0;
  double level = 0; // 0..1, fast attack / slow release
  double pitch = 0; // Hz, 0 = unvoiced
  double swirl = 0;
  double err = 0;
  final List<double> a = [0, 0, 0], b = [0, 0, 0];
  double sensitivity = 1.2;

  /// Loudness 0..1 and pitch in Hz (0 when unknown).
  void setInput(double loudness, {double pitchHz = 0}) {
    _targetLevel = loudness.clamp(0.0, 1.0);
    if (pitchHz > 0) _targetPitch = pitchHz;
  }

  /// Idle breathing so the orb never looks frozen.
  double displayLevel(double clock) {
    final breathe = state == OrbState.idle ? 0.06 + 0.05 * math.sin(clock * 1.4) : 0.0;
    return math.max(level, breathe);
  }

  void tick(double dt) {
    final live = state == OrbState.listening || state == OrbState.speaking;
    final raw = live ? (_targetLevel * sensitivity).clamp(0.0, 1.0) : 0.0;
    level += (raw - level) * (raw > level ? 0.45 : 0.07);
    if (live && _targetPitch > 0) {
      pitch += (_targetPitch - pitch) * 0.2;
    } else {
      pitch += (0 - pitch) * 0.02;
    }

    final p = _palette[state]!;
    final shift = pitch > 0 ? ((pitch - 180) / 110).clamp(-1.0, 1.0) * 28 : 0.0; // higher voice → warmer
    for (var k = 0; k < 2; k++) {
      final target = p[k];
      final c = k == 0 ? a : b;
      c[0] = _hueLerp(c[0], (target[0] + shift + 360) % 360, 0.06);
      c[1] = c[1] + (target[1] - c[1]) * 0.06;
      c[2] = c[2] + ((target[2] + level * 6).clamp(30, 75) - c[2]) * 0.06;
    }
    swirl += (_swirl[state]! - swirl) * 0.04;
    err += ((state == OrbState.error ? 1.0 : 0.0) - err) * 0.08;
  }

  Color get colorA => HSLColor.fromAHSL(1, a[0], a[1] / 100, a[2] / 100).toColor();
  Color get colorB => HSLColor.fromAHSL(1, b[0], b[1] / 100, b[2] / 100).toColor();

  static double _hueLerp(double h1, double h2, double t) {
    final d = ((h2 - h1 + 540) % 360) - 180;
    return (h1 + d * t + 360) % 360;
  }
}
