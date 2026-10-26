import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:sora/chat/chat_models.dart';
import 'package:sora/core/api.dart';
import 'package:sora/orb/orb_controller.dart';
import 'package:sora/orb/particle_orb.dart';
import 'package:sora/brand/splash_screen.dart';
import 'package:sora/l10n/strings.dart';
import 'package:sora/theme.dart';
import 'package:sora/voice/speaker.dart';
import 'package:sora/voice/voice_input.dart';
import 'package:sora/widgets/sora_widgets.dart';
import 'package:sora/widgets/markdown_lite.dart';
import 'package:material_symbols_icons/symbols.dart';

void main() {
  setUpAll(initializeDateFormatting);

  test('SSE parser yields typed agent events and skips comments/blank lines', () async {
    final lines = Stream.fromIterable([
      ': OPENROUTER PROCESSING',
      'event: conversation',
      'data: {"type": "conversation", "id": "c1", "title": "hi"}',
      '',
      'event: delta',
      'data: {"type": "delta", "text": "আমি "}',
      '',
      'data: {"type": "done", "conversation_id": "c1", "status": "complete"}',
    ]);
    final events = await SoraApi.parseSse(lines).toList();
    expect(events.map((e) => e.type), ['conversation', 'delta', 'done']);
    expect(events[1].data['text'], 'আমি ');
  });

  test('orb colours follow the state and pitch shifts the hue', () {
    final orb = OrbController()..state = OrbState.speaking;
    for (var i = 0; i < 400; i++) {
      orb.tick(1 / 60);
    }
    expect(orb.a[0], closeTo(304, 1)); // speaking magenta
    orb.setInput(0.8, pitchHz: 290); // high voice → hue moves warmer
    for (var i = 0; i < 400; i++) {
      orb.tick(1 / 60);
    }
    expect(orb.level, greaterThan(0.5));
    expect((orb.a[0] - 332).abs(), lessThan(3));
  });

  test('markdown markers are dropped for speech', () {
    expect(stripMarkdown('১. **Cse project** — `due`\n- item'), '১. Cse project — due\nitem');
  });

  testWidgets('markdown renders bold without the asterisks, bullets and numbered badges', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: soraTheme(SoraPalette.darkTheme),
        home: const Scaffold(body: MarkdownLite('আছে **দুটি কাজ** বাকি\n- প্রথম\n2. দ্বিতীয়')),
      ),
    );
    final rich = tester.widgetList<RichText>(find.byType(RichText)).map((r) => r.text.toPlainText()).toList();
    expect(rich, contains('আছে দুটি কাজ বাকি'));
    expect(rich, contains('প্রথম'));
    expect(rich, contains('২')); // Bangla digits in the number badge for Bangla text
    final para = tester.widgetList<RichText>(find.byType(RichText)).firstWhere((r) => r.text.toPlainText() == 'আছে দুটি কাজ বাকি');
    TextSpan? bold;
    para.text.visitChildren((span) {
      if (span is TextSpan && span.text == 'দুটি কাজ') bold = span;
      return bold == null;
    });
    expect(bold!.style!.fontWeight, FontWeight.w600);
  });

  testWidgets('markdown tables render as a grid without the pipes', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: soraTheme(SoraPalette.darkTheme),
        home: const Scaffold(
          body: MarkdownLite('Inbox:\n| # | From | Subject |\n|---|---|---|\n| 1 | Rafi | **Slides** |\n| 2 | Zoom | Promo |'),
        ),
      ),
    );
    expect(find.byType(Table), findsOneWidget);
    final texts = tester.widgetList<RichText>(find.byType(RichText)).map((r) => r.text.toPlainText()).toList();
    expect(texts, containsAll(['From', 'Rafi', 'Slides', 'Promo']));
    expect(texts.any((t) => t.contains('|')), isFalse);
  });

  test('approval cards show the email as fields + body, and know when Sora asks because of an email', () {
    final a = Approval({
      'action_id': 'a1',
      'tool': 'gmail_send',
      'summary': 'Send email…',
      'args': {'to': 'rafi@x.com', 'cc': '', 'subject': 'Slides', 'body': 'Hi Rafi,\n\nAttached.'},
      'reason': 'tainted',
    });
    final v = ApprovalView.of(a, S.bn);
    expect(v.service, 'Gmail');
    expect(v.title, S.bn.sendEmail);
    expect(v.fields, [('প্রাপক', 'rafi@x.com'), ('বিষয়', 'Slides')]); // empty Cc left out
    expect(v.body, 'Hi Rafi,\n\nAttached.');
    expect(a.tainted, isTrue);
    final other = ApprovalView.of(Approval({'action_id': 'b', 'tool': 'mystery_tool', 'summary': 'Do X\nmore'}), S.en);
    expect((other.title, other.body), ('Do X', 'more'));
  });

  test('list rows show short relative times and reminder times', () {
    final now = DateTime.now();
    expect(S.en.ago(now.subtract(const Duration(seconds: 20))), 'now');
    expect(S.en.ago(now.subtract(const Duration(minutes: 5))), '5 min');
    expect(S.bn.ago(now.subtract(const Duration(minutes: 5))), '৫ মিনিট');
    expect(S.en.ago(DateTime(now.year, now.month, now.day).subtract(const Duration(hours: 3))), 'Yesterday');
    expect(S.en.ago(null), '');
    final tonight = DateTime(now.year, now.month, now.day, 21);
    expect(S.en.when(tonight), 'Today · 9:00 PM');
    expect(S.en.when(tonight.add(const Duration(days: 1))), startsWith('Tomorrow · '));
  });

  test('speech is split into sentences (English and Bangla) without markdown', () {
    expect(
      Speaker.sentences('**Hi!** You have two events.\nআজ ল্যাব আছে। বিকেলে meeting?'),
      ['Hi!', 'You have two events.', 'আজ ল্যাব আছে।', 'বিকেলে meeting?'],
    );
    expect(SoraVoice.byName('Orion').bn, 'bn-BD-PradeepNeural');
    expect(SoraVoice.byName('nobody').name, 'Nova');
  });

  test('voice recording stops after speech then quiet, and gives up when nothing is said', () {
    final e = SpeechEndpointer();
    Endpoint feed(double db, int ms) {
      var r = Endpoint.listening;
      for (var t = 0; t < ms; t += 100) {
        r = e.add(db, 100);
      }
      return r;
    }

    expect(feed(-62, 1000), Endpoint.listening); // a quiet room
    expect(feed(-25, 1500), Endpoint.listening); // talking
    expect(e.heard, isTrue);
    expect(feed(-60, 1000), Endpoint.listening); // a short pause is not the end
    expect(feed(-60, 400), Endpoint.finished);
    final silent = SpeechEndpointer();
    var r = Endpoint.listening;
    for (var t = 0; t < 8000 && r == Endpoint.listening; t += 100) {
      r = silent.add(-58, 100);
    }
    expect(r, Endpoint.noSpeech);
  });

  test('recordings are wrapped as 16 kHz mono WAV and their loudness is measured', () {
    final pcm = Uint8List(32000); // 1 s of silence
    final wav = VoiceRecorder.wav(pcm, 16000);
    expect(String.fromCharCodes(wav.sublist(0, 4)), 'RIFF');
    expect(String.fromCharCodes(wav.sublist(8, 12)), 'WAVE');
    expect(ByteData.sublistView(wav).getUint32(24, Endian.little), 16000);
    expect(wav.length, 44 + 32000);
    expect(VoiceRecorder.levelDb(pcm), -90);
    final loud = ByteData(3200);
    for (var i = 0; i < 1600; i++) {
      loud.setInt16(i * 2, i.isEven ? 16384 : -16384, Endian.little);
    }
    expect(VoiceRecorder.levelDb(loud.buffer.asUint8List()), closeTo(-6, 0.1)); // half scale
  });

  test('tool chips group calls per service and settle to ok or failed', () {
    final m = ChatMessage.sora()
      ..toolStarted('gmail_search')
      ..toolStarted('gmail_read');
    expect(m.tools.keys, ['Gmail']);
    expect(m.tools['Gmail']!.state, ToolState.run);
    m
      ..toolFinished('gmail_search', true)
      ..toolFinished('gmail_read', false);
    expect(m.tools['Gmail']!.state, ToolState.ok);
    m
      ..toolStarted('drive_search')
      ..toolFinished('drive_search', false);
    expect(m.tools['Drive']!.state, ToolState.fail);
    m
      ..committed = 'one'
      ..live = 'two';
    expect(m.text, 'one\n\ntwo');
  });

  test('every Bangla string differs from its English one (no untranslated copy)', () {
    expect(S.bn.greeting, isNot(S.en.greeting));
    expect(S.bn.statusIdle, isNot(S.en.statusIdle));
    expect(S.forCode('xx'), same(S.en)); // English is the default
    expect(S.bn.serviceLabels.keys, containsAll(['gmail', 'calendar', 'drive', 'docs', 'sheets', 'slides']));
  });

  testWidgets('splash plays through and reveals the wordmark', (tester) async {
    var done = false;
    await tester.pumpWidget(
      MaterialApp(
        theme: soraTheme(SoraPalette.lightTheme),
        home: SoraSplash(onDone: () => done = true),
      ),
    );
    await tester.pump(const Duration(milliseconds: 1400)); // mid-roll
    expect(done, isFalse);
    await tester.pump(const Duration(milliseconds: 1600)); // animation over, holding the lockup
    expect(done, isFalse);
    await tester.pump(const Duration(milliseconds: 450)); // 0.4 s hold, then hand over
    expect(done, isTrue);
    expect(find.text('Sora'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  test('tool names become owner-friendly labels', () {
    expect(toolLabel('gmail_search'), 'Gmail');
    expect(toolLabel('reminder_create'), 'Reminder');
    expect(toolLabel('unknownthing'), 'unknownthing');
  });

  testWidgets('particle orb paints frames without errors', (tester) async {
    final orb = OrbController()..state = OrbState.thinking;
    await tester.pumpWidget(
      MaterialApp(
        home: SizedBox(width: 400, height: 400, child: ParticleOrb(controller: orb)),
      ),
    );
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 16));
    }
    expect(find.byType(ParticleOrb), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  for (final palette in [SoraPalette.darkTheme, SoraPalette.lightTheme]) {
    testWidgets('glass kit renders in the ${palette.dark ? 'dark' : 'light'} theme', (tester) async {
      var seg = 'usb';
      var on = false;
      await tester.pumpWidget(
        MaterialApp(
          theme: soraTheme(palette),
          home: BackdropGroup(
            child: Scaffold(
              body: SoraBackground(
                child: StatefulBuilder(
                  builder: (context, set) => Column(
                    children: [
                      GlassIconButton(icon: Symbols.menu_rounded, tooltip: 'Menu', badge: 3, onTap: () {}),
                      SoraSegmented(options: const [('usb', 'USB'), ('ts', 'Tailscale')], value: seg, onChanged: (v) => set(() => seg = v)),
                      SoraSwitch(value: on, onChanged: (v) => set(() => on = v)),
                      const MonoLabel('Connect via'),
                      const InkButton(label: 'Connect', trailing: Symbols.arrow_forward_rounded),
                      const Glass(sheen: true, shadow: true, strong: true, child: SizedBox(height: 40)),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Tailscale'));
      await tester.tap(find.byType(SoraSwitch));
      await tester.pumpAndSettle();
      expect(seg, 'ts');
      expect(on, isTrue);
      expect(find.text('CONNECT VIA'), findsOneWidget);
      expect(find.text('3'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
}
