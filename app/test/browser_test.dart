import 'package:flutter_test/flutter_test.dart';
import 'package:sora/chat/chat_models.dart';
import 'package:sora/l10n/strings.dart';

void main() {
  test('a page watch reads naturally in English and Bangla', () {
    const price = {'type': 'page_change', 'url': 'https://www.daraz.com.bd/products/x', 'minutes': 60, 'contains': '৳'};
    expect(S.en.routineWhen(price), 'When “৳” on daraz.com.bd changes');
    expect(S.bn.routineWhen(price), 'daraz.com.bd-এ “৳” বদলালে');
    const page = {'type': 'page_change', 'url': 'https://gub.edu.bd/notices', 'minutes': 60};
    expect(S.en.routineWhen(page), 'When gub.edu.bd changes');
    expect(S.bn.routineWhen(page), 'gub.edu.bd বদলালে');
    expect(
      S.en.routineWhen({'type': 'page_change', 'url': 'https://a.example', 'selector': '#price'}),
      'When “#price” on a.example changes',
    );
    expect(S.bn.routineUnchanged, isNot(S.en.routineUnchanged));
    expect(S.bn.checkStarted, isNot(S.en.checkStarted));
  });

  test('browser steps show as Browser, and a committing click says what it does', () {
    expect(toolLabel('browser'), 'Browser');
    Approval click(String text) => Approval({
      'action_id': '1',
      'tool': 'browser',
      'summary': 'Browser: press “$text” (it submits, pays, posts or sends)',
      'args': {'action': 'click', 'target': '12', 'text': text, 'value': 1},
    });
    final en = ApprovalView.of(click('Place order'), S.en);
    expect((en.service, en.title, en.body), ('Browser', 'Press “Place order” on the web page', S.en.browserCommits));
    final bn = ApprovalView.of(click('অর্ডার করুন'), S.bn);
    expect(bn.title, 'ওয়েব পেজে “অর্ডার করুন” চাপা');

    final open = ApprovalView.of(
      Approval({
        'action_id': '2',
        'tool': 'browser',
        'summary': 'Browser: open https://a.example',
        'args': {'action': 'open', 'target': 'https://a.example'},
      }),
      S.bn,
    );
    expect(open.title, S.bn.openWebPage);
    expect(open.fields.single, ('লিংক', 'https://a.example'));
  });
}
