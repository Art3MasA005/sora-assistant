import 'dart:typed_data';

/// 3D value noise, the same lattice + permutation as the web prototype (seed 1337).
class ValueNoise {
  ValueNoise() {
    final p = List<int>.generate(256, (i) => i);
    var s = 1337;
    for (var i = 255; i > 0; i--) {
      s = (s * 16807) % 2147483647;
      final j = s % (i + 1);
      final t = p[i];
      p[i] = p[j];
      p[j] = t;
    }
    for (var i = 0; i < 512; i++) {
      _perm[i] = p[i & 255];
    }
  }

  final _perm = Uint8List(512);

  double _h(int x, int y, int z) => _perm[(_perm[(_perm[x & 255] + y) & 255] + z) & 255] / 255.0;

  static double _fade(double t) => t * t * (3 - 2 * t);
  static double _lerp(double a, double b, double t) => a + (b - a) * t;

  double sample(double x, double y, double z) {
    final xi = x.floor(), yi = y.floor(), zi = z.floor();
    final xf = _fade(x - xi), yf = _fade(y - yi), zf = _fade(z - zi);
    return _lerp(
      _lerp(_lerp(_h(xi, yi, zi), _h(xi + 1, yi, zi), xf), _lerp(_h(xi, yi + 1, zi), _h(xi + 1, yi + 1, zi), xf), yf),
      _lerp(
        _lerp(_h(xi, yi, zi + 1), _h(xi + 1, yi, zi + 1), xf),
        _lerp(_h(xi, yi + 1, zi + 1), _h(xi + 1, yi + 1, zi + 1), xf),
        yf,
      ),
      zf,
    );
  }
}
