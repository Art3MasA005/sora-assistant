package com.yeasir.sora_phone;

import android.Manifest;
import android.app.ActivityManager;
import android.content.ActivityNotFoundException;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.database.Cursor;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.media.AudioManager;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.AlarmClock;
import android.provider.ContactsContract;
import android.provider.MediaStore;
import android.provider.Settings;
import android.telecom.PhoneAccountHandle;
import android.telecom.TelecomManager;
import android.telephony.SmsManager;
import android.telephony.SubscriptionInfo;
import android.telephony.SubscriptionManager;
import android.telephony.TelephonyManager;
import android.text.TextUtils;
import android.view.KeyEvent;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import io.flutter.embedding.engine.plugins.FlutterPlugin;
import io.flutter.plugin.common.MethodCall;
import io.flutter.plugin.common.MethodChannel;

/**
 * Phone actions for Sora, available in the app and in the background "Hey Sora" service alike
 * (a plugin is registered in every Flutter engine). One method, "run", takes an action and params;
 * it answers with a short result or fails with a message the assistant can repeat.
 */
public class SoraPhonePlugin implements FlutterPlugin, MethodChannel.MethodCallHandler {
    private MethodChannel channel;
    private Context context;
    private final Handler main = new Handler(Looper.getMainLooper());

    public SoraPhonePlugin() {
    }

    /** For {@link SoraLink}: runs actions with no Flutter engine (the app closed). */
    SoraPhonePlugin(Context context) {
        this.context = context;
    }

    void runFor(String action, Map<String, Object> params, MethodChannel.Result result) {
        try {
            run(action, params, result);
        } catch (Exception e) {
            result.error("failed", e.getMessage() == null ? e.toString() : e.getMessage(), null);
        }
    }

    @Override
    public void onAttachedToEngine(FlutterPluginBinding binding) {
        context = binding.getApplicationContext();
        channel = new MethodChannel(binding.getBinaryMessenger(), "sora_phone");
        channel.setMethodCallHandler(this);
        SoraClip.attach(channel);
    }

    @Override
    public void onDetachedFromEngine(FlutterPluginBinding binding) {
        channel.setMethodCallHandler(null);
        SoraClip.detach(channel);
    }

    @Override
    public void onMethodCall(MethodCall call, MethodChannel.Result result) {
        try {
            switch (call.method) {
                case "accessibilityEnabled":
                    result.success(SoraAccessibilityService.instance != null);
                    return;
                case "openAccessibilitySettings":
                    start(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS));
                    result.success(true);
                    return;
                case "run":
                    run(call.argument("action"), call.argument("params"), result);
                    return;
                case "link":
                    SoraLink.configure(context, call.argument("server"), call.argument("token"));
                    if (call.argument("bangla") != null) SoraLink.setBangla(context, Boolean.TRUE.equals(call.argument("bangla")));
                    result.success(true);
                    return;
                case "linkSettings": {
                    // read, or change what is given: {connected: not Disconnected, notify: the notification}
                    Boolean connected = call.argument("connected"), notify = call.argument("notify");
                    if (notify != null) LinkNotification.setEnabled(context, notify);
                    if (connected != null) SoraLink.setPaused(context, !connected);
                    Map<String, Object> state = new HashMap<>();
                    state.put("connected", !SoraLink.paused(context));
                    state.put("notify", LinkNotification.enabled(context));
                    state.put("online", SoraLink.online());
                    result.success(state);
                    return;
                }
                case "linkActive":
                    result.success(SoraLink.active());
                    return;
                case "edgeGlow": // the hands-free conversation's glow round the screen: {state, level}
                    Number level = call.argument("level");
                    result.success(EdgeGlow.set(call.argument("state"), level == null ? 0 : level.doubleValue()));
                    return;
                case "notificationMirror": // read, or change what is given: {enabled, allowed: [packages]}
                    result.success(SoraNotificationListener.configure(context, call.argument("enabled"), call.argument("allowed")));
                    return;
                case "openNotificationAccess":
                    openNotificationAccess();
                    result.success(true);
                    return;
                default:
                    result.notImplemented();
            }
        } catch (Exception e) {
            result.error("failed", e.getMessage() == null ? e.toString() : e.getMessage(), null);
        }
    }

    private void run(String action, Map<String, Object> p, MethodChannel.Result result) throws Exception {
        String target = p == null ? null : (String) p.get("target");
        switch (action) {
            case "set_clipboard": {
                Object text = p == null ? null : p.get("text");
                if (!(text instanceof String)) throw new IllegalArgumentException("no text to copy");
                SoraClip.set(context, (String) text);
                result.success("copied to the phone's clipboard");
                return;
            }
            case "clipboard_sync": {
                SoraClip.on = p != null && Boolean.TRUE.equals(p.get("on"));
                result.success(SoraClip.on ? "on" : "off");
                return;
            }
            case "open_app": {
                ResolveInfo app = findApp(target);
                if (app == null) throw new IllegalArgumentException("no app called \"" + target + "\" on this phone");
                Intent launch = context.getPackageManager().getLaunchIntentForPackage(app.activityInfo.packageName);
                if (launch == null) throw new IllegalStateException("that app can't be opened");
                start(launch);
                result.success("opened " + label(app));
                return;
            }
            case "close_app": {
                ResolveInfo app = findApp(target);
                if (app == null) throw new IllegalArgumentException("no app called \"" + target + "\" on this phone");
                String pkg = app.activityInfo.packageName;
                SoraAccessibilityService svc = SoraAccessibilityService.instance;
                if (svc != null && pkg.equals(SoraAccessibilityService.foregroundPackage)) svc.home();
                ActivityManager am = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
                // Give it a moment to leave the screen, then stop it in the background.
                main.postDelayed(() -> am.killBackgroundProcesses(pkg), 600);
                result.success("closed " + label(app));
                return;
            }
            case "open_url": {
                if (TextUtils.isEmpty(target)) throw new IllegalArgumentException("which link?");
                String url = target.matches("(?i)^[a-z][a-z0-9+.-]*:.*") ? target : "https://" + target;
                start(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                result.success("opened " + url);
                return;
            }
            case "media": {
                int key;
                String which = target == null ? "play_pause" : target;
                switch (which) {
                    case "next": key = KeyEvent.KEYCODE_MEDIA_NEXT; break;
                    case "previous": key = KeyEvent.KEYCODE_MEDIA_PREVIOUS; break;
                    case "stop": key = KeyEvent.KEYCODE_MEDIA_STOP; break;
                    default: key = KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE;
                }
                AudioManager audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
                long now = SystemClock.uptimeMillis();
                audio.dispatchMediaKeyEvent(new KeyEvent(now, now, KeyEvent.ACTION_DOWN, key, 0));
                audio.dispatchMediaKeyEvent(new KeyEvent(now, now, KeyEvent.ACTION_UP, key, 0));
                result.success("media " + which);
                return;
            }
            case "volume": {
                AudioManager audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
                String dir = target == null ? "up" : target;
                if (dir.equals("mute")) {
                    audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_TOGGLE_MUTE, AudioManager.FLAG_SHOW_UI);
                } else {
                    int steps = Math.max(1, Math.min(15, intParam(p, "seconds", 2)));
                    int adjust = dir.equals("down") ? AudioManager.ADJUST_LOWER : AudioManager.ADJUST_RAISE;
                    for (int i = 0; i < steps; i++) {
                        audio.adjustStreamVolume(AudioManager.STREAM_MUSIC, adjust, i == steps - 1 ? AudioManager.FLAG_SHOW_UI : 0);
                    }
                }
                result.success("volume " + dir);
                return;
            }
            case "flashlight": {
                CameraManager cams = (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
                boolean on = !Boolean.FALSE.equals(p == null ? null : p.get("on"));
                for (String id : cams.getCameraIdList()) {
                    Boolean flash = cams.getCameraCharacteristics(id).get(CameraCharacteristics.FLASH_INFO_AVAILABLE);
                    if (Boolean.TRUE.equals(flash)) {
                        cams.setTorchMode(id, on);
                        result.success(on ? "torch on" : "torch off");
                        return;
                    }
                }
                throw new IllegalStateException("this phone has no torch");
            }
            case "set_alarm": {
                String time = p == null ? null : (String) p.get("time");
                if (time == null || !time.matches("\\d{1,2}:\\d{2}")) throw new IllegalArgumentException("alarm time must be HH:MM");
                String[] hm = time.split(":");
                Intent i = new Intent(AlarmClock.ACTION_SET_ALARM)
                        .putExtra(AlarmClock.EXTRA_HOUR, Integer.parseInt(hm[0]))
                        .putExtra(AlarmClock.EXTRA_MINUTES, Integer.parseInt(hm[1]))
                        .putExtra(AlarmClock.EXTRA_SKIP_UI, true);
                String label = (String) p.get("text");
                if (label != null) i.putExtra(AlarmClock.EXTRA_MESSAGE, label);
                start(i);
                result.success("alarm " + time);
                return;
            }
            case "cancel_alarm": {
                // Android has no way to delete an alarm; the Clock app turns off the one asked for
                // (time=HH:MM, or text "all" for every alarm, else the next one) or stops one ringing.
                if (android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.M) {
                    throw new IllegalStateException("turning alarms off needs Android 6 or newer");
                }
                String time = p == null ? null : (String) p.get("time");
                String which = p == null ? null : (String) p.get("text");
                Intent i = new Intent(AlarmClock.ACTION_DISMISS_ALARM);
                if (time != null && time.matches("\\d{1,2}:\\d{2}")) {
                    String[] hm = time.split(":");
                    i.putExtra(AlarmClock.EXTRA_ALARM_SEARCH_MODE, AlarmClock.ALARM_SEARCH_MODE_TIME)
                            .putExtra(AlarmClock.EXTRA_HOUR, Integer.parseInt(hm[0]))
                            .putExtra(AlarmClock.EXTRA_MINUTES, Integer.parseInt(hm[1]));
                } else if (which != null && which.trim().equalsIgnoreCase("all")) {
                    i.putExtra(AlarmClock.EXTRA_ALARM_SEARCH_MODE, AlarmClock.ALARM_SEARCH_MODE_ALL);
                } else {
                    i.putExtra(AlarmClock.EXTRA_ALARM_SEARCH_MODE, AlarmClock.ALARM_SEARCH_MODE_NEXT);
                }
                start(i);
                result.success(time != null ? "turning off the " + time + " alarm" : "turning off the alarm");
                return;
            }
            case "cancel_timer": {
                if (android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.P) {
                    throw new IllegalStateException("stopping timers needs Android 9 or newer");
                }
                start(new Intent(AlarmClock.ACTION_DISMISS_TIMER));
                result.success("stopping the timer");
                return;
            }
            case "set_timer": {
                int seconds = intParam(p, "seconds", 0);
                if (seconds <= 0) throw new IllegalArgumentException("how long?");
                Intent i = new Intent(AlarmClock.ACTION_SET_TIMER)
                        .putExtra(AlarmClock.EXTRA_LENGTH, seconds)
                        .putExtra(AlarmClock.EXTRA_SKIP_UI, true);
                String label = p == null ? null : (String) p.get("text");
                if (label != null) i.putExtra(AlarmClock.EXTRA_MESSAGE, label);
                start(i);
                result.success("timer " + seconds + "s");
                return;
            }
            case "call": {
                if (TextUtils.isEmpty(target)) throw new IllegalArgumentException("call whom?");
                String[] who = numberFor(target, p);
                Uri tel = Uri.parse("tel:" + Uri.encode(who[1]));
                SubscriptionInfo sub = sim(p == null ? null : p.get("sim"));
                if (sub != null && granted(Manifest.permission.CALL_PHONE)) {
                    // From the SIM the owner named, straight away.
                    PhoneAccountHandle account = account(sub);
                    android.os.Bundle extras = new android.os.Bundle();
                    if (account != null) extras.putParcelable(TelecomManager.EXTRA_PHONE_ACCOUNT_HANDLE, account);
                    context.getSystemService(TelecomManager.class).placeCall(tel, extras);
                    result.success("calling " + who[0] + " (" + who[1] + ") from " + simName(sub));
                    return;
                }
                // Calls straight away when allowed; otherwise the dialer opens with the number ready.
                if (granted(Manifest.permission.CALL_PHONE)) {
                    start(new Intent(Intent.ACTION_CALL, tel));
                    result.success("calling " + who[0] + " (" + who[1] + ")");
                } else {
                    start(new Intent(Intent.ACTION_DIAL, tel));
                    result.success("dialer opened for " + who[0] + " (" + who[1] + ")");
                }
                return;
            }
            case "send_sms": {
                String[] who = TextUtils.isEmpty(target) ? new String[]{"", ""} : numberFor(target, p);
                String text = p == null || p.get("text") == null ? "" : String.valueOf(p.get("text"));
                SubscriptionInfo sub = sim(p == null ? null : p.get("sim"));
                if (!who[1].isEmpty() && !text.isEmpty() && granted(Manifest.permission.SEND_SMS)) {
                    // Sent right away (Sora already asked the owner), from the SIM they named or the default.
                    SmsManager sms;
                    if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.S) {
                        sms = context.getSystemService(SmsManager.class);
                        if (sub != null) sms = sms.createForSubscriptionId(sub.getSubscriptionId());
                    } else {
                        sms = sub != null ? SmsManager.getSmsManagerForSubscriptionId(sub.getSubscriptionId()) : SmsManager.getDefault();
                    }
                    sms.sendMultipartTextMessage(who[1], null, sms.divideMessage(text), null, null);
                    result.success("sent to " + who[0] + " (" + who[1] + ")" + (sub != null ? " from " + simName(sub) : ""));
                    return;
                }
                Intent i = new Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:" + Uri.encode(who[1])));
                i.putExtra("sms_body", text);
                start(i);
                result.success("message ready to send");
                return;
            }
            case "set_clipboard_image": {
                Object b64 = p == null ? null : p.get("png_base64");
                if (!(b64 instanceof String)) throw new IllegalArgumentException("no image");
                SoraClip.setImage(context, android.util.Base64.decode((String) b64, android.util.Base64.DEFAULT));
                result.success("image copied to the phone's clipboard");
                return;
            }
            case "save_image": {
                // A PNG into the gallery (Pictures/Sora). Not named Sora_…: that is how the phone's own
                // screenshots look, which clipboard sync would then send to the PC.
                Object b64 = p == null ? null : p.get("png_base64");
                if (!(b64 instanceof String)) throw new IllegalArgumentException("no image");
                String name = "Sora-" + new java.text.SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(new java.util.Date()) + ".png";
                android.content.ContentValues values = new android.content.ContentValues();
                values.put(MediaStore.Images.Media.DISPLAY_NAME, name);
                values.put(MediaStore.Images.Media.MIME_TYPE, "image/png");
                if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q) {
                    values.put(MediaStore.Images.Media.RELATIVE_PATH, android.os.Environment.DIRECTORY_PICTURES + "/Sora");
                }
                Uri uri = context.getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
                if (uri == null) throw new IllegalStateException("could not save the picture");
                try (java.io.OutputStream out = context.getContentResolver().openOutputStream(uri)) {
                    if (out == null) throw new IllegalStateException("could not save the picture");
                    out.write(android.util.Base64.decode((String) b64, android.util.Base64.DEFAULT));
                }
                result.success("Pictures/Sora/" + name);
                return;
            }
            case "find_contact": {
                String[] who = numberFor(target, p);
                result.success(who[0] + ": " + who[1]);
                return;
            }
            case "navigate": {
                if (TextUtils.isEmpty(target)) throw new IllegalArgumentException("where to?");
                start(new Intent(Intent.ACTION_VIEW, Uri.parse("google.navigation:q=" + Uri.encode(target))));
                result.success("navigating to " + target);
                return;
            }
            case "play_music": {
                Intent i = new Intent(MediaStore.INTENT_ACTION_MEDIA_PLAY_FROM_SEARCH)
                        .putExtra(SearchManagerQuery.KEY, target == null ? "" : target);
                try {
                    start(i);
                } catch (ActivityNotFoundException e) {
                    start(new Intent(Intent.ACTION_VIEW, Uri.parse("https://music.youtube.com/search?q=" + Uri.encode(target))));
                }
                result.success("playing " + target);
                return;
            }
            case "open_settings": {
                String which = target == null ? "" : target.toLowerCase(Locale.ROOT);
                String act = Settings.ACTION_SETTINGS;
                if (which.contains("wifi") || which.contains("wi-fi")) act = Settings.ACTION_WIFI_SETTINGS;
                else if (which.contains("bluetooth")) act = Settings.ACTION_BLUETOOTH_SETTINGS;
                else if (which.contains("display") || which.contains("bright")) act = Settings.ACTION_DISPLAY_SETTINGS;
                else if (which.contains("sound") || which.contains("volume")) act = Settings.ACTION_SOUND_SETTINGS;
                else if (which.contains("battery")) act = Intent.ACTION_POWER_USAGE_SUMMARY;
                else if (which.contains("location")) act = Settings.ACTION_LOCATION_SOURCE_SETTINGS;
                else if (which.contains("data") || which.contains("mobile")) act = Settings.ACTION_DATA_ROAMING_SETTINGS;
                start(new Intent(act));
                result.success("settings opened");
                return;
            }
            case "lock": {
                SoraAccessibilityService svc = needAccessibility();
                if (!svc.lock()) throw new IllegalStateException("the phone did not lock");
                result.success("locked");
                return;
            }
            case "screenshot": {
                boolean send = p != null && Boolean.TRUE.equals(p.get("send"));
                needAccessibility().screenshot(new SoraAccessibilityService.Done() {
                    @Override
                    public void ok(String r) {
                        main.post(() -> result.success(r));
                    }

                    @Override
                    public void fail(String m) {
                        main.post(() -> result.error("failed", m, null));
                    }
                }, send);
                return;
            }
            case "status": {
                result.success(status().toString());
                return;
            }
            case "ring": {
                if ("stop".equalsIgnoreCase(target)) {
                    stopRing();
                    result.success("stopped ringing");
                    return;
                }
                ring(Math.max(5, Math.min(120, intParam(p, "seconds", 30))));
                result.success("ringing (even in silent mode)");
                return;
            }
            case "say":
                say(p, result);
                return;
            case "reply_notification": {
                String text = p == null || p.get("text") == null ? "" : String.valueOf(p.get("text"));
                if (TextUtils.isEmpty(target)) throw new IllegalArgumentException("reply to which notification?");
                SoraNotificationListener.reply(context, target, text);
                result.success("replied");
                return;
            }
            case "whatsapp_send":
                whatsappSend(target, p, result);
                return;
            default:
                throw new IllegalArgumentException("this phone can't do \"" + action + "\" yet");
        }
    }

    private boolean granted(String permission) {
        return context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED;
    }

    /** Like {@link #numberFor(String)}, falling back to the number the server found in Google contacts. */
    private String[] numberFor(String who, Map<String, Object> p) {
        Object fallback = p == null ? null : p.get("fallback_number");
        try {
            return numberFor(who);
        } catch (RuntimeException e) {
            boolean notFound = e.getMessage() != null
                    && (e.getMessage().startsWith("no contact") || e.getMessage().contains("read contacts"));
            if (notFound && fallback instanceof String && !((String) fallback).isEmpty()) {
                Object name = p.get("fallback_name");
                return new String[]{name == null ? who : name.toString(), ((String) fallback).replaceAll("[^0-9+]", "")};
            }
            throw e;
        }
    }

    /**
     * {name, number} for a phone number or a contact name from the phone's contacts. The best match wins:
     * exact name, then names starting with it, then names containing every word of it, then names that
     * sound the same (speech recognition writes "Tasdid" as "টাস্টিট" or "Tastit"; see {@link #soundKey}).
     * Several different people matching equally well is an error listing them, so Sora can ask which one.
     */
    private String[] numberFor(String who) {
        String digits = who.replaceAll("[^0-9+]", "");
        if (digits.length() >= 3 && digits.length() >= who.replaceAll("\\s", "").length() - 2) {
            return new String[]{digits, digits};
        }
        if (!granted(Manifest.permission.READ_CONTACTS)) {
            throw new IllegalStateException("Sora needs permission to read contacts (open Sora on the phone once to allow it)");
        }
        String want = norm(who), wantKey = soundKey(who);
        String[] words = who.toLowerCase(Locale.ROOT).trim().split("\\s+");
        Map<String, String[]> best = new LinkedHashMap<>(); // contact name -> {name, number, rank}
        int bestScore = 0;
        Map<String, Integer> near = new HashMap<>(); // contact name -> how far it sounds, for "closest names"
        String[] cols = {
                ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                ContactsContract.CommonDataKinds.Phone.NUMBER,
                ContactsContract.CommonDataKinds.Phone.TYPE,
                ContactsContract.CommonDataKinds.Phone.IS_SUPER_PRIMARY,
        };
        try (Cursor c = context.getContentResolver().query(
                ContactsContract.CommonDataKinds.Phone.CONTENT_URI, cols, null, null, null)) {
            if (c == null) throw new IllegalStateException("could not read the contacts");
            while (c.moveToNext()) {
                String name = c.getString(0), number = c.getString(1);
                if (name == null || number == null) continue;
                String n = norm(name);
                int score;
                if (n.equals(want)) score = 4;
                else if (n.startsWith(want)) score = 3;
                else if (containsAll(name.toLowerCase(Locale.ROOT), words) || n.contains(want)) score = 2;
                else if (soundsLike(wantKey, name)) score = 1;
                else {
                    near.put(name, soundDistance(wantKey, name));
                    continue;
                }
                if (score < bestScore) continue;
                if (score > bestScore) {
                    best.clear();
                    bestScore = score;
                }
                // Prefer the primary number, then a mobile number, for each person.
                int rank = c.getInt(3) != 0 ? 0 : (c.getInt(2) == ContactsContract.CommonDataKinds.Phone.TYPE_MOBILE ? 1 : 2);
                String[] old = best.get(name);
                if (old == null || rank < Integer.parseInt(old[2])) best.put(name, new String[]{name, number, String.valueOf(rank)});
            }
        }
        if (best.isEmpty()) {
            // The closest-sounding names, so Sora can ask "did you mean …?" (speech recognition misspells names).
            List<String> closest = new ArrayList<>();
            for (Map.Entry<String, Integer> e : near.entrySet()) {
                if (e.getValue() <= Math.max(1, wantKey.length() / 2)) closest.add(e.getKey());
            }
            java.util.Collections.sort(closest, (a, b) -> near.get(a) - near.get(b));
            String hint = closest.isEmpty() ? ""
                    : "; closest names: " + TextUtils.join(", ", closest.subList(0, Math.min(3, closest.size())));
            throw new IllegalArgumentException("no contact called \"" + who + "\" on this phone" + hint);
        }
        if (best.size() > 1) {
            throw new IllegalArgumentException("several contacts match \"" + who + "\": " + TextUtils.join(", ", best.keySet())
                    + " — which one?");
        }
        String[] one = best.values().iterator().next();
        return new String[]{one[0], one[1].replaceAll("[^0-9+]", "")};
    }

    /** [key] (a {@link #soundKey}) sounds like the whole of [name] or one of its words. */
    private static boolean soundsLike(String key, String name) {
        if (key.length() < 2) return false;
        List<String> parts = new ArrayList<>(Arrays.asList(name.trim().split("\\s+")));
        parts.add(name);
        for (String part : parts) {
            String k = soundKey(part);
            if (k.equals(key)) return true;
            if (key.length() >= 4 && k.length() >= 4 && editDistance(k, key) <= 1) return true;
        }
        return false;
    }

    /** The fewest letter changes between [key] and how [name] or one of its words sounds. */
    private static int soundDistance(String key, String name) {
        int best = Integer.MAX_VALUE;
        List<String> parts = new ArrayList<>(Arrays.asList(name.trim().split("\\s+")));
        parts.add(name);
        for (String part : parts) best = Math.min(best, editDistance(soundKey(part), key));
        return best;
    }

    /** Bangla letters → rough English letters, for {@link #soundKey}. */
    private static final Map<Character, String> BANGLA = new HashMap<>();

    static {
        String[] pairs = {
                "অa", "আa", "ইi", "ঈi", "উu", "ঊu", "ঋri", "এe", "ঐoi", "ওo", "ঔou",
                "াa", "িi", "ীi", "ুu", "ূu", "ৃri", "েe", "ৈoi", "োo", "ৌou", "ংng", "ঃh",
                "কk", "খkh", "গg", "ঘgh", "ঙng", "চch", "ছchh", "জj", "ঝjh", "ঞn",
                "টt", "ঠth", "ডd", "ঢdh", "ণn", "তt", "থth", "দd", "ধdh", "নn",
                "পp", "ফph", "বb", "ভbh", "মm", "যj", "রr", "লl", "শsh", "ষsh", "সs", "হh", "ৎt",
        };
        for (String pair : pairs) BANGLA.put(pair.charAt(0), pair.substring(1));
    }

    /**
     * How a name sounds, roughly, in either script: Bangla letters spelled out in English letters, then
     * only the consonants, with the pairs speech recognition mixes up merged (t/d, s/sh/z, k/c/q/g,
     * b/v/bh, p/f/ph…) and doubles collapsed; a leading vowel counts as "a". "Tasdid", "Tastit" and
     * "টাস্টিট" are all "tst"; "Ammu" and "আম্মু" are both "am".
     */
    static String soundKey(String s) {
        StringBuilder latin = new StringBuilder();
        // NFC splits ড় ঢ় য় into letter + nukta (U+09BC).
        String text = Normalizer.normalize(s == null ? "" : s, Normalizer.Form.NFC).toLowerCase(Locale.ROOT)
                .replace("ড়", "r").replace("ঢ়", "r").replace("য়", "y");
        for (char ch : text.toCharArray()) {
            String b = BANGLA.get(ch);
            if (b != null) latin.append(b);
            else if (ch >= 'a' && ch <= 'z') latin.append(ch);
        }
        String l = latin.toString()
                .replace("chh", "C").replace("ch", "C").replace("sh", "s").replace("ph", "f").replace("bh", "b")
                .replace("kh", "k").replace("gh", "g").replace("th", "t").replace("dh", "d").replace("jh", "j")
                .replace("x", "ks");
        StringBuilder key = new StringBuilder();
        for (int i = 0; i < l.length(); i++) {
            char c = l.charAt(i), k;
            switch (c) {
                case 'a': case 'e': case 'i': case 'o': case 'u': case 'y': case 'w': case 'h':
                    if (i == 0 && c != 'h') key.append('a');
                    continue;
                case 'd': k = 't'; break;
                case 'z': k = 'j'; break;
                case 'c': case 'q': case 'g': k = 'k'; break;
                case 'C': k = 'c'; break;
                case 'v': k = 'b'; break;
                case 'f': k = 'p'; break;
                default: k = c;
            }
            if (key.length() == 0 || key.charAt(key.length() - 1) != k) key.append(k);
        }
        return key.toString();
    }

    private static int editDistance(String a, String b) {
        int[] prev = new int[b.length() + 1], cur = new int[b.length() + 1];
        for (int j = 0; j <= b.length(); j++) prev[j] = j;
        for (int i = 1; i <= a.length(); i++) {
            cur[0] = i;
            for (int j = 1; j <= b.length(); j++) {
                int cost = a.charAt(i - 1) == b.charAt(j - 1) ? 0 : 1;
                cur[j] = Math.min(Math.min(cur[j - 1] + 1, prev[j] + 1), prev[j - 1] + cost);
            }
            int[] tmp = prev;
            prev = cur;
            cur = tmp;
        }
        return prev[b.length()];
    }

    /** Battery, network, storage, sound and model, as JSON for the PC app and Sora. */
    private org.json.JSONObject status() throws org.json.JSONException {
        org.json.JSONObject s = new org.json.JSONObject();
        Intent battery = context.registerReceiver(null, new android.content.IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        if (battery != null) {
            int level = battery.getIntExtra(android.os.BatteryManager.EXTRA_LEVEL, -1);
            int scale = battery.getIntExtra(android.os.BatteryManager.EXTRA_SCALE, 100);
            int state = battery.getIntExtra(android.os.BatteryManager.EXTRA_STATUS, -1);
            if (level >= 0) s.put("battery", Math.round(level * 100f / scale));
            s.put("charging", state == android.os.BatteryManager.BATTERY_STATUS_CHARGING
                    || state == android.os.BatteryManager.BATTERY_STATUS_FULL);
            s.put("temperature_c", battery.getIntExtra(android.os.BatteryManager.EXTRA_TEMPERATURE, 0) / 10.0);
        }
        android.net.ConnectivityManager cm = context.getSystemService(android.net.ConnectivityManager.class);
        android.net.NetworkCapabilities caps = cm == null ? null : cm.getNetworkCapabilities(cm.getActiveNetwork());
        s.put("network", caps == null ? "offline"
                : caps.hasTransport(android.net.NetworkCapabilities.TRANSPORT_WIFI) ? "wifi"
                : caps.hasTransport(android.net.NetworkCapabilities.TRANSPORT_CELLULAR) ? "mobile" : "other");
        android.os.StatFs fs = new android.os.StatFs(android.os.Environment.getDataDirectory().getPath());
        s.put("storage_free_gb", Math.round(fs.getAvailableBytes() / 1e8) / 10.0);
        s.put("storage_total_gb", Math.round(fs.getTotalBytes() / 1e8) / 10.0);
        AudioManager audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
        int mode = audio.getRingerMode();
        s.put("ringer", mode == AudioManager.RINGER_MODE_SILENT ? "silent" : mode == AudioManager.RINGER_MODE_VIBRATE ? "vibrate" : "normal");
        s.put("volume", Math.round(audio.getStreamVolume(AudioManager.STREAM_MUSIC) * 100f / audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC)));
        s.put("model", android.os.Build.MANUFACTURER + " " + android.os.Build.MODEL);
        s.put("android", android.os.Build.VERSION.RELEASE);
        s.put("screen_on", context.getSystemService(android.os.PowerManager.class).isInteractive());
        return s;
    }

    private static android.media.Ringtone ringing;
    private static int volumeBefore = -1;

    /** "Find my phone": the ringtone on the alarm stream at full volume (heard in silent mode too). */
    private void ring(int seconds) {
        stopRing();
        AudioManager audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
        volumeBefore = audio.getStreamVolume(AudioManager.STREAM_ALARM);
        audio.setStreamVolume(AudioManager.STREAM_ALARM, audio.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0);
        Uri tone = android.media.RingtoneManager.getActualDefaultRingtoneUri(context, android.media.RingtoneManager.TYPE_RINGTONE);
        if (tone == null) tone = android.media.RingtoneManager.getDefaultUri(android.media.RingtoneManager.TYPE_ALARM);
        ringing = android.media.RingtoneManager.getRingtone(context, tone);
        if (ringing == null) throw new IllegalStateException("no ringtone to play");
        ringing.setAudioAttributes(new android.media.AudioAttributes.Builder()
                .setUsage(android.media.AudioAttributes.USAGE_ALARM).build());
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.P) ringing.setLooping(true);
        ringing.play();
        main.postDelayed(this::stopRing, seconds * 1000L);
    }

    private void stopRing() {
        if (ringing != null) ringing.stop();
        ringing = null;
        if (volumeBefore >= 0) {
            AudioManager audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
            audio.setStreamVolume(AudioManager.STREAM_ALARM, volumeBefore, 0);
            volumeBefore = -1;
        }
    }

    private void openNotificationAccess() {
        String me = SoraNotificationListener.component(context).flattenToString();
        if (android.os.Build.VERSION.SDK_INT >= 30) {
            try { // straight to Sora's switch
                start(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_DETAIL_SETTINGS)
                        .putExtra(Settings.EXTRA_NOTIFICATION_LISTENER_COMPONENT_NAME, me));
                return;
            } catch (ActivityNotFoundException ignored) {
                // some phones have only the list
            }
        }
        start(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS));
    }

    private static final Map<String, String> COUNTRY_CODES = new HashMap<>();

    static {
        String[] pairs = {"bd", "880", "in", "91", "pk", "92", "np", "977", "lk", "94", "us", "1", "ca", "1", "gb", "44",
                "ae", "971", "sa", "966", "qa", "974", "kw", "965", "om", "968", "bh", "973", "my", "60", "sg", "65",
                "au", "61", "it", "39", "de", "49", "fr", "33", "jp", "81", "kr", "82"};
        for (int i = 0; i < pairs.length; i += 2) COUNTRY_CODES.put(pairs[i], pairs[i + 1]);
    }

    /** A number as wa.me wants it: digits with the country code ("01712…" in Bangladesh → "8801712…"). */
    private String internationalDigits(String number) {
        String d = number.replaceAll("[^0-9+]", "");
        if (d.startsWith("+")) return d.substring(1);
        if (d.startsWith("00")) return d.substring(2);
        TelephonyManager tm = context.getSystemService(TelephonyManager.class);
        String iso = tm == null ? "" : tm.getSimCountryIso();
        if (TextUtils.isEmpty(iso) && tm != null) iso = tm.getNetworkCountryIso();
        String code = COUNTRY_CODES.get(iso == null ? "" : iso.toLowerCase(Locale.ROOT));
        if (code == null) return d; // taken as already international
        if (d.startsWith("0")) return code + d.substring(1);
        return d.length() <= 10 ? code + d : d;
    }

    /**
     * whatsapp_send (the owner approved it): opens the chat with the message typed in, then the
     * accessibility service taps Send once. Without it, or when Send doesn't show up, the chat stays
     * open with the message ready and the answer says to tap Send.
     */
    private void whatsappSend(String target, Map<String, Object> p, MethodChannel.Result result) {
        String text = p == null || p.get("text") == null ? "" : String.valueOf(p.get("text"));
        if (TextUtils.isEmpty(target) || text.isEmpty()) throw new IllegalArgumentException("WhatsApp whom, and what?");
        String pkg = null;
        for (String candidate : new String[]{"com.whatsapp", "com.whatsapp.w4b"}) {
            if (context.getPackageManager().getLaunchIntentForPackage(candidate) != null) {
                pkg = candidate;
                break;
            }
        }
        if (pkg == null) throw new IllegalStateException("WhatsApp isn't installed on this phone");
        String[] who = numberFor(target, p);
        Uri chat = Uri.parse("https://wa.me/" + internationalDigits(who[1]) + "?text=" + Uri.encode(text));
        start(new Intent(Intent.ACTION_VIEW, chat).setPackage(pkg));
        SoraAccessibilityService svc = SoraAccessibilityService.instance;
        String name = who[0];
        if (svc == null) {
            result.success("opened the WhatsApp chat with " + name + " with the message typed in; Sora can't tap Send "
                    + "without its accessibility service, so tap Send on the phone");
            return;
        }
        svc.tapSend(pkg, 8000, new SoraAccessibilityService.Done() {
            @Override
            public void ok(String r) {
                main.post(() -> result.success("sent to " + name + " on WhatsApp"));
            }

            @Override
            public void fail(String m) {
                main.post(() -> result.error("failed", m, null));
            }
        });
    }

    private static android.media.MediaPlayer saying;
    private static java.io.File sayingFile;

    /**
     * A routine's result, said aloud: plays the MP3 the server made (its Bangla voice is better than most
     * phones'), ducking music meanwhile. Not on silent or in a call: the server then tries the PC.
     */
    private void say(Map<String, Object> p, MethodChannel.Result result) {
        Object audio = p == null ? null : p.get("audio_mp3_base64");
        if (!(audio instanceof String)) throw new IllegalArgumentException("no audio to play");
        AudioManager am = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
        if (am.getRingerMode() != AudioManager.RINGER_MODE_NORMAL) throw new IllegalStateException("the phone is on silent");
        int mode = am.getMode();
        if (mode == AudioManager.MODE_IN_CALL || mode == AudioManager.MODE_IN_COMMUNICATION) {
            throw new IllegalStateException("the phone is in a call");
        }
        java.io.File dir = context.getCacheDir();
        new Thread(() -> { // decoding and writing it stay off the main thread
            java.io.File file;
            try {
                file = java.io.File.createTempFile("sora-say", ".mp3", dir);
                try (java.io.FileOutputStream out = new java.io.FileOutputStream(file)) {
                    out.write(android.util.Base64.decode((String) audio, android.util.Base64.DEFAULT));
                }
            } catch (Exception e) {
                main.post(() -> result.error("failed", "couldn't play it: " + e.getMessage(), null));
                return;
            }
            main.post(() -> play(am, file, result));
        }, "sora-say").start();
    }

    private void play(AudioManager am, java.io.File file, MethodChannel.Result result) {
        stopSaying();
        android.media.AudioAttributes attrs = new android.media.AudioAttributes.Builder()
                .setUsage(android.media.AudioAttributes.USAGE_ASSISTANT)
                .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SPEECH).build();
        android.media.MediaPlayer player = new android.media.MediaPlayer();
        saying = player;
        sayingFile = file;
        boolean[] answered = {false};
        AudioManager.OnAudioFocusChangeListener ignore = change -> { };
        Runnable finish = () -> {
            am.abandonAudioFocus(ignore);
            if (saying == player) stopSaying();
        };
        player.setAudioAttributes(attrs);
        player.setOnPreparedListener(m -> {
            am.requestAudioFocus(ignore, AudioManager.STREAM_MUSIC, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK);
            m.start();
            answered[0] = true;
            result.success("saying it");
        });
        player.setOnCompletionListener(m -> finish.run());
        player.setOnErrorListener((m, what, extra) -> {
            finish.run();
            if (!answered[0]) {
                answered[0] = true;
                result.error("failed", "couldn't play it (" + what + ")", null);
            }
            return true;
        });
        try {
            player.setDataSource(file.getPath());
            player.prepareAsync();
        } catch (Exception e) {
            finish.run();
            result.error("failed", "couldn't play it: " + e.getMessage(), null);
        }
    }

    /** Stops what is being said (a newer one interrupts it) and deletes its file. */
    private static void stopSaying() {
        if (saying != null) saying.release();
        if (sayingFile != null) sayingFile.delete();
        saying = null;
        sayingFile = null;
    }

    /**
     * The SIM the owner named: "1" / "2" / "SIM 2" / "২" (the slot), or part of the carrier's name
     * ("Grameenphone", "Robi"); null when they didn't name one (the phone's default is used).
     */
    private SubscriptionInfo sim(Object which) {
        String w = which == null ? "" : String.valueOf(which).trim().toLowerCase(Locale.ROOT);
        w = w.replace('১', '1').replace('২', '2').replaceAll("^(sim|সিম)\\s*", "").trim();
        if (w.isEmpty()) return null;
        if (!granted(Manifest.permission.READ_PHONE_STATE)) {
            throw new IllegalStateException("Sora needs the Phone permission to pick a SIM (open Sora on the phone once to allow it)");
        }
        SubscriptionManager sm = context.getSystemService(SubscriptionManager.class);
        List<SubscriptionInfo> subs = sm == null ? null : sm.getActiveSubscriptionInfoList();
        if (subs == null || subs.isEmpty()) throw new IllegalStateException("no SIM card is active");
        for (SubscriptionInfo s : subs) {
            if (w.matches("\\d") && s.getSimSlotIndex() == Integer.parseInt(w) - 1) return s;
        }
        for (SubscriptionInfo s : subs) {
            String name = (s.getDisplayName() + " " + s.getCarrierName()).toLowerCase(Locale.ROOT);
            if (name.contains(w)) return s;
        }
        List<String> have = new ArrayList<>();
        for (SubscriptionInfo s : subs) have.add(simName(s));
        throw new IllegalArgumentException("no SIM \"" + which + "\" — this phone has " + TextUtils.join(", ", have));
    }

    private static String simName(SubscriptionInfo s) {
        return "SIM " + (s.getSimSlotIndex() + 1) + " (" + s.getDisplayName() + ")";
    }

    /** The calling account of [sub], for placing a call from that SIM. */
    private PhoneAccountHandle account(SubscriptionInfo sub) {
        TelecomManager telecom = context.getSystemService(TelecomManager.class);
        List<PhoneAccountHandle> accounts = telecom.getCallCapablePhoneAccounts();
        TelephonyManager phone = context.getSystemService(TelephonyManager.class);
        for (PhoneAccountHandle h : accounts) {
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R) {
                if (phone.getSubscriptionId(h) == sub.getSubscriptionId()) return h;
            } else if (h.getId().equals(String.valueOf(sub.getSubscriptionId())) || h.getId().equals(sub.getIccId())) {
                return h;
            }
        }
        int slot = sub.getSimSlotIndex();
        return slot >= 0 && slot < accounts.size() ? accounts.get(slot) : null;
    }

    private static boolean containsAll(String text, String[] words) {
        for (String w : words) {
            if (!w.isEmpty() && !text.contains(w)) return false;
        }
        return true;
    }

    private SoraAccessibilityService needAccessibility() {
        SoraAccessibilityService svc = SoraAccessibilityService.instance;
        if (svc == null) {
            throw new IllegalStateException("turn on Sora in the phone's Settings → Accessibility first");
        }
        return svc;
    }

    private void start(Intent intent) {
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(intent);
    }

    private static int intParam(Map<String, Object> p, String key, int fallback) {
        Object v = p == null ? null : p.get(key);
        return v instanceof Number ? ((Number) v).intValue() : fallback;
    }

    private String label(ResolveInfo app) {
        return app.loadLabel(context.getPackageManager()).toString();
    }

    private static String norm(String s) {
        String n = Normalizer.normalize(s == null ? "" : s, Normalizer.Form.NFKC).toLowerCase(Locale.ROOT);
        return n.replaceAll("[^\\p{L}\\p{N}]+", "");
    }

    /** The launcher app whose name best matches [name]: exact, then starts-with, then contains. */
    private ResolveInfo findApp(String name) {
        if (TextUtils.isEmpty(name)) return null;
        String want = norm(name);
        PackageManager pm = context.getPackageManager();
        Intent query = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
        List<ResolveInfo> apps = pm.queryIntentActivities(query, 0);
        ResolveInfo starts = null, contains = null;
        for (ResolveInfo app : apps) {
            String l = norm(app.loadLabel(pm).toString());
            if (l.equals(want)) return app;
            if (starts == null && l.startsWith(want)) starts = app;
            if (contains == null && (l.contains(want) || norm(app.activityInfo.packageName).contains(want))) contains = app;
        }
        return starts != null ? starts : contains;
    }

    /** SearchManager.QUERY without pulling in the class for one constant. */
    private static final class SearchManagerQuery {
        static final String KEY = "query";
    }
}
