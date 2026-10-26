import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sora/core/api.dart';
import 'package:sora/l10n/strings.dart';
import 'package:sora/lists/people_screen.dart';
import 'package:sora/theme.dart';

/// Only the People calls; anything else the screen asked for would fail the test.
class _FakeApi implements SoraApi {
  _FakeApi(this.items);

  final List<Map<String, dynamic>> items;
  final added = <Map<String, dynamic>>[];

  @override
  Future<List<dynamic>> people() async => items;

  @override
  Future<void> addPerson(Map<String, dynamic> person) async => added.add(person);

  @override
  dynamic noSuchMethod(Invocation invocation) => throw UnimplementedError('${invocation.memberName}');
}

Map<String, dynamic> _person(String id, String name, {String relation = '', List<String> phones = const [], String? birthday}) => {
  'id': id,
  'name': name,
  'relation': relation,
  'phones': phones,
  'emails': <String>[],
  'aliases': <String>[],
  'birthday': birthday,
  'notes': '',
};

void main() {
  test('People strings exist in English and Bangla', () {
    for (final pick in <String Function(S)>[(s) => s.people, (s) => s.emptyPeople, (s) => s.nicknamesHint, (s) => s.birthdayIn(3)]) {
      expect(pick(S.bn), isNot(pick(S.en)));
    }
    expect(S.en.birthdayIn(0), 'Birthday today 🎂');
  });

  testWidgets('the People screen lists, searches and adds someone', (tester) async {
    tester.view.physicalSize = const Size(1000, 1800); // the whole form on screen
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final today = DateTime.now();
    final soon = DateTime(1970, today.month, today.day).toIso8601String().substring(0, 10);
    final api = _FakeApi([
      _person('p1', 'Ayesha Begum', relation: 'mother', phones: ['01911111111'], birthday: soon),
      _person('p2', 'Rahim Uddin', relation: 'boss', phones: ['01711111111']),
    ]);
    await tester.pumpWidget(
      MaterialApp(
        theme: soraTheme(SoraPalette.lightTheme),
        home: PeopleScreen(api: api, onBack: () {}),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Ayesha Begum'), findsOneWidget);
    expect(find.text('boss · 01711111111'), findsOneWidget);
    expect(find.text('Birthday today 🎂'), findsOneWidget);

    await tester.enterText(find.byType(TextField), 'boss');
    await tester.pumpAndSettle();
    expect(find.text('Rahim Uddin'), findsOneWidget);
    expect(find.text('Ayesha Begum'), findsNothing);

    await tester.tap(find.text('Add person').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(find.text('Give a name first.'), findsOneWidget); // nothing saved without a name
    final fields = find.byType(TextField); // the search, then the form: name, relation, phones, emails, nicknames, notes
    await tester.enterText(fields.at(1), 'Tasdid Hasan');
    await tester.enterText(fields.at(3), '01811111111, 01822222222');
    await tester.enterText(fields.at(5), 'Tasdid, তাসদিদ');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(api.added.single['name'], 'Tasdid Hasan');
    expect(api.added.single['phones'], ['01811111111', '01822222222']);
    expect(api.added.single['aliases'], ['Tasdid', 'তাসদিদ']);
    expect(api.added.single['birthday'], isNull);
    expect(tester.takeException(), isNull);
  });
}
