package com.yeasir.sora_phone;

import android.accessibilityservice.AccessibilityService;
import android.content.ContentValues;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.view.Display;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import java.io.OutputStream;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.Executor;

/**
 * Turned on by the owner in Settings → Accessibility → Sora. Sora uses it to take screenshots, lock
 * the screen and go home; it remembers which app is in front (to "close" it) and, with clipboard sync
 * on, notices taps on "Copy" and new screenshots ({@link SoraClip}). The one screen it reads is
 * WhatsApp's, for a few seconds after the owner approved a WhatsApp message, to tap its Send button
 * ({@link #tapSend}). While it is on it also keeps the phone connected to the PC's Sora with the app
 * closed ({@link SoraLink}).
 */
public class SoraAccessibilityService extends AccessibilityService {
    static volatile SoraAccessibilityService instance;
    static volatile String foregroundPackage;

    public interface Done {
        void ok(String result);

        void fail(String message);
    }

    @Override
    protected void onServiceConnected() {
        instance = this;
        SoraClip.watchScreenshots(getApplicationContext());
        SoraLink.start(getApplicationContext());
    }

    @Override
    public boolean onUnbind(android.content.Intent intent) {
        instance = null;
        EdgeGlow.gone();
        SoraClip.stopWatching(getApplicationContext());
        SoraLink.stop();
        return super.onUnbind(intent);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event.getEventType() == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED && event.getPackageName() != null) {
            foregroundPackage = event.getPackageName().toString();
        }
        SoraClip.onEvent(getApplicationContext(), event);
    }

    @Override
    public void onInterrupt() {
    }

    // WhatsApp's Send button, by its view id, else by what TalkBack reads for it (English or Bangla).
    private static final String[] SEND_LABELS = {"send", "পাঠান", "পাঠাও", "প্রেরণ"};

    /**
     * Taps Send once in [pkg]'s chat that was just opened, looking every 300 ms for up to [timeoutMs].
     * Only that app's window is read, and only for this long.
     */
    void tapSend(String pkg, long timeoutMs, Done done) {
        android.os.Handler main = new android.os.Handler(android.os.Looper.getMainLooper());
        long until = android.os.SystemClock.uptimeMillis() + timeoutMs;
        Runnable[] look = new Runnable[1];
        look[0] = () -> {
            AccessibilityNodeInfo root = getRootInActiveWindow();
            if (root != null && root.getPackageName() != null && pkg.contentEquals(root.getPackageName())) {
                AccessibilityNodeInfo send = findSend(root, pkg);
                if (send != null) {
                    if (send.performAction(AccessibilityNodeInfo.ACTION_CLICK)) done.ok("sent");
                    else done.fail("opened the WhatsApp chat with the message, but tapping Send didn't work: tap it on the phone");
                    return;
                }
            }
            if (android.os.SystemClock.uptimeMillis() >= until) {
                done.fail("opened the WhatsApp chat with the message, but couldn't find its Send button: tap Send on the phone");
                return;
            }
            main.postDelayed(look[0], 300);
        };
        main.postDelayed(look[0], 500);
    }

    private static AccessibilityNodeInfo findSend(AccessibilityNodeInfo root, String pkg) {
        for (AccessibilityNodeInfo n : root.findAccessibilityNodeInfosByViewId(pkg + ":id/send")) {
            AccessibilityNodeInfo tappable = tappable(n);
            if (tappable != null) return tappable;
        }
        java.util.ArrayDeque<AccessibilityNodeInfo> queue = new java.util.ArrayDeque<>();
        queue.add(root);
        while (!queue.isEmpty()) {
            AccessibilityNodeInfo n = queue.poll();
            CharSequence d = n.getContentDescription();
            if (d != null && java.util.Arrays.asList(SEND_LABELS).contains(d.toString().trim().toLowerCase(Locale.ROOT))) {
                AccessibilityNodeInfo tappable = tappable(n);
                if (tappable != null) return tappable;
            }
            for (int i = 0; i < n.getChildCount(); i++) {
                AccessibilityNodeInfo child = n.getChild(i);
                if (child != null) queue.add(child);
            }
        }
        return null;
    }

    /** [n] or the nearest parent that takes a tap, if enabled. */
    private static AccessibilityNodeInfo tappable(AccessibilityNodeInfo n) {
        for (AccessibilityNodeInfo at = n; at != null; at = at.getParent()) {
            if (at.isClickable()) return at.isEnabled() ? at : null;
        }
        return null;
    }

    boolean home() {
        return performGlobalAction(GLOBAL_ACTION_HOME);
    }

    boolean lock() {
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.P && performGlobalAction(GLOBAL_ACTION_LOCK_SCREEN);
    }

    /**
     * Takes a screenshot and saves it to Pictures/Sora; reports the saved file's name, or with [send]
     * a JSON {saved, png_base64} so the PC app can show it (then it is not also sent as a clipboard
     * screenshot).
     */
    void screenshot(Done done, boolean send) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            done.fail("screenshots need Android 11 or newer");
            return;
        }
        Executor executor = getMainExecutor();
        takeScreenshot(Display.DEFAULT_DISPLAY, executor, new TakeScreenshotCallback() {
            @Override
            public void onSuccess(ScreenshotResult result) {
                Bitmap bitmap = Bitmap.wrapHardwareBuffer(result.getHardwareBuffer(), result.getColorSpace());
                result.getHardwareBuffer().close();
                if (bitmap == null) {
                    done.fail("could not read the screenshot");
                    return;
                }
                String name = "Sora_" + new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(new Date()) + ".png";
                ContentValues values = new ContentValues();
                values.put(MediaStore.Images.Media.DISPLAY_NAME, name);
                values.put(MediaStore.Images.Media.MIME_TYPE, "image/png");
                values.put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/Sora");
                Uri uri = getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
                if (uri == null) {
                    done.fail("could not save the screenshot");
                    return;
                }
                try (OutputStream out = getContentResolver().openOutputStream(uri)) {
                    java.io.ByteArrayOutputStream png = new java.io.ByteArrayOutputStream();
                    bitmap.copy(Bitmap.Config.ARGB_8888, false).compress(Bitmap.CompressFormat.PNG, 100, png);
                    if (send) SoraClip.skipScreenshot = name;
                    png.writeTo(out);
                    if (!send) {
                        done.ok("saved Pictures/Sora/" + name);
                        return;
                    }
                    org.json.JSONObject json = new org.json.JSONObject();
                    json.put("saved", "Pictures/Sora/" + name);
                    json.put("png_base64", android.util.Base64.encodeToString(png.toByteArray(), android.util.Base64.NO_WRAP));
                    done.ok(json.toString());
                } catch (Exception e) {
                    done.fail("could not save the screenshot: " + e.getMessage());
                }
            }

            @Override
            public void onFailure(int errorCode) {
                done.fail("the phone refused the screenshot (code " + errorCode + ")");
            }
        });
    }
}
