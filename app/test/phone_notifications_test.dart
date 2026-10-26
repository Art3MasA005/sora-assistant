import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:sora/chat/chat_models.dart';
import 'package:sora/core/api.dart';
import 'package:sora/desktop/phone_notifications_section.dart';
import 'package:sora/l10n/strings.dart';
import 'package:sora/theme.dart';

class _FakeApi implements SoraApi {
  int cleared = 0;

  @override
  Future<Map<String, dynamic>> phoneNotifications() async => {
    'toast': true,
    'items': [
      {'id': 'a', 'app': 'WhatsApp', 'title': 'Ammu', 'text': 'Where are you?', 'at': DateTime.now().toIso8601String()},
    ],
  };

  @override
  Future<void> clearPhoneNotifications() async => cleared++;

  @override
  dynamic noSuchMethod(Invocation invocation) => throw UnimplementedError('${invocation.memberName}');
}

void main() {
  setUpAll(initializeDateFormatting);

  testWidgets('the Details section shows what came and adds new ones as they arrive', (tester) async {
    final api = _FakeApi();
    final live = StreamController<Map<String, dynamic>>.broadcast();
    await tester.pumpWidget(
      MaterialApp(
        theme: soraTheme(SoraPalette.lightTheme),
        home: Scaffold(body: PhoneNotificationsSection(api: api, events: live.stream)),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Ammu'), findsOneWidget);
    expect(find.text('Where are you?'), findsOneWidget);

    live.add({'type': 'clipboard'}); // other events are not for this section
    live.add({
      'type': 'phone_notification',
      'notification': {'id': 'b', 'app': 'Messenger', 'title': 'Karim', 'text': 'On my way', 'at': DateTime.now().toIso8601String()},
    });
    await tester.pumpAndSettle();
    expect(find.text('On my way'), findsOneWidget);
    expect(tester.getTopLeft(find.text('Karim')).dy, lessThan(tester.getTopLeft(find.text('Ammu')).dy)); // newest first

    await tester.tap(find.text('Clear'));
    await tester.pumpAndSettle();
    expect(api.cleared, 1);
    expect(find.text('Karim'), findsNothing);
    await live.close();
  });

  test('approval cards for replying and WhatsApp', () {
    final reply = ApprovalView.of(
      Approval({
        'action_id': '1',
        'tool': 'phone_action',
        'summary': 'Phone: reply to Ammu (WhatsApp): আসছি',
        'args': {'action': 'reply_notification', 'target': '0|com.whatsapp|1|x|10', 'text': 'আসছি'},
      }),
      S.en,
    );
    expect(reply.title, 'Reply from the phone');
    expect(reply.fields.single.$2, 'Ammu (WhatsApp)'); // the person, not the notification's key
    expect(reply.body, 'আসছি');

    final wa = ApprovalView.of(
      Approval({
        'action_id': '2',
        'tool': 'phone_action',
        'summary': 'Phone: WhatsApp Ammu: hi',
        'args': {'action': 'whatsapp_send', 'target': 'Ammu', 'text': 'hi'},
      }),
      S.en,
    );
    expect(wa.service, 'WhatsApp');
    expect(wa.title, 'Send on WhatsApp');

    for (final t in [S.en, S.bn]) {
      expect(t.mirrorNotifs, isNotEmpty);
    }
    expect(S.bn.phoneNotifs, isNot(S.en.phoneNotifs));
    expect(S.bn.mirrorNotifsAccess, isNot(S.en.mirrorNotifsAccess));
  });
}
