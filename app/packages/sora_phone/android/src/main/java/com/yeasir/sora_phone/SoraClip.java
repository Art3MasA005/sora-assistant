package com.yeasir.sora_phone;

import android.content.ClipData;
import android.content.ClipDescription;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.database.ContentObserver;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.PersistableBundle;
import android.provider.MediaStore;
import android.view.accessibility.AccessibilityEvent;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

import io.flutter.plugin.common.MethodChannel;

/**
 * The phone's half of the shared phone/PC clipboard. Android (10+) lets only the keyboard and the
 * app in front read the clipboard, so Sora's accessibility service notices a tap on "Copy" (in any
 * app's text menu, Chrome, WhatsApp…), then opens an invisible screen for a moment to read what was
 * copied ({@link ClipReaderActivity}). New screenshots are noticed in the photo library. Both go to
 * the Sora server for the PC ({@link SoraLink}; before the app has signed in it, to the Dart side:
 * "clipboard" / "screenshot" calls on the plugin channel). Copies marked private (password managers) are not sent.
 */
final class SoraClip {
    private SoraClip() {
    }

    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    // "Copy", "Copy text", "Copy link", "কপি", "কপি করুন"…
    private static final Pattern COPY = Pattern.compile("^\\s*(copy|copy text|copy link|copy all|কপি.*)\\s*$",
            Pattern.CASE_INSENSITIVE);

    /** Channels of the Flutter engines running now (the app, the "Hey Sora" service); the newest gets events. */
    private static final List<MethodChannel> channels = new ArrayList<>();
    static volatile boolean on = false; // the owner's "Sync clipboard" setting, set by the app
    static volatile String setBySora = ""; // text Sora put on the clipboard (from the PC): not sent back
    private static String lastSent = "";
    private static long lastScreenshotId = -1;
    static volatile String skipScreenshot = ""; // taken for the PC app, which shows it itself
    private static ContentObserver screenshots;

    static synchronized void attach(MethodChannel channel) {
        channels.add(channel);
    }

    static synchronized void detach(MethodChannel channel) {
        channels.remove(channel);
    }

    /** A server event for the app's screens (a device came online…), to every Flutter engine running now.
     * With none running (the app closed) it is simply dropped: nothing waits for it. */
    static void toApps(String method, Object args) {
        MAIN.post(() -> {
            List<MethodChannel> now;
            synchronized (SoraClip.class) {
                now = new ArrayList<>(channels);
            }
            for (MethodChannel channel : now) channel.invokeMethod(method, args);
        });
    }

    private static void deliver(String method, Object args) {
        if (SoraLink.sendClip(method, args)) return; // straight to the server, app open or not
        MAIN.post(() -> {
            MethodChannel channel;
            synchronized (SoraClip.class) {
                channel = channels.isEmpty() ? null : channels.get(channels.size() - 1);
            }
            if (channel != null) channel.invokeMethod(method, args);
        });
    }

    /** From the accessibility service: was that a tap on "Copy"? Then read the clipboard shortly. */
    static void onEvent(Context context, AccessibilityEvent event) {
        if (!on || event.getEventType() != AccessibilityEvent.TYPE_VIEW_CLICKED) return;
        StringBuilder said = new StringBuilder();
        for (CharSequence t : event.getText()) said.append(t);
        CharSequence desc = event.getContentDescription();
        if (!COPY.matcher(said).matches() && (desc == null || !COPY.matcher(desc).matches())) return;
        MAIN.postDelayed(() -> {
            Intent read = new Intent(context, ClipReaderActivity.class)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_NO_ANIMATION
                            | Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS | Intent.FLAG_ACTIVITY_NO_HISTORY);
            try {
                context.startActivity(read);
            } catch (Exception ignored) {
                // not allowed right now: this copy just isn't sent
            }
        }, 250);
    }

    /** From {@link ClipReaderActivity}, which has the focus Android requires. */
    static void readNow(Context context) {
        ClipboardManager cm = context.getSystemService(ClipboardManager.class);
        ClipData clip = cm == null ? null : cm.getPrimaryClip();
        if (clip == null || clip.getItemCount() == 0) return;
        ClipDescription d = clip.getDescription();
        if (d != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            PersistableBundle extras = d.getExtras();
            if (extras != null && extras.getBoolean("android.content.extra.IS_SENSITIVE", false)) return;
        }
        ClipData.Item first = clip.getItemAt(0);
        if (first.getText() == null && first.getUri() != null) return; // an image or file, not text
        CharSequence text = first.coerceToText(context);
        if (text == null) return;
        String s = text.toString();
        if (s.trim().isEmpty() || s.equals(setBySora) || s.equals(lastSent)) return;
        lastSent = s;
        deliver("clipboard", s);
    }

    /** Puts [text] (from the PC) on the phone's clipboard; writing is allowed in the background. */
    static void set(Context context, String text) {
        setBySora = text;
        ClipboardManager cm = context.getSystemService(ClipboardManager.class);
        if (cm == null) throw new IllegalStateException("no clipboard");
        cm.setPrimaryClip(ClipData.newPlainText("Sora", text));
    }

    /** Puts an image (PNG, from the PC) on the phone's clipboard, served by {@link ClipImageProvider}. */
    static void setImage(Context context, byte[] png) throws java.io.IOException {
        java.io.File dir = ClipImageProvider.folder(context);
        java.io.File[] old = dir.listFiles();
        if (old != null) for (java.io.File f : old) //noinspection ResultOfMethodCallIgnored
            f.delete();
        String name = "pc-" + System.currentTimeMillis() + ".png"; // a new name: apps may cache by URI
        try (java.io.FileOutputStream out = new java.io.FileOutputStream(new java.io.File(dir, name))) {
            out.write(png);
        }
        Uri uri = Uri.parse("content://" + context.getPackageName() + ".soraclip/" + name);
        ClipboardManager cm = context.getSystemService(ClipboardManager.class);
        if (cm == null) throw new IllegalStateException("no clipboard");
        setBySora = "";
        cm.setPrimaryClip(ClipData.newUri(context.getContentResolver(), "Image from the PC", uri));
    }

    /** Starts noticing new screenshots (needs the photos permission, asked for by the app). */
    static void watchScreenshots(Context context) {
        if (screenshots != null) return;
        screenshots = new ContentObserver(MAIN) {
            @Override
            public void onChange(boolean selfChange, Uri uri) {
                MAIN.removeCallbacks(check);
                MAIN.postDelayed(check, 800); // the screenshot app writes the file in steps
            }

            final Runnable check = () -> sendNewScreenshot(context);
        };
        context.getContentResolver().registerContentObserver(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, true, screenshots);
    }

    static void stopWatching(Context context) {
        if (screenshots != null) context.getContentResolver().unregisterContentObserver(screenshots);
        screenshots = null;
    }

    private static void sendNewScreenshot(Context context) {
        if (!on) return;
        String[] cols = {MediaStore.Images.Media._ID, MediaStore.Images.Media.DISPLAY_NAME,
                MediaStore.Images.Media.RELATIVE_PATH, MediaStore.Images.Media.DATE_ADDED};
        String where = MediaStore.Images.Media.DATE_ADDED + " >= ?"
                + (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q ? " AND " + MediaStore.Images.Media.IS_PENDING + " = 0" : "");
        String[] args = {String.valueOf(System.currentTimeMillis() / 1000 - 20)};
        try (Cursor c = context.getContentResolver().query(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, cols, where, args,
                MediaStore.Images.Media.DATE_ADDED + " DESC")) {
            if (c == null || !c.moveToFirst()) return;
            long id = c.getLong(0);
            String name = c.getString(1) == null ? "" : c.getString(1);
            String path = c.getString(2) == null ? "" : c.getString(2);
            boolean screenshot = path.toLowerCase().contains("screenshot") || name.toLowerCase().startsWith("screenshot")
                    || name.startsWith("Sora_");
            if (!screenshot || id == lastScreenshotId || name.equals(skipScreenshot)) return;
            lastScreenshotId = id;
            Uri uri = Uri.withAppendedPath(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, String.valueOf(id));
            byte[] bytes;
            try (InputStream in = context.getContentResolver().openInputStream(uri)) {
                if (in == null) return;
                ByteArrayOutputStream out = new ByteArrayOutputStream();
                byte[] buf = new byte[64 * 1024];
                for (int n; (n = in.read(buf)) > 0; ) out.write(buf, 0, n);
                bytes = out.toByteArray();
            }
            Map<String, Object> shot = new HashMap<>();
            shot.put("name", name);
            shot.put("bytes", bytes);
            deliver("screenshot", shot);
        } catch (Exception ignored) {
            // no photos permission yet, or the file went away
        }
    }
}
