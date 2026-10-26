import 'package:flutter_test/flutter_test.dart';
import 'package:sora/voice/voice_controller.dart';

void main() {
  test('short goodbyes end a hands-free conversation; requests do not', () {
    for (final bye in ['Bye', 'Thank you.', 'Thanks Sora!', 'ok bye', 'ধন্যবাদ', 'ঠিক আছে।', 'ঠিকাছে.', "that's all", 'stop listening']) {
      expect(isGoodbye(bye), isTrue, reason: bye);
    }
    for (final more in ['Thanks, now open YouTube', 'stop the music', 'ঠিক আছে, এবার ইউটিউব খোলো', 'এটা করার জন্য ধন্যবাদ']) {
      expect(isGoodbye(more), isFalse, reason: more);
    }
  });
}
