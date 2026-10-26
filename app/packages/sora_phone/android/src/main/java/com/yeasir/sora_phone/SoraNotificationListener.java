package com.yeasir.sora_phone;

import android.app.Notification;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.RemoteInput;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Parcelable;
import android.provider.Settings;
import android.provider.Telephony;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;
import android.text.TextUtils;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Notifications from the apps the owner chose (WhatsApp, Messenger, Telegram and SMS by default) go
 * to the PC's Sora over the phone's open line ({@link SoraLink}), not a new request: the PC shows
 * them, and Sora can say what came and answer through the notification's own Reply.
 *
 * <p>Off until the owner turns it on in the app and allows "Notification access". Ongoing, silent and
 * group-summary notifications, and Sora's own, are skipped; one re-posted unchanged is sent once.
 * Android calls in for each notification, so there is nothing to poll.
 */
public class SoraNotificationListener extends NotificationListenerService {
    private static final String PREFS = "sora_notifications";
    private static final List<String> DEFAULT_APPS = Arrays.asList(
            "com.whatsapp", "com.whatsapp.w4b", "com.facebook.orca", "com.facebook.mlite", "org.telegram.messenger",
            "com.google.android.apps.messaging", "com.samsung.android.messaging");
    private static final int REPLIES_KEPT = 50, SENT_KEPT = 200, SEEN_KEPT = 30;

    // notification key -> its Reply action, for reply_notification (newest last; the oldest go)
    private static final Map<String, Notification.Action> replies = lru(REPLIES_KEPT);
    // notification key -> what was last sent for it, to drop re-posts of the same thing
    private static final Map<String, String> sent = lru(SENT_KEPT);
    private static final Map<String, String> labels = new HashMap<>();

    private static <V> Map<String, V> lru(int keep) {
        return new LinkedHashMap<String, V>(16, 0.75f, true) {
            @Override
            protected boolean removeEldestEntry(Map.Entry<String, V> eldest) {
                return size() > keep;
            }
        };
    }

    // ------------------------------------------------------------------ settings (the app's Settings screen)

    private static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static boolean enabled(Context c) {
        return prefs(c).getBoolean("enabled", false);
    }

    /** The apps whose notifications go to the PC: the owner's choice, else the messaging apps. */
    static Set<String> allowed(Context c) {
        Set<String> chosen = prefs(c).getStringSet("allowed", null);
        if (chosen != null) return chosen;
        Set<String> apps = new HashSet<>(DEFAULT_APPS);
        String sms = Telephony.Sms.getDefaultSmsPackage(c);
        if (sms != null) apps.add(sms);
        return apps;
    }

    static boolean accessGranted(Context c) {
        String on = Settings.Secure.getString(c.getContentResolver(), "enabled_notification_listeners");
        return on != null && on.contains(new ComponentName(c, SoraNotificationListener.class).flattenToString());
    }

    static ComponentName component(Context c) {
        return new ComponentName(c, SoraNotificationListener.class);
    }

    /** Changes what is given (on/off, the allowed apps) and returns the state for the Settings screen. */
    static Map<String, Object> configure(Context c, Boolean on, List<String> allowedApps) {
        SharedPreferences.Editor e = prefs(c).edit();
        if (on != null) e.putBoolean("enabled", on);
        if (allowedApps != null) e.putStringSet("allowed", new HashSet<>(allowedApps));
        e.apply();
        Map<String, Object> state = new HashMap<>();
        state.put("enabled", on != null ? on : enabled(c));
        state.put("access", accessGranted(c));
        Set<String> allowedNow = allowedApps != null ? new HashSet<>(allowedApps) : allowed(c);
        state.put("allowed", new ArrayList<>(allowedNow));
        // The apps to choose from: the allowed ones (installed) and the ones seen posting lately.
        List<Map<String, String>> apps = new ArrayList<>();
        Set<String> listed = new HashSet<>();
        List<String> candidates = new ArrayList<>(allowedNow);
        candidates.addAll(seen(c));
        for (String pkg : candidates) {
            if (!listed.add(pkg) || !installed(c, pkg)) continue;
            Map<String, String> app = new HashMap<>();
            app.put("package", pkg);
            app.put("label", label(c, pkg));
            apps.add(app);
        }
        state.put("apps", apps);
        return state;
    }

    private static List<String> seen(Context c) {
        List<String> out = new ArrayList<>();
        try {
            JSONObject json = new JSONObject(prefs(c).getString("seen", "{}"));
            for (Iterator<String> it = json.keys(); it.hasNext(); ) out.add(it.next());
        } catch (Exception ignored) {
            // nothing seen yet
        }
        return out;
    }

    /** Remembers an app that posts notifications (newest last), so the owner can pick it. Written only when new. */
    private static void noteSeen(Context c, String pkg) {
        try {
            JSONObject json = new JSONObject(prefs(c).getString("seen", "{}"));
            if (json.has(pkg)) return;
            json.put(pkg, 1);
            JSONObject kept = new JSONObject();
            int skip = Math.max(0, json.length() - SEEN_KEPT);
            for (Iterator<String> it = json.keys(); it.hasNext(); ) {
                String k = it.next();
                if (skip-- > 0) continue;
                kept.put(k, 1);
            }
            prefs(c).edit().putString("seen", kept.toString()).apply();
        } catch (Exception ignored) {
            // just a convenience for the Settings list
        }
    }

    private static boolean installed(Context c, String pkg) {
        try {
            c.getPackageManager().getApplicationInfo(pkg, 0);
            return true;
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
    }

    private static String label(Context c, String pkg) {
        synchronized (labels) {
            String known = labels.get(pkg);
            if (known != null) return known;
            String name = pkg;
            try {
                PackageManager pm = c.getPackageManager();
                name = pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString();
            } catch (Exception ignored) {
                // not visible to Sora: the package name will do
            }
            labels.put(pkg, name);
            return name;
        }
    }

    // ------------------------------------------------------------------ notifications

    @Override
    public void onListenerConnected() {
        // After a restart: the Reply buttons of what is still showing.
        try {
            for (StatusBarNotification sbn : getActiveNotifications()) rememberReply(sbn);
        } catch (Exception ignored) {
            // not connected after all
        }
    }

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        Context c = getApplicationContext();
        if (!enabled(c)) return;
        String pkg = sbn.getPackageName();
        if (pkg.equals(c.getPackageName())) return; // Sora's own
        Notification n = sbn.getNotification();
        int skip = Notification.FLAG_ONGOING_EVENT | Notification.FLAG_GROUP_SUMMARY | Notification.FLAG_FOREGROUND_SERVICE;
        if ((n.flags & skip) != 0 || silent(sbn)) return;
        noteSeen(c, pkg);
        if (!allowed(c).contains(pkg)) return;

        Bundle x = n.extras;
        String title = str(x.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE));
        if (title.isEmpty()) title = str(x.getCharSequence(Notification.EXTRA_TITLE));
        String text = lastMessage(x, title);
        if (text.isEmpty()) text = str(x.getCharSequence(Notification.EXTRA_BIG_TEXT));
        if (text.isEmpty()) text = str(x.getCharSequence(Notification.EXTRA_TEXT));
        if (title.isEmpty() && text.isEmpty()) return;

        String key = sbn.getKey(), what = title + "\n" + text;
        synchronized (sent) {
            if (what.equals(sent.get(key))) return;
            sent.put(key, what);
        }
        boolean replyable = rememberReply(sbn);
        try {
            SoraLink.sendEvent(new JSONObject()
                    .put("type", "phone_notification")
                    .put("key", key)
                    .put("app", label(c, pkg))
                    .put("package", pkg)
                    .put("title", title)
                    .put("text", text.length() > 1000 ? text.substring(0, 1000) : text)
                    .put("replyable", replyable)
                    .toString());
        } catch (Exception ignored) {
            // not sent: the PC simply doesn't get this one
        }
    }

    @Override
    public void onNotificationRemoved(StatusBarNotification sbn) {
        synchronized (replies) {
            replies.remove(sbn.getKey());
        }
    }

    /** Below the default importance: the app itself wants it quiet. */
    private boolean silent(StatusBarNotification sbn) {
        try {
            Ranking r = new Ranking();
            return getCurrentRanking().getRanking(sbn.getKey(), r) && r.getImportance() < NotificationManager.IMPORTANCE_DEFAULT;
        } catch (Exception e) {
            return false;
        }
    }

    /** A chat's newest message ("Karim: on my way" in a group), from MessagingStyle. */
    private static String lastMessage(Bundle x, String title) {
        Parcelable[] messages = x.getParcelableArray(Notification.EXTRA_MESSAGES);
        if (messages == null || messages.length == 0 || !(messages[messages.length - 1] instanceof Bundle)) return "";
        Bundle last = (Bundle) messages[messages.length - 1];
        String text = str(last.getCharSequence("text"));
        String sender = str(last.getCharSequence("sender"));
        if (sender.isEmpty() && android.os.Build.VERSION.SDK_INT >= 28 && last.get("sender_person") instanceof android.app.Person) {
            sender = str(((android.app.Person) last.get("sender_person")).getName());
        }
        return !sender.isEmpty() && !sender.equals(title) && !text.isEmpty() ? sender + ": " + text : text;
    }

    private static String str(CharSequence s) {
        return s == null ? "" : s.toString().trim();
    }

    /** Keeps the notification's Reply (an action that takes typed text); true when it has one. */
    private static boolean rememberReply(StatusBarNotification sbn) {
        Notification n = sbn.getNotification();
        List<Notification.Action> actions = new ArrayList<>();
        if (n.actions != null) actions.addAll(Arrays.asList(n.actions));
        actions.addAll(new Notification.WearableExtender(n).getActions()); // some apps put Reply only here
        for (Notification.Action a : actions) {
            RemoteInput[] inputs = a.getRemoteInputs();
            if (inputs == null) continue;
            for (RemoteInput in : inputs) {
                if (in.getAllowFreeFormInput()) {
                    synchronized (replies) {
                        replies.put(sbn.getKey(), a);
                    }
                    return true;
                }
            }
        }
        return false;
    }

    /** reply_notification: answers through the notification's own Reply, as typing in it would. */
    static void reply(Context c, String key, String text) throws PendingIntent.CanceledException {
        Notification.Action a;
        synchronized (replies) {
            a = replies.get(key);
        }
        if (a == null) throw new IllegalStateException("that notification is gone from the phone (answered or cleared)");
        if (TextUtils.isEmpty(text)) throw new IllegalArgumentException("reply with what?");
        Intent fill = new Intent();
        Bundle results = new Bundle();
        for (RemoteInput in : a.getRemoteInputs()) results.putCharSequence(in.getResultKey(), text);
        RemoteInput.addResultsToIntent(a.getRemoteInputs(), fill, results);
        a.actionIntent.send(c, 0, fill);
    }
}
