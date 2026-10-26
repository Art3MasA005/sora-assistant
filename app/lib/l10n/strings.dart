import 'package:flutter/widgets.dart';
import 'package:intl/intl.dart';

/// Every piece of app copy in English (default) and Bangla, side by side. Wording follows the design
/// handoff (`sora-data.js` → `STR.en` / `STR.bn`). Use `S.of(context)`; the language is chosen in
/// Settings or on the sign-in screen and remembered by `Session`.
class S {
  const S._(this.code);

  final String code;
  bool get isBn => code == 'bn';
  String _t(String en, String bn) => isBn ? bn : en;

  static const en = S._('en');
  static const bn = S._('bn');

  static S forCode(String code) => code == 'bn' ? bn : en;

  static S of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<SoraStrings>()?.strings ?? en;

  /// Bangla digits in Bangla, as the design does for counts and list numbers.
  String num(Object n) {
    final s = n.toString();
    if (!isBn) return s;
    const d = '০১২৩৪৫৬৭৮৯';
    return s.replaceAllMapped(RegExp('[0-9]'), (m) => d[int.parse(m[0]!)]);
  }

  // ------------------------------------------------------------------ voice
  String get greeting => _t('How can I help you today?', 'আজ আপনাকে কীভাবে সাহায্য করতে পারি?');
  String get statusIdle => _t('Tap the mic to talk', 'কথা বলতে মাইকে ট্যাপ করুন');
  String get statusListening => _t('Listening…', 'শুনছি…');
  String get statusThinking => _t('Thinking…', 'ভাবছি…');
  String get statusSpeaking => _t('Speaking… tap the button to interrupt', 'বলছি… থামাতে বোতামে ট্যাপ করুন');
  String get statusError => _t('Something went wrong', 'একটি সমস্যা হয়েছে');
  String get voiceEnglish => _t('Voice · English', 'ভয়েস · English');
  String get voiceBangla => _t('Voice · Bangla', 'ভয়েস · বাংলা');
  String get didntCatch => _t("I didn't catch that. Tap the mic to try again.", 'বুঝতে পারিনি। আবার বলতে মাইকে ট্যাপ করুন।');
  String get waitAnswer => _t('Waiting for your answer', 'আপনার উত্তরের অপেক্ষায়');
  String get sayYesNo => _t('Or just say “yes” or “no”.', 'অথবা শুধু বলুন “হ্যাঁ” বা “না”।');
  String get working => _t('Working on it…', 'কাজ করছি…');
  String get onIt => _t('On it…', 'করছি…');
  String get declined => _t("Okay, I won't do that.", 'ঠিক আছে, এটি করছি না।');
  String get confirmPrompt => _t('Shall I go ahead?', 'করব কি?');
  String get noVoiceInput =>
      _t("Voice input isn't available on this device. Use chat instead.", 'এই ডিভাইসে ভয়েস ইনপুট নেই। চ্যাট ব্যবহার করুন।');
  String micProblem(String detail) => _t('Microphone problem ($detail)', 'মাইক্রোফোনে সমস্যা হচ্ছে ($detail)');

  // ------------------------------------------------------------------ common
  String get yes => _t('Yes, go ahead', 'হ্যাঁ, করুন');
  String get no => _t('No', 'না');
  String get menu => _t('Menu', 'মেনু');
  String get pause => _t('Pause', 'থামান');
  String get cancel => _t('Cancel', 'বাতিল');
  String get close => _t('Close', 'বন্ধ করুন');
  String get send => _t('Send', 'পাঠান');
  String get talk => _t('Talk to Sora', 'Sora-র সাথে কথা বলুন');
  String get back => _t('Back', 'ফিরে যান');
  String get save => _t('Save', 'সেভ করুন');
  String get done => _t('Done', 'সম্পন্ন');
  String get comingSoon => _t('Coming in a later update', 'পরের আপডেটে আসছে');
  String get serverUnreachable =>
      _t("Can't reach your Sora server. Check that it's running on your PC.", 'Sora সার্ভারে পৌঁছানো যাচ্ছে না। PC-তে সার্ভার চালু আছে কিনা দেখুন।');
  String get genericError => _t('Something went wrong. Please try again.', 'একটি সমস্যা হয়েছে। আবার চেষ্টা করুন।');

  // ------------------------------------------------------------------ menu / screens
  String get chat => _t('Chat', 'চ্যাট');
  String get voice => _t('Voice', 'ভয়েস');
  String get newChat => _t('New chat', 'নতুন চ্যাট');
  String get conversations => _t('Conversations', 'কথোপকথন');
  String get notifications => _t('Notifications', 'নোটিফিকেশন');
  String get reminders => _t('Reminders', 'রিমাইন্ডার');
  String get routines => _t('Routines', 'রুটিন');
  String get memories => _t('Memories', 'স্মৃতি');
  String get knowledge => _t('Knowledge', 'নলেজ');
  String get connections => _t('Connections', 'কানেকশন');
  String get devices => _t('Devices', 'ডিভাইস');
  String get settings => _t('Settings', 'সেটিংস');
  String get ownerLine => _t('Connected', 'সংযুক্ত');
  String get offline => _t('Offline', 'অফলাইন');

  // ------------------------------------------------------------------ sign in
  String get signTitle => _t('Sign in to Sora', 'Sora-তে সাইন ইন করুন');
  String get signInSubtitle => _t('Connect this device to your Sora server.', 'এই ডিভাইসটি আপনার Sora সার্ভারের সাথে যুক্ত করুন।');
  String get connVia => _t('Connect via', 'যেভাবে যুক্ত হবেন');
  String get usbHelp => _t('Phone plugged into your PC, using adb reverse.', 'ফোন USB দিয়ে PC-তে যুক্ত, adb reverse ব্যবহার করে।');
  String get wifiHelp => _t('Phone and PC on the same home Wi-Fi.', 'ফোন আর PC একই বাসার Wi-Fi-তে।');
  String get tsHelp => _t("Your PC's Tailscale address. Works from anywhere.", 'আপনার PC-র Tailscale ঠিকানা। যেকোনো জায়গা থেকে চলে।');
  String get server => _t('Server address', 'সার্ভারের ঠিকানা');
  String get pin => 'PIN';
  String get pinPh => _t('6 or more digits', '৬ বা তার বেশি সংখ্যা');
  String get showPin => _t('Show PIN', 'PIN দেখান');
  String get deviceName => _t('Device name', 'ডিভাইসের নাম');
  String get connect => _t('Connect', 'সংযুক্ত করুন');
  String get connecting => _t('Connecting…', 'সংযুক্ত হচ্ছে…');
  String get wrongPin => _t("That PIN didn't match. Please try again.", 'PIN মেলেনি। আবার চেষ্টা করুন।');
  String get pinShort => _t('Your PIN has at least 6 digits.', 'আপনার PIN কমপক্ষে ৬ সংখ্যার।');
  String locked(int minutes) => _t(
    'Too many wrong PINs. Try again in ${minutes <= 1 ? 'a minute' : '$minutes minutes'}.',
    'অনেকবার ভুল PIN দেওয়া হয়েছে। ${num(minutes < 1 ? 1 : minutes)} মিনিট পর আবার চেষ্টা করুন।',
  );
  String get secure => _t('Sora only talks to your own server.', 'Sora শুধু আপনার নিজের সার্ভারের সাথেই কথা বলে।');

  // ------------------------------------------------------------------ chat
  String get chatTitle => chat;
  String get messageHint => _t('Type a message', 'একটি বার্তা লিখুন');
  String get tryAsk => _t('Try asking', 'জিজ্ঞেস করে দেখুন');
  String waiting(int n) => _t('$n action${n > 1 ? 's' : ''} waiting for you', '${num(n)}টি কাজ আপনার অপেক্ষায়');
  String checking(String what) => _t('Checking $what…', '$what দেখছি…');
  String get copied => _t('Copied', 'কপি করা হয়েছে');
  String get attachTitle => _t('Add to message', 'বার্তায় যোগ করুন');
  String get camera => _t('Camera', 'ক্যামেরা');
  String get photos => _t('Photos', 'ছবি');
  String get files => _t('Files', 'ফাইল');
  String get attach => _t('Attach', 'যোগ করুন');
  String get exportTitle => _t('Export this chat', 'এই চ্যাট এক্সপোর্ট করুন');
  String get expPdf => _t('Save as PDF', 'PDF হিসেবে সেভ করুন');
  String get expTxt => _t('Save as text', 'টেক্সট হিসেবে সেভ করুন');
  String get expCopy => _t('Copy whole chat', 'পুরো চ্যাট কপি করুন');
  String get export => _t('Export', 'এক্সপোর্ট');
  String get copy => _t('Copy', 'কপি');
  String get goodReply => _t('Good reply', 'ভালো উত্তর');
  String get badReply => _t('Bad reply', 'খারাপ উত্তর');
  String get readAloud => _t('Read aloud', 'পড়ে শোনান');
  String get regenerate => _t('Regenerate', 'আবার লিখুন');
  String get share => _t('Share', 'শেয়ার');
  String get voiceInput => _t('Voice', 'ভয়েস');
  String get you => _t('You', 'আপনি');

  /// Empty-chat suggestions: (icon name, text).
  List<(String, String)> get suggestions => [
    ('calendar_month', _t("What's on my calendar today?", 'আজকের meeting কটায়? Zoom link টা দাও')),
    ('mail', _t('Show my newest emails', 'আমার নতুন ইমেইলগুলো দেখাও')),
    ('alarm', _t('Remind me at 9 pm to call Ammu', 'রাত ৯টায় আম্মুকে ফোন করার কথা মনে করিয়ে দিও')),
    ('event_note', _t('Plan my week', 'এই সপ্তাহের plan বানাও')),
  ];

  // ------------------------------------------------------------------ approvals
  String get needsApproval => _t('Needs your approval', 'আপনার অনুমোদন প্রয়োজন');
  String get actionDone => _t('Done', 'সম্পন্ন হয়েছে');
  String get actionCancelled => _t('Cancelled', 'বাতিল করা হয়েছে');
  String get actionFailed => _t("Couldn't complete this", 'এটি সম্পন্ন করা যায়নি');
  String get actionBusy => working;
  String get showAll => _t('Show full email', 'পুরো ইমেইল দেখুন');
  String get showLess => _t('Show less', 'কম দেখুন');
  String get lines => _t('lines', 'লাইন');
  String get safety =>
      _t('Asking because this chat contains content from an email.', 'জিজ্ঞেস করছি কারণ এই চ্যাটে একটি ইমেইলের তথ্য আছে।');

  /// Approval-card field labels (`FIELD` in the design).
  String field(String key) => !isBn
      ? key
      : const {
              'To': 'প্রাপক',
              'Subject': 'বিষয়',
              'Title': 'শিরোনাম',
              'When': 'সময়',
              'Guests': 'অতিথি',
              'Command': 'কমান্ড',
              'Where': 'স্থান',
              'Event': 'ইভেন্ট',
              'Emails': 'ইমেইল',
              'Item': 'বিষয়',
              'Number': 'নম্বর',
              'Sheet': 'শিট',
              'Rows': 'সারি',
              'Rule': 'নিয়ম',
              'Link': 'লিংক',
              'Project': 'প্রজেক্ট',
              'Terminal': 'টার্মিনাল',
              'File': 'ফাইল',
              'Task': 'টাস্ক',
              'Window': 'উইন্ডো',
              'Setting': 'সেটিং',
              'Also allowed': 'আরও অনুমতি',
            }[key] ??
            key;

  String get sendEmail => _t('Send email', 'ইমেইল পাঠানো');
  String get replyEmail => _t('Reply to email', 'ইমেইলের উত্তর দেওয়া');
  String get trashEmail => _t('Move email to trash', 'ইমেইল ট্র্যাশে সরানো');
  String get createInvite => _t('Create event and invite guests', 'ইভেন্ট তৈরি ও অতিথিদের আমন্ত্রণ');
  String get updateEvent => _t('Update event', 'ইভেন্ট আপডেট করা');
  String get deleteEvent => _t('Delete event', 'ইভেন্ট মুছে ফেলা');
  String get sendSms => _t('Send SMS', 'SMS পাঠানো');
  String get makeCall => _t('Make a call', 'কল করা');
  String get openLink => _t('Open a link', 'লিংক খোলা');
  String phoneAction(String action) => _t('Phone: ${action.replaceAll('_', ' ')}', 'ফোন: ${action.replaceAll('_', ' ')}');
  String get writeSheet => _t('Write to sheet', 'শিটে লেখা');
  String get addToDoc => _t('Add to document', 'ডকুমেন্টে যোগ করা');
  String get deleteKnowledge => _t('Delete from knowledge', 'নলেজ থেকে মুছে ফেলা');
  String get saveMemory => _t('Remember this', 'এটি মনে রাখা');
  String get openWebPage => _t('Open a web page', 'ওয়েব পেজ খোলা');
  String browserPress(String label) => _t('Press “$label” on the web page', 'ওয়েব পেজে “$label” চাপা');
  String get browserCommits => _t('This submits, pays, posts or sends something.', 'এতে কিছু জমা, পেমেন্ট, পোস্ট বা পাঠানো হবে।');
  String get browserType => _t('Type into the web page', 'ওয়েব পেজে লেখা');
  String get downloadFile => _t('Download a file', 'ফাইল ডাউনলোড করা');
  String get vsOpen => _t('Open a project in VS Code', 'VS Code-এ প্রজেক্ট খোলা');
  String get vsRun => _t('Run in the VS Code terminal', 'VS Code-এর টার্মিনালে চালানো');
  String get vsTask => _t('Run a VS Code task', 'VS Code-এর টাস্ক চালানো');
  String get vsDebug => _t('Start debugging', 'ডিবাগ শুরু করা');
  String get vsStop => _t('Stop the command in a terminal', 'টার্মিনালের কমান্ড থামানো');
  String get vsCloseTerminal => _t('Close a terminal', 'টার্মিনাল বন্ধ করা');
  String get vsWrite => _t('Write a file in VS Code', 'VS Code-এ ফাইল লেখা');
  String get vsEdit => _t('Change a file in VS Code', 'VS Code-এ ফাইল বদলানো');
  String get vsRename => _t('Rename a file', 'ফাইলের নাম বদলানো');
  String get vsDelete => _t('Delete a file (to the Recycle Bin)', 'ফাইল মোছা (Recycle Bin-এ)');
  String get vsCommand => _t('Run a VS Code command', 'VS Code-এর কমান্ড চালানো');
  String get vsSetting => _t('Change a VS Code setting', 'VS Code-এর সেটিং বদলানো');
  String get vsInstallExt => _t('Install a VS Code extension', 'VS Code এক্সটেনশন ইনস্টল করা');
  String get gitCommit => _t('Git commit', 'Git commit করা');
  String get gitPush => _t('Git push', 'Git push করা');
  String get gitPull => _t('Git pull', 'Git pull করা');
  String get gitBranch => _t('Switch git branch', 'Git branch বদলানো');
  String get claudeStart => _t('Give Claude Code a job', 'Claude Code-কে কাজ দেওয়া');
  String get claudeContinue => _t('Let Claude Code carry on', 'Claude Code-কে কাজ চালিয়ে যেতে দেওয়া');
  String get claudeMayEdit => _t('It may edit the project’s files.', 'প্রজেক্টের ফাইল বদলাতে পারবে।');
  String pcAction(String action) => _t('PC: ${action.replaceAll('_', ' ')}', 'PC: ${action.replaceAll('_', ' ')}');

  // ------------------------------------------------------------------ desktop
  String get conversationsL => _t('Conversations', 'কথোপকথন');
  String get details => _t('Details', 'বিবরণ');
  String get waitingForYou => _t('Waiting for you', 'আপনার অপেক্ষায়');
  String get nothingWaiting => _t('Nothing is waiting for you.', 'কোনো কাজ অপেক্ষায় নেই।');
  String get activity => _t("Sora's activity", 'Sora-র কাজ');
  String get activityEmpty => _t('What Sora does for you shows up here.', 'Sora আপনার জন্য যা করে, তা এখানে দেখা যাবে।');
  String get hideSidebar => _t('Hide sidebar', 'সাইডবার লুকান');
  String get showSidebar => _t('Show sidebar', 'সাইডবার দেখান');
  String get hidePanel => _t('Hide panel', 'প্যানেল লুকান');
  String get showPanel => _t('Show panel', 'প্যানেল দেখান');
  String get minimize => _t('Minimize', 'ছোট করুন');
  String get maximize => _t('Maximize', 'বড় করুন');
  String get restore => _t('Restore', 'আগের মাপে');
  String pcOf(String name) => _t("$name's PC", '$name-এর PC');

  // ------------------------------------------------------------------ list screens
  String get searchConv => _t('Search conversations', 'কথোপকথন খুঁজুন');
  String get pinned => _t('Pinned', 'পিন করা');
  String get recent => _t('Recent', 'সাম্প্রতিক');
  String get pinIt => _t('Pin', 'পিন করুন');
  String get unpin => _t('Unpin', 'পিন সরান');
  String get rename => _t('Rename', 'নাম বদলান');
  String get archive => _t('Archive', 'আর্কাইভ করুন');
  String get del => _t('Delete', 'মুছে ফেলুন');
  String get edit => _t('Edit', 'এডিট');
  String get more => _t('More', 'আরও');
  String get noMatch => _t('Nothing matches that search.', 'এই খোঁজের সাথে কিছু মেলেনি।');
  String get emptyConv => _t('No conversations yet.', 'এখনও কোনো কথোপকথন নেই।');
  String get emptyNotif => _t("You're all caught up.", 'নতুন কিছু নেই, সব দেখা হয়ে গেছে।');
  String get emptyRem => _t('No reminders. Try: “Remind me at 9 pm to call Ammu.”', 'কোনো রিমাইন্ডার নেই। বলে দেখুন: “রাত ৯টায় আম্মুকে ফোন করার কথা মনে করিয়ে দিও।”');
  String get emptyMem => _t("Sora hasn't learned anything about you yet.", 'Sora এখনও আপনার সম্পর্কে কিছু শেখেনি।');
  String get emptyKnow => _t('Add notes or files so Sora can answer from them.', 'নোট বা ফাইল যোগ করুন, Sora সেগুলো থেকে উত্তর দেবে।');
  String get loadFailed => _t("Couldn't load this. Pull down to try again.", 'লোড করা যায়নি। আবার চেষ্টা করতে নিচে টানুন।');
  String get markAll => _t('Mark all read', 'সব পঠিত');
  String get deleteAllNotif => _t('Delete all', 'সব মুছুন');
  String get deleteAllNotifQ => _t('All notifications are deleted. This can’t be undone.', 'সব নোটিফিকেশন মুছে যাবে। আর ফেরানো যাবে না।');
  String get rules => _t('Email rules', 'ইমেইল নিয়ম');
  String get rulesHint => _t('Sora tells you right away when a rule matches.', 'কোনো নিয়ম মিললে Sora সাথে সাথে জানাবে।');
  String get addRule => _t('Add a rule', 'নিয়ম যোগ করুন');
  String get ruleTitle => _t('New email rule', 'নতুন ইমেইল নিয়ম');
  String get rulePh => _t('Always tell me about mail from…', 'এর কাছ থেকে মেইল এলে সবসময় জানাবে…');
  String unread(int n) => _t('$n unread', '${num(n)}টি অপঠিত');
  String get important => _t('Important', 'জরুরি');
  String get newRem => _t('New reminder', 'নতুন রিমাইন্ডার');
  String get remPh => _t('What should I remind you about?', 'কী মনে করিয়ে দেব?');
  String get pickTime => _t('Pick a time…', 'সময় বেছে নিন…');
  String get noneRepeat => _t('None', 'নেই');
  String get daily => _t('Daily', 'প্রতিদিন');
  String get weekly => _t('Weekly', 'প্রতি সপ্তাহে');
  String get scheduled => _t('Scheduled', 'নির্ধারিত');
  String get doneS => _t('Done', 'সম্পন্ন');
  String get cancelledS => _t('Cancelled', 'বাতিল');
  String get markDone => _t('Mark done', 'সম্পন্ন হিসেবে চিহ্নিত করুন');
  String get cancelRem => _t('Cancel reminder', 'রিমাইন্ডার বাতিল করুন');
  String get phoneNotifs => _t('Phone notifications', 'ফোনের নোটিফিকেশন');
  String get phoneNotifsEmpty => _t(
    'Messages that come on the phone show up here. Turn it on in the phone app: Settings → Phone notifications on the PC.',
    'ফোনে যে মেসেজ আসে তা এখানে দেখাবে। ফোনের অ্যাপে চালু করুন: সেটিংস → ফোনের নোটিফিকেশন PC-তে।',
  );
  String get mirrorNotifs => _t('Phone notifications on the PC', 'ফোনের নোটিফিকেশন PC-তে');
  String get mirrorNotifsHint => _t(
    'WhatsApp, Messenger, SMS… show on the PC, and Sora can read them out and reply.',
    'WhatsApp, Messenger, SMS… PC-তে দেখাবে, আর Sora সেগুলো পড়ে শোনাতে ও উত্তর দিতে পারবে।',
  );
  String get mirrorNotifsAccess => _t(
    'Allow Sora under Notification access first (tap the switch).',
    'আগে “নোটিফিকেশন অ্যাক্সেস”-এ Sora-কে অনুমতি দিন (সুইচে ট্যাপ করুন)।',
  );
  String get mirrorApps => _t('Which apps', 'কোন কোন অ্যাপ');
  String get mirrorAppsTitle => _t('Apps whose notifications go to the PC', 'যে অ্যাপের নোটিফিকেশন PC-তে যাবে');
  String get mirrorAppsNone => _t('None chosen', 'কোনোটিই বাছা হয়নি');
  String get phoneNotifsPanel => _t('Phone notifications in Details', 'Details-এ ফোনের নোটিফিকেশন');
  String get phoneNotifsPanelHint => _t('What came on the phone, beside the chat.', 'ফোনে কী এসেছে, চ্যাটের পাশে।');
  String get phoneNotifsToast => _t('Windows notifications for them', 'এগুলোর জন্য Windows নোটিফিকেশন');
  String get phoneNotifsToastHint => _t('Each one also pops up in the corner of the screen.', 'প্রতিটি স্ক্রিনের কোণেও ভেসে উঠবে।');
  String get replyNotif => _t('Reply from the phone', 'ফোন থেকে উত্তর দিন');
  String get sendWhatsapp => _t('Send on WhatsApp', 'WhatsApp-এ পাঠান');

  String get emptyRoutines => _t(
    'No routines yet. In the chat, try: “Every morning at 8, tell me my calendar and important emails.”',
    'এখনও কোনো রুটিন নেই। চ্যাটে বলে দেখুন: “প্রতিদিন সকাল ৮টায় আমার ক্যালেন্ডার আর জরুরি ইমেইল জানাবে।”',
  );
  String get routinesHint => _t(
    'Sora does these on its own. Ask in the chat to add or change one.',
    'এগুলো Sora নিজে থেকেই করে। নতুন রুটিন বা কোনো বদল চাইলে চ্যাটে বলুন।',
  );
  String routineNext(String when) => _t('Next: $when', 'পরের বার: $when');
  String routineLast(String when) => _t('Last: $when', 'শেষবার: $when');
  String get runNow => _t('Run now', 'এখনই চালান');
  String get runStarted => _t('Running… the result comes as a notification.', 'চলছে… ফলাফল নোটিফিকেশনে আসবে।');
  String get checkStarted => _t('Looking at the page… you hear only if it changed.', 'পেজটা দেখছি… বদলালে তবেই জানাব।');
  String get sayAloud => _t('Say results aloud', 'ফলাফল জোরে বলবে');
  String get notifOnly => _t('Notification only', 'শুধু নোটিফিকেশন');
  String get deleteRoutine => _t('Delete routine', 'রুটিন মুছুন');
  String get deleteRoutineQ => _t('Its past results go too. This can’t be undone.', 'আগের ফলাফলও মুছে যাবে। আর ফেরানো যাবে না।');
  String get routineOk => _t('Done', 'হয়েছে');
  String get routineFailed => _t('Failed', 'হয়নি');
  String get routineWaiting => _t('Needs approval', 'অনুমতি দরকার');
  String get routineMissed => _t('Missed', 'বাদ পড়েছে');
  String get routineUnchanged => _t('No change', 'বদলায়নি');
  String get routineOff => _t('Off', 'বন্ধ');
  String runsWithoutAsking(String what) => _t('Runs without asking: $what', 'অনুমতি ছাড়া করবে: $what');

  /// What starts a routine, from its trigger JSON (see backend services/routine_triggers.py).
  String routineWhen(Map trigger) {
    String clock(String at) {
      final hm = at.split(':');
      return DateFormat('h:mm a', code).format(DateTime(2024, 1, 1, int.tryParse(hm.first) ?? 0, int.tryParse(hm.last) ?? 0));
    }

    String device(Object? d) => d == 'pc' ? 'PC' : _t('phone', 'ফোন');
    switch (trigger['type']) {
      case 'time':
        const week = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
        final days = [for (final d in trigger['days'] as List? ?? const []) week.indexOf('$d')]..removeWhere((i) => i < 0);
        // 2024-01-01 was a Monday: the weekday names come from DateFormat in this language.
        final on = days.isEmpty
            ? _t('Every day', 'প্রতিদিন')
            : days.map((i) => DateFormat('EEE', code).format(DateTime(2024, 1, 1 + i))).join(', ');
        return '$on · ${clock(trigger['at'] as String? ?? '0:00')}';
      case 'interval':
        final m = trigger['minutes'] as int? ?? 0;
        if (m % 60 != 0) return _t('Every $m minutes', 'প্রতি ${num(m)} মিনিটে');
        return m == 60 ? _t('Every hour', 'প্রতি ঘণ্টায়') : _t('Every ${m ~/ 60} hours', 'প্রতি ${num(m ~/ 60)} ঘণ্টায়');
      case 'email':
        final from = trigger['sender'] as String?, subject = trigger['subject'] as String?;
        final important = trigger['important_only'] == true;
        if (isBn) {
          return '${from != null ? '$from থেকে ' : ''}${subject != null ? '“$subject” বিষয়ে ' : ''}${important ? 'জরুরি ' : ''}ইমেইল এলে';
        }
        return 'When ${important ? 'an important email' : 'an email'}${from != null ? ' from $from' : ''}'
            '${subject != null ? ' about “$subject”' : ''} arrives';
      case 'battery_below':
        final percent = trigger['percent'] ?? '';
        return _t('When the phone battery drops below $percent%', 'ফোনের চার্জ ${num(percent)}%-এর নিচে নামলে');
      case 'device_online':
        return _t('When the ${device(trigger['device'])} comes online', '${device(trigger['device'])} অনলাইনে এলে');
      case 'device_offline':
        return _t('When the ${device(trigger['device'])} goes offline', '${device(trigger['device'])} অফলাইন হলে');
      case 'pc_woke':
        return _t('When the PC wakes up', 'PC ঘুম থেকে জাগলে');
      case 'phone_notification':
        final app = trigger['app'] as String?, from = trigger['sender'] as String?;
        if (isBn) return '${from != null ? '$from-এর ' : ''}${app ?? 'ফোনে'} নোটিফিকেশন এলে';
        return 'When ${app != null ? 'a $app notification' : 'a phone notification'}${from != null ? ' from $from' : ''} arrives';
      case 'page_change':
        final url = trigger['url'] as String? ?? '';
        final host = Uri.tryParse(url)?.host ?? '';
        final site = host.isEmpty ? url : host.replaceFirst(RegExp(r'^www\.'), '');
        final part = trigger['contains'] as String? ?? trigger['selector'] as String?;
        if (isBn) return '${part != null ? '$site-এ “$part”' : site} বদলালে';
        return 'When ${part != null ? '“$part” on $site' : site} changes';
    }
    return '${trigger['type'] ?? ''}';
  }

  String get addMem => _t('Add memory', 'স্মৃতি যোগ করুন');
  String get editMem => _t('Edit memory', 'স্মৃতি এডিট করুন');
  String get memPh => _t('Something Sora should remember', 'Sora-র যা মনে রাখা উচিত');
  String get instrTitle => _t('How Sora should respond', 'Sora কীভাবে উত্তর দেবে');
  String get instrSheet => _t('Custom instructions', 'কাস্টম নির্দেশনা');
  String get instrPh => _t('Tell Sora how to talk to you', 'Sora আপনার সাথে কীভাবে কথা বলবে, লিখুন');
  String get instrEmpty => _t('No instructions yet. Tap Edit to tell Sora how to reply.', 'এখনও কোনো নির্দেশনা নেই। Sora কীভাবে উত্তর দেবে তা জানাতে এডিট-এ ট্যাপ করুন।');
  String tone(String t) => !isBn ? t : const {'Warm': 'উষ্ণ', 'Concise': 'সংক্ষিপ্ত', 'Formal': 'আনুষ্ঠানিক'}[t] ?? t;
  String category(String c) => switch (c) {
    'people' => _t('People', 'মানুষ'),
    'study' => _t('Study', 'পড়াশোনা'),
    'prefs' => _t('Preferences', 'পছন্দ'),
    _ => _t('Personal', 'ব্যক্তিগত'),
  };
  String get addNote => _t('Note', 'নোট');
  String get addUrl => _t('Link', 'লিংক');
  String get upload => _t('Upload', 'আপলোড');
  String get searchKnow => _t('Search notes and files', 'নোট ও ফাইল খুঁজুন');

  // People
  String get people => _t('People', 'মানুষজন');
  String get addPerson => _t('Add person', 'যোগ করুন');
  String get editPerson => _t('Edit person', 'এডিট করুন');
  String get searchPeople => _t('Search by name, relation or number', 'নাম, সম্পর্ক বা নম্বর দিয়ে খুঁজুন');
  String get emptyPeople => _t(
    'Add the people in your life — family, friends, your boss. Then "call Ammu" or "email my boss" just works.',
    'আপনার আপনজনদের যোগ করুন — পরিবার, বন্ধু, বস। তারপর “আম্মুকে কল দাও” বা “বসকে মেইল করো” বললেই হবে।',
  );
  String get personName => _t('Name', 'নাম');
  String get personNameHint => _t('Full name', 'পুরো নাম');
  String get relation => _t('Relation', 'সম্পর্ক');
  String get relationHint => _t('Boss, mother, friend, cousin…', 'বস, মা, বন্ধু, কাজিন…');
  String get phones => _t('Phone numbers', 'ফোন নম্বর');
  String get phonesHint => _t('01XXXXXXXXX — separate more with commas', '01XXXXXXXXX — একাধিক হলে কমা দিয়ে লিখুন');
  String get emails => _t('Emails', 'ইমেইল');
  String get emailsHint => _t('name@example.com — separate more with commas', 'name@example.com — একাধিক হলে কমা দিয়ে লিখুন');
  String get nicknames => _t('Nicknames', 'ডাকনাম');
  String get nicknamesHint => _t('What you call them: Ammu, আম্মু, Rahim bhai', 'যে নামে ডাকেন: Ammu, আম্মু, রহিম ভাই');
  String get birthday => _t('Birthday', 'জন্মদিন');
  String get pickDate => _t('Pick a date', 'তারিখ বেছে নিন');
  String get notes => _t('Notes', 'নোট');
  String get notesHint => _t('Anything else Sora should know about them', 'তাঁর সম্পর্কে Sora-র আর যা জানা দরকার');
  String get removePerson => _t('Remove from People', 'মুছে ফেলুন');
  String get nameNeeded => _t('Give a name first.', 'আগে একটা নাম দিন।');
  String removePersonQ(String name) =>
      _t('Remove $name from People? Sora will forget their numbers and details.', '$name-কে মুছে ফেলবেন? Sora তাঁর নম্বর ও তথ্য ভুলে যাবে।');
  String birthdayIn(int days) => days == 0
      ? _t('Birthday today 🎂', 'আজ জন্মদিন 🎂')
      : days == 1
      ? _t('Birthday tomorrow', 'কাল জন্মদিন')
      : _t('Birthday in $days days', '${num(days)} দিন পর জন্মদিন');
  String get uploadHint => _t('PDF, DOCX, TXT, MD or HTML', 'PDF, DOCX, TXT, MD বা HTML');
  String get chooseFile => _t('Choose a file', 'ফাইল বেছে নিন');
  String get notePh => _t('Write a note for Sora', 'Sora-র জন্য একটি নোট লিখুন');
  String get urlPh => _t('Paste a link', 'একটি লিংক দিন');
  String get adding => _t('Adding…', 'যোগ করছি…');
  String get added => _t('Added', 'যোগ হয়েছে');
  String source(String src) => switch (src) {
    'note' => _t('Note', 'নোট'),
    'url' => _t('Link', 'লিংক'),
    'drive' => 'Drive',
    _ => _t('Upload', 'আপলোড'),
  };
  String get connectAll => _t('Connect all', 'সব কানেক্ট করুন');
  String get connectB => _t('Connect', 'কানেক্ট');
  String get connectedL => _t('Connected', 'কানেক্টেড');
  String get reconnect => _t('Reconnect', 'আবার কানেক্ট');
  String get expiredAccess => _t('Access expired. Reconnect to keep using it.', 'অ্যাক্সেসের মেয়াদ শেষ। ব্যবহার চালিয়ে যেতে আবার কানেক্ট করুন।');
  String get partial => _t('Some permissions were unticked. Connect again to allow all.', 'কিছু অনুমতি বাদ দেওয়া হয়েছে। সব অনুমতি দিতে আবার কানেক্ট করুন।');
  String get disconnectG => _t('Disconnect Google', 'Google ডিসকানেক্ট করুন');
  String get waitingG => _t('Waiting for Google…', 'Google-এর অপেক্ষায়…');
  String get disconnectQ => _t(
    'Sora will lose access to all eight Google services. You can connect them again later.',
    'আটটি Google সার্ভিসেই Sora-র অ্যাক্সেস চলে যাবে। পরে আবার কানেক্ট করতে পারবেন।',
  );
  String isConnected(int n) => _t('$n connected', '${num(n)}টি কানেক্টেড');
  String get thisDevice => _t('This device', 'এই ডিভাইস');
  String get activeNow => _t('Active now', 'এখন সক্রিয়');
  String lastSeen(String when) => _t('Last seen $when', 'সর্বশেষ $when');
  String get onlineS => _t('Online', 'অনলাইন');
  String deviceKind(String kind) => switch (kind) {
    'android' => 'Android',
    'windows' => _t('Windows app', 'Windows অ্যাপ'),
    'pc_agent' => _t('PC agent', 'PC এজেন্ট'),
    _ => kind,
  };
  String get lock => _t('Lock', 'লক');
  String get screenshot => _t('Screenshot', 'স্ক্রিনশট');
  String get volume => _t('Volume', 'ভলিউম');
  String get sleep => _t('Sleep', 'স্লিপ');
  String get volumeUp => _t('Volume up', 'ভলিউম বাড়ান');
  String get volumeDown => _t('Volume down', 'ভলিউম কমান');
  String get mute => _t('Mute', 'মিউট');
  String sleepQ(String pc) => _t("Put $pc to sleep? Anything unsaved stays open.", '$pc স্লিপে পাঠাবেন? সেভ না করা কাজ খোলাই থাকবে।');
  String get pcLocked => _t('PC locked', 'PC লক হয়েছে');
  String get signOutDev => _t('Sign out', 'সাইন আউট');
  String get revokeQ => _t('This device will need the PIN to sign in again.', 'আবার সাইন ইন করতে এই ডিভাইসে PIN লাগবে।');
  String get pcOffline => _t('Your PC is offline.', 'আপনার PC অফলাইনে আছে।');

  /// Short relative time for list rows: "now", "5 min", "2 h", "Yesterday", "Mon", "Oct 3".
  String ago(DateTime? t) {
    if (t == null) return '';
    final now = DateTime.now();
    final d = now.difference(t);
    if (d.inMinutes < 1) return _t('now', 'এখন');
    if (d.inMinutes < 60) return _t('${d.inMinutes} min', '${num(d.inMinutes)} মিনিট');
    final day = DateTime(t.year, t.month, t.day), today = DateTime(now.year, now.month, now.day);
    final days = today.difference(day).inDays;
    if (days == 0) return _t('${d.inHours} h', '${num(d.inHours)} ঘণ্টা');
    if (days == 1) return _t('Yesterday', 'গতকাল');
    if (days < 7) return DateFormat('EEE', code).format(t);
    return DateFormat('MMM d', code).format(t);
  }

  /// "Today · 9:00 pm", "Tomorrow · 8:00 am", "Fri · 3:30 pm", "Oct 14 · 10:00 am".
  String when(DateTime t) {
    final now = DateTime.now();
    final days = DateTime(t.year, t.month, t.day).difference(DateTime(now.year, now.month, now.day)).inDays;
    final day = switch (days) {
      0 => _t('Today', 'আজ'),
      1 => _t('Tomorrow', 'আগামীকাল'),
      -1 => _t('Yesterday', 'গতকাল'),
      _ when days > 1 && days < 7 => DateFormat('EEE', code).format(t),
      _ => DateFormat('MMM d', code).format(t),
    };
    return '$day · ${DateFormat('h:mm a', code).format(t)}';
  }

  // ------------------------------------------------------------------ settings
  String get appearance => _t('Appearance', 'অ্যাপিয়ারেন্স');
  String get theme => _t('Theme', 'থিম');
  String get themeAuto => _t('Auto', 'অটো');
  String get themeLight => _t('Light', 'লাইট');
  String get themeDark => _t('Dark', 'ডার্ক');
  String get appLang => _t('App language', 'অ্যাপের ভাষা');
  String get voiceSec => _t('Voice', 'ভয়েস');
  String get voiceLang => _t('Default voice language', 'ডিফল্ট ভয়েস ভাষা');
  String get soraVoice => _t("Sora's voice", 'Sora-র কণ্ঠ');
  String get speed => _t('Speed', 'গতি');
  String get play => _t('Play', 'শুনুন');
  String get handsFree => _t('“Hey Sora” — hands-free', '“হেই সোরা” — হাত না লাগিয়ে');
  String get handsFreeHint => _t(
    'Listens for its name in the background, even with the screen locked, and keeps talking until you say thanks. Shows a notification; uses some battery. Needs the server to be reachable.',
    'স্ক্রিন লক থাকলেও নাম শুনলে সাড়া দেবে, “ধন্যবাদ” না বলা পর্যন্ত কথা চালিয়ে যাবে। একটা নোটিফিকেশন থাকবে, কিছুটা ব্যাটারি খরচ হবে। সার্ভারের সাথে সংযোগ লাগবে।',
  );
  String get phoneControl => _t('Screenshots, lock & opening apps', 'স্ক্রিনশট, লক ও অ্যাপ খোলা');
  String get phoneControlHint => _t(
    'Turn on Sora in Accessibility so it can take screenshots, lock the phone and open apps while you talk to it hands-free. Sora does not read your screen.',
    'অ্যাক্সেসিবিলিটিতে সোরা চালু করলে হাত না লাগিয়ে কথা বলার সময়ও স্ক্রিনশট নিতে, ফোন লক করতে আর অ্যাপ খুলতে পারবে। সোরা আপনার স্ক্রিন পড়ে না।',
  );
  String get turnOn => _t('Turn on', 'চালু করুন');
  String get isOn => _t('On', 'চালু');
  String get handsFreeDenied => _t('Sora needs the microphone for this.', 'এর জন্য সোরার মাইক্রোফোন লাগবে।');
  String get teachVoice => _t('Teach Sora your voice', 'সোরাকে আপনার কণ্ঠ শেখান');
  String get teachVoiceHint => _t(
    'Record yourself saying “Hey Sora” and a few other things, so Sora can learn to hear its name right on this device. About 5 minutes; do it on each device you use.',
    'নিজের কণ্ঠে “হেই সোরা” আর আরও কিছু কথা রেকর্ড করুন, যাতে সোরা এই ডিভাইসেই নিজের নাম চিনতে শেখে। প্রায় ৫ মিনিট লাগবে; যে ডিভাইসে ব্যবহার করেন, প্রতিটাতে একবার করে।',
  );
  String get teachStart => _t('Start', 'শুরু করুন');
  String get teachSay => _t('Say', 'বলুন');
  String get teachTap => _t('Tap the mic, then say it', 'মাইকে ট্যাপ করে বলুন');
  String get teachSaved => _t('Saved', 'সেভ হয়েছে');
  String get teachNothing => _t('Didn’t hear anything. Try again.', 'কিছু শুনতে পাইনি। আবার চেষ্টা করুন।');
  String get teachUndo => _t('Undo last', 'শেষটা মুছুন');
  String get teachOtherPhase => _t(
    'Now some things that are not “Hey Sora”, so Sora learns the difference.',
    'এবার কিছু কথা যেগুলো “হেই সোরা” নয়, যাতে সোরা পার্থক্যটা শেখে।',
  );
  String get teachAllDone =>
      _t('All done on this device. Thank you! More recordings still help.', 'এই ডিভাইসে সব হয়ে গেছে, ধন্যবাদ! আরও রেকর্ড করলে আরও ভালো হবে।');
  String teachCount(int p, int pAll, int n, int nAll) => _t(
    'This device: ${num(p)}/${num(pAll)} “Hey Sora” · ${num(n)}/${num(nAll)} other',
    'এই ডিভাইস: “হেই সোরা” ${num(p)}/${num(pAll)} · অন্য কথা ${num(n)}/${num(nAll)}',
  );
  String get clipboard => _t('Clipboard', 'ক্লিপবোর্ড');
  String get clipboardEmpty => _t(
    'Copy something on your phone or this PC, or take a screenshot on the phone: it shows up here and is ready to paste.',
    'ফোনে বা এই পিসিতে কিছু কপি করুন, বা ফোনে স্ক্রিনশট নিন: এখানে চলে আসবে, পেস্ট করার জন্য তৈরি।',
  );
  String get clipboardOff => _t('Clipboard sync is off (Settings).', 'ক্লিপবোর্ড সিঙ্ক বন্ধ আছে (সেটিংস)।');
  String get copiedToPc => _t('Copied — press Ctrl+V to paste', 'কপি হয়েছে — পেস্ট করতে Ctrl+V চাপুন');
  String get fromPhone => _t('Phone', 'ফোন');
  String get fromPc => _t('PC', 'পিসি');
  String get syncClipboard => _t('Share the clipboard with the PC', 'পিসির সাথে ক্লিপবোর্ড শেয়ার');
  String get syncClipboardHint => _t(
    'What you copy on the phone (tap Copy) and new screenshots go to the PC’s clipboard; what you copy on the PC comes to the phone. Needs Sora on in Accessibility. Passwords from password managers are left out.',
    'ফোনে যা কপি করবেন (Copy চাপলে) আর নতুন স্ক্রিনশট পিসির ক্লিপবোর্ডে যাবে; পিসিতে যা কপি করবেন তা ফোনে আসবে। অ্যাক্সেসিবিলিটিতে সোরা চালু থাকতে হবে। পাসওয়ার্ড ম্যানেজারের পাসওয়ার্ড পাঠানো হয় না।',
  );
  String get syncClipboardPc => _t('Share the clipboard with the phone', 'ফোনের সাথে ক্লিপবোর্ড শেয়ার');
  String get syncClipboardPcHint => _t(
    'What you copy here goes to the phone, and what you copy on the phone (or a screenshot) lands here, ready for Ctrl+V.',
    'এখানে যা কপি করবেন তা ফোনে যাবে, আর ফোনে যা কপি করবেন (বা স্ক্রিনশট) এখানে চলে আসবে, Ctrl+V দিলেই পেস্ট।',
  );
  String get phoneOff => _t('Your phone isn’t connected. Open Sora on it, or turn on “Hey Sora”.', 'ফোন সংযুক্ত নেই। ফোনে সোরা খুলুন, বা “হেই সোরা” চালু করুন।');
  String get ring => _t('Ring', 'বাজাও');
  String get ringing => _t('Ringing at full volume…', 'পুরো আওয়াজে বাজছে…');
  String get stopRing => _t('Stop ringing', 'বাজানো থামাও');
  String get charging => _t('charging', 'চার্জ হচ্ছে');
  String storageFree(Object free, Object total) => _t('$free of $total GB free', '$total GB-এর মধ্যে $free GB খালি');
  String get ringerSilent => _t('Silent', 'সাইলেন্ট');
  String get ringerVibrate => _t('Vibrate', 'ভাইব্রেট');
  String get ringerNormal => _t('Sound on', 'সাউন্ড চালু');
  String get crop => _t('Crop', 'ক্রপ');
  String get cropHint => _t('Drag over the part to keep', 'যে অংশ রাখবেন তার উপর টেনে দিন');
  String get applyCrop => _t('Crop to selection', 'বাছাই করা অংশ রাখুন');
  String savedTo(String path) => _t('Saved to $path', '$path-এ সেভ হয়েছে');
  String get deleteChat => _t('Delete this chat?', 'এই চ্যাট মুছবেন?');
  String get deleteChatQ => _t('The conversation and its messages are deleted. This can’t be undone.', 'কথোপকথন আর এর সব মেসেজ মুছে যাবে। আর ফেরানো যাবে না।');
  String get clear => _t('Clear', 'মুছুন');
  String get clearClipboardHint => _t('Empty this list (what is on the clipboards stays)', 'তালিকা খালি করুন (ক্লিপবোর্ডে যা আছে তা থাকবে)');
  String get copiedPhone => _t('Copied — paste it in any app', 'কপি হয়েছে — যেকোনো অ্যাপে পেস্ট করুন');
  String get phoneScreenshot => _t('Phone screenshot', 'ফোনের স্ক্রিনশট');
  String get thisPc => _t('This PC', 'এই পিসি');
  String get startWithWindows => _t('Start Sora with Windows', 'Windows চালু হলে Sora চালু হবে');
  String get startWithWindowsHint => _t(
    'Starts the Sora server and the PC agent when you sign in to Windows, without any windows.',
    'Windows-এ সাইন ইন করলেই Sora সার্ভার আর PC এজেন্ট নিজে থেকে চালু হবে, কোনো উইন্ডো খুলবে না।',
  );
  String get pcHeySora => _t('“Hey Sora” on the PC', 'পিসিতে “হেই সোরা”');
  String get pcHeySoraHint => _t(
    'Listens for its name through the PC’s microphone. Turn it off to free the microphone.',
    'পিসির মাইক্রোফোনে নাম শুনলে সাড়া দেবে। বন্ধ করলে মাইক্রোফোন ছেড়ে দেবে।',
  );
  String get pcLink => _t('Stay connected to the PC', 'PC-র সাথে যুক্ত থাকুন');
  String get pcLinkOn => _t(
    'Connected now. Like Phone Link: it stays connected with the app closed, and connects as soon as Sora starts on the PC.',
    'এখন যুক্ত। Phone Link-এর মতো: অ্যাপ বন্ধ থাকলেও যুক্ত থাকে, PC-তে Sora চালু হলেই যুক্ত হয়ে যায়।',
  );
  String get pcLinkWaiting => _t(
    'Waiting for Sora on the PC. It connects by itself as soon as Sora starts there.',
    'PC-র Sora-র অপেক্ষায়। ওখানে Sora চালু হলেই নিজে থেকে যুক্ত হবে।',
  );
  String get pcLinkOff => _t(
    'Disconnected: the PC can’t reach this phone and the clipboard isn’t shared.',
    'বিচ্ছিন্ন: PC এই ফোনে কিছু করতে পারবে না, ক্লিপবোর্ডও শেয়ার হবে না।',
  );
  String get pcLinkNotify => _t('Connection notification', 'সংযোগের নোটিফিকেশন');
  String get pcLinkNotifyHint => _t(
    '“Connected to the PC” in the notification shade, with Disconnect.',
    'নোটিফিকেশনে “PC-র সাথে যুক্ত” দেখাবে, বিচ্ছিন্ন করার বোতামসহ।',
  );
  String get closeToTray => _t('Keep running when closed', 'বন্ধ করলেও চালু থাকুক');
  String get closeToTrayHint => _t(
    'Closing the window leaves Sora by the clock (Show hidden icons); click it there to open Sora again.',
    'উইন্ডো বন্ধ করলে Sora ঘড়ির পাশে (Show hidden icons) থেকে যাবে; ওখানে ক্লিক করলে আবার খুলবে।',
  );
  String get turnSoraOff => _t('Turn Sora off', 'Sora বন্ধ করুন');
  String get turnSoraOffHint => _t(
    'Stops the server, the PC agent and Hey Sora on this PC. Opening this app starts them again.',
    'এই PC-তে সার্ভার, PC এজেন্ট আর Hey Sora বন্ধ হবে। এই অ্যাপ আবার খুললে সব চালু হবে।',
  );
  String get turnSoraOffQ => _t(
    'The server, the PC agent and Hey Sora stop and this app closes. Your phone can’t reach Sora until you open this app again.',
    'সার্ভার, PC এজেন্ট আর Hey Sora বন্ধ হবে, এই অ্যাপও বন্ধ হবে। অ্যাপ আবার না খোলা পর্যন্ত ফোন থেকে Sora পাওয়া যাবে না।',
  );
  String get turnOff => _t('Turn off', 'বন্ধ করুন');
  String get pcAgentOff => _t('The PC agent isn’t running.', 'PC এজেন্ট চলছে না।');
  String get couldntChange => _t('Couldn’t change that. Try again.', 'বদলানো গেল না। আবার চেষ্টা করুন।');
  String get findingServer => _t('Looking for Sora on your Wi-Fi…', 'Wi-Fi-তে Sora খুঁজছি…');
  String get readAloudNotif => _t('Read important notifications aloud', 'জরুরি নোটিফিকেশন পড়ে শোনান');
  String get connection => _t('Connection', 'কানেকশন');
  String get status => _t('Status', 'অবস্থা');
  String get connectedS => _t('Connected', 'সংযুক্ত');
  String get about => _t('About', 'সম্পর্কে');
  String get version => _t('App version', 'অ্যাপ ভার্সন');
  String get serverVer => _t('Server version', 'সার্ভার ভার্সন');
  String tools(int n) => _t('$n tools', '${num(n)}টি টুল');
  String get signOut => _t('Sign out', 'সাইন আউট');

  // ------------------------------------------------------------------ connections (old screen)
  String get connectionsSub => 'Gmail, Calendar, Drive, Sheets…';
  String get connectionsHint => _t(
    'Tap Connect next to a service. Google will ask for that service only.',
    'সার্ভিসের পাশে কানেক্ট-এ ট্যাপ করুন। Google শুধু সেই সার্ভিসের অনুমতি চাইবে।',
  );
  String get googleNotConfigured => _t(
    'Google isn’t set up on the server yet. See docs/google-setup.md.',
    'সার্ভারে এখনো Google সেটআপ করা হয়নি। docs/google-setup.bn.md দেখুন।',
  );
  String get browserFailed => _t('Couldn’t open the browser.', 'ব্রাউজার খোলা যায়নি।');
  String googleAccount(String email) => 'Google · $email';
  String get newConversation => newChat;

  /// Bangla names for Google services; empty for English (the server's labels are used).
  Map<String, String> get serviceLabels => !isBn
      ? const {}
      : const {
          'gmail': 'Gmail',
          'calendar': 'Google ক্যালেন্ডার',
          'drive': 'Google ড্রাইভ',
          'docs': 'Google ডক্স',
          'sheets': 'Google শিটস',
          'slides': 'Google স্লাইডস',
          'tasks': 'Google টাস্কস',
          'contacts': 'Google কন্টাক্টস',
        };

  Map<String, String> get serviceDescriptions => !isBn
      ? const {}
      : const {
          'gmail': 'ইমেইল পড়া, খোঁজা, পাঠানো ও উত্তর দেওয়া; জরুরি মেইলের নোটিফিকেশন',
          'calendar': 'ইভেন্ট দেখা ও তৈরি করা',
          'drive': 'যেকোনো ফাইল খোঁজা ও পড়া (ডক্স, শিটস, স্লাইডসসহ)',
          'docs': 'ডকুমেন্ট তৈরি ও লেখা',
          'sheets': 'স্প্রেডশিট পড়া ও লেখা',
          'slides': 'প্রেজেন্টেশন তৈরি',
          'tasks': 'টু-ডু লিস্ট',
          'contacts': 'নাম দিয়ে ইমেইল ও ফোন নম্বর খোঁজা (শুধু পড়া)',
        };
}

/// Puts the chosen language's [S] into the tree (wrapped around the whole app).
class SoraStrings extends InheritedWidget {
  SoraStrings({super.key, required String code, required super.child}) : strings = S.forCode(code);

  final S strings;

  @override
  bool updateShouldNotify(SoraStrings old) => old.strings.code != strings.code;
}
