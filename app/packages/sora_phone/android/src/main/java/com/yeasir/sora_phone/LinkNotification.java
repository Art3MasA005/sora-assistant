package com.yeasir.sora_phone;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.SystemClock;
import android.widget.RemoteViews;

/**
 * The "Connected to the PC" notification in the status bar and the shade while {@link SoraLink} is
 * connected, with Disconnect and Turn off notification; after Disconnect it says so and offers
 * Connect. Quiet (no sound, no pop-up). The content is a glass panel (res/drawable/sora_glass.xml)
 * over the card Android draws — apps can't make the card itself see-through.
 */
final class LinkNotification {
    private LinkNotification() {
    }

    static final String CHANNEL = "sora_link";
    static final int ID = 4712;
    static final String DISCONNECT = "com.yeasir.sora_phone.DISCONNECT";
    static final String CONNECT = "com.yeasir.sora_phone.CONNECT";
    static final String HIDE = "com.yeasir.sora_phone.HIDE_NOTIFICATION";

    private static long connectedAt; // SystemClock.elapsedRealtime() of the current connection

    private static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences("sora_link", Context.MODE_PRIVATE);
    }

    static boolean enabled(Context c) {
        return prefs(c).getBoolean("notify", true);
    }

    /** The owner's choice (notification's "Turn off notification", or the app's Settings). */
    static void setEnabled(Context c, boolean on) {
        prefs(c).edit().putBoolean("notify", on).apply();
        if (!on) cancel(c);
        else SoraLink.refreshNotification();
    }

    private static boolean bangla(Context c) {
        return prefs(c).getBoolean("bangla", false);
    }

    static void connected(Context c, String pc) {
        connectedAt = SystemClock.elapsedRealtime();
        show(c, true, pc);
    }

    /** Shown again (language or the switch changed) without restarting the timer. */
    static void stillConnected(Context c, String pc) {
        if (connectedAt == 0) connectedAt = SystemClock.elapsedRealtime();
        show(c, true, pc);
    }

    static void paused(Context c) {
        connectedAt = 0;
        show(c, false, null);
    }

    static void cancel(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null) nm.cancel(ID);
    }

    static void gone(Context c) {
        connectedAt = 0;
        cancel(c);
    }

    private static void show(Context c, boolean on, String pc) {
        if (!enabled(c)) return;
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm == null) return;
        boolean bn = bangla(c);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, bn ? "PC-র সাথে সংযোগ" : "PC connection",
                    NotificationManager.IMPORTANCE_LOW);
            ch.setDescription(bn ? "ফোন PC-র Sora-র সাথে যুক্ত থাকলে দেখায়" : "Shown while the phone is connected to Sora on the PC");
            ch.setShowBadge(false);
            nm.createNotificationChannel(ch);
        }
        String name = pc == null || pc.isEmpty() ? (bn ? "PC" : "the PC") : pc;
        String title = on ? (bn ? name + "-এর সাথে যুক্ত" : "Connected to " + name)
                : (bn ? "PC থেকে বিচ্ছিন্ন" : "Disconnected from the PC");
        String text = on
                ? (bn ? "ক্লিপবোর্ড শেয়ার চালু · PC থেকে ফোন চালানো যাবে" : "Clipboard shared · the PC can reach this phone")
                : (bn ? "আবার যুক্ত করতে Connect চাপুন" : "Tap Connect to link it again");

        RemoteViews small = views(c, R.layout.sora_link_small, on, title, null);
        RemoteViews big = views(c, R.layout.sora_link_big, on, title, text);

        Notification.Builder b = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new Notification.Builder(c, CHANNEL) : new Notification.Builder(c);
        b.setSmallIcon(R.drawable.sora_link_icon)
                .setColor(0xFF5CC8FF)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(new Notification.DecoratedCustomViewStyle())
                .setCustomContentView(small)
                .setCustomBigContentView(big)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setShowWhen(false)
                .setCategory(Notification.CATEGORY_STATUS)
                .setVisibility(Notification.VISIBILITY_PUBLIC);
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) b.setPriority(Notification.PRIORITY_LOW);
        Intent open = c.getPackageManager().getLaunchIntentForPackage(c.getPackageName());
        if (open != null) b.setContentIntent(PendingIntent.getActivity(c, 0, open, PendingIntent.FLAG_IMMUTABLE));
        if (on) b.addAction(action(c, DISCONNECT, bn ? "বিচ্ছিন্ন করুন" : "Disconnect", 1));
        else b.addAction(action(c, CONNECT, bn ? "যুক্ত করুন" : "Connect", 2));
        b.addAction(action(c, HIDE, bn ? "নোটিফিকেশন বন্ধ" : "Turn off notification", 3));
        try {
            nm.notify(ID, b.build());
        } catch (SecurityException ignored) {
            // notifications not allowed (Android 13+ asks; the app asks once)
        }
    }

    private static RemoteViews views(Context c, int layout, boolean on, String title, String text) {
        RemoteViews v = new RemoteViews(c.getPackageName(), layout);
        v.setImageViewResource(R.id.sora_dot, on ? R.drawable.sora_dot_on : R.drawable.sora_dot_off);
        v.setTextViewText(R.id.sora_title, title);
        if (text != null) v.setTextViewText(R.id.sora_text, text);
        if (on && connectedAt > 0) {
            v.setChronometer(R.id.sora_since, connectedAt, null, true);
        } else {
            v.setViewVisibility(R.id.sora_since, android.view.View.GONE);
        }
        return v;
    }

    private static Notification.Action action(Context c, String what, String label, int code) {
        Intent i = new Intent(c, Actions.class).setAction(what);
        PendingIntent pi = PendingIntent.getBroadcast(c, code, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Action.Builder(null, label, pi).build();
    }

    /** The notification's buttons. */
    public static class Actions extends BroadcastReceiver {
        @Override
        public void onReceive(Context context, Intent intent) {
            String a = intent.getAction();
            if (DISCONNECT.equals(a)) SoraLink.setPaused(context, true);
            else if (CONNECT.equals(a)) SoraLink.setPaused(context, false);
            else if (HIDE.equals(a)) setEnabled(context, false);
        }
    }
}
