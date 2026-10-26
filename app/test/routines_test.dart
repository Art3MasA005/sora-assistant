import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:sora/chat/chat_models.dart';
import 'package:sora/core/api.dart';
import 'package:sora/l10n/strings.dart';
import 'package:sora/lists/routines_screen.dart';
import 'package:sora/theme.dart';
import 'package:sora/widgets/sora_widgets.dart';

/// Only the routine calls; anything else the screen asked for would fail the test.
class _FakeApi implements SoraApi {
  _FakeApi(this.items);

  final List<Map<String, dynamic>> items;
  final patches = <Map<String, Object?>>[];
  final runs = <String>[];

  @override
  Future<List<dynamic>> routines() async => items;

  @override
  Future<Map<String, dynamic>> patchRoutine(String id, {bool? enabled, bool? speak}) async {
    patches.add({'id': id, 'enabled': enabled, 'speak': speak});
    return {'enabled': ?enabled, 'speak': ?speak, 'next_run_at': enabled == false ? null : '2026-10-22T02:00:00+00:00'};
  }

  @override
  Future<void> runRoutine(String id) async => runs.add(id);

  @override
  dynamic noSuchMethod(Invocation invocation) => throw UnimplementedError('${invocation.memberName}');
}

void main() {
  setUpAll(initializeDateFormatting);

  test('routine triggers read naturally in English and Bangla', () {
    expect(S.en.routineWhen({'type': 'time', 'at': '08:00'}), 'Every day · 8:00 AM');
    expect(S.en.routineWhen({'type': 'time', 'at': '07:30', 'days': ['mon', 'wed']}), 'Mon, Wed · 7:30 AM');
    expect(S.en.routineWhen({'type': 'interval', 'minutes': 30}), 'Every 30 minutes');
    expect(S.en.routineWhen({'type': 'interval', 'minutes': 120}), 'Every 2 hours');
    expect(
      S.en.routineWhen({'type': 'email', 'sender': 'gub.edu.bd', 'important_only': true}),
      'When an important email from gub.edu.bd arrives',
    );
    expect(S.en.routineWhen({'type': 'battery_below', 'percent': 20}), 'When the phone battery drops below 20%');
    expect(S.en.routineWhen({'type': 'device_online', 'device': 'phone'}), 'When the phone comes online');
    expect(S.en.routineWhen({'type': 'pc_woke'}), 'When the PC wakes up');

    expect(S.bn.routineWhen({'type': 'interval', 'minutes': 30}), 'প্রতি ৩০ মিনিটে');
    expect(S.bn.routineWhen({'type': 'battery_below', 'percent': 20}), 'ফোনের চার্জ ২০%-এর নিচে নামলে');
    expect(S.bn.routineWhen({'type': 'email', 'sender': 'gub.edu.bd'}), 'gub.edu.bd থেকে ইমেইল এলে');
    expect(S.bn.routineWhen({'type': 'time', 'at': '08:00'}), startsWith('প্রতিদিন · '));
    expect(
      S.en.routineWhen({'type': 'phone_notification', 'app': 'WhatsApp', 'sender': 'Ammu'}),
      'When a WhatsApp notification from Ammu arrives',
    );
    expect(S.bn.routineWhen({'type': 'phone_notification', 'app': 'WhatsApp', 'sender': 'Ammu'}), 'Ammu-এর WhatsApp নোটিফিকেশন এলে');
    for (final type in ['time', 'interval', 'email', 'battery_below', 'device_online', 'device_offline', 'pc_woke', 'phone_notification']) {
      final t = {'type': type, 'at': '08:00', 'minutes': 15, 'percent': 20};
      expect(S.bn.routineWhen(t), isNot(S.en.routineWhen(t)), reason: type);
    }
    expect(S.bn.routines, isNot(S.en.routines));
    expect(toolLabel('routine_create'), 'Routines');
  });

  testWidgets('the Routines screen lists them and switches one off', (tester) async {
    final api = _FakeApi([
      {
        'id': 'r1',
        'name': 'Morning brief',
        'enabled': true,
        'trigger': {'type': 'time', 'at': '08:00'},
        'prompt': 'Tell me my calendar',
        'allowed_actions': ['pc_action:sleep'],
        'speak': true,
        'next_run_at': '2026-10-22T02:00:00+00:00',
        'last_run_at': '2026-10-21T02:00:00+00:00',
        'last_status': 'ok',
        'last_result': 'You have 2 meetings today.',
      },
    ]);
    await tester.pumpWidget(
      MaterialApp(
        theme: soraTheme(SoraPalette.lightTheme),
        home: RoutinesScreen(api: api, onBack: () {}),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Morning brief'), findsOneWidget);
    expect(find.text('Every day · 8:00 AM'), findsOneWidget);
    expect(find.text('You have 2 meetings today.'), findsOneWidget);
    expect(find.text('Runs without asking: pc_action:sleep'), findsOneWidget);
    expect(find.text('Done'), findsOneWidget);
    expect(find.text('Off'), findsNothing);

    await tester.tap(find.byType(SoraSwitch));
    await tester.pumpAndSettle();
    expect(api.patches, [
      {'id': 'r1', 'enabled': false, 'speak': null},
    ]);
    expect(find.text('Off'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
