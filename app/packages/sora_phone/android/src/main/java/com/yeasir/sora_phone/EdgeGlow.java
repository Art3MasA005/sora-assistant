package com.yeasir.sora_phone;

import android.accessibilityservice.AccessibilityService;
import android.content.Context;
import android.graphics.BlurMaskFilter;
import android.graphics.Canvas;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.PixelFormat;
import android.graphics.RectF;
import android.graphics.SweepGradient;
import android.os.Build;
import android.os.SystemClock;
import android.view.RoundedCorner;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowManager;

/**
 * Sora's glow around the screen's edge, like Siri's, while the owner talks with it hands-free ("Hey
 * Sora"): colours flowing round the rounded edge, breathing with the voice while Sora listens,
 * swirling faster while it thinks, pulsing while it speaks.
 *
 * <p>Drawn over every app as an accessibility overlay (no extra permission; needs Sora on in
 * Accessibility, like screenshots), touches pass through it. It exists only during a conversation:
 * added when one starts, animating while shown, removed when it ends, so it costs nothing otherwise.
 * Main thread only (the plugin's method calls arrive there).
 */
final class EdgeGlow {
    private static EdgeGlow current;

    private final WindowManager windows;
    private final GlowView view;
    private boolean leaving;

    private EdgeGlow(AccessibilityService service) {
        windows = (WindowManager) service.getSystemService(Context.WINDOW_SERVICE);
        view = new GlowView(service);
        WindowManager.LayoutParams lp = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
                        | WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
                PixelFormat.TRANSLUCENT);
        if (Build.VERSION.SDK_INT >= 30) {
            lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
        } else if (Build.VERSION.SDK_INT >= 28) {
            lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
        }
        lp.setTitle("Sora glow");
        view.setAlpha(0f);
        windows.addView(view, lp);
        view.animate().alpha(1f).setDuration(260).start();
    }

    /**
     * [state]: "listening", "thinking", "speaking", or "off". [level]: the voice's loudness, 0..1, while
     * listening. False when it can't be shown (Sora is off in Accessibility).
     */
    static boolean set(String state, double level) {
        if (state == null || state.equals("off")) {
            off();
            return true;
        }
        AccessibilityService service = SoraAccessibilityService.instance;
        if (service == null) return false;
        try {
            if (current == null || current.leaving) {
                if (current != null) current.remove();
                current = new EdgeGlow(service);
            }
            current.view.update(state, (float) level);
            return true;
        } catch (RuntimeException e) { // the overlay was refused (the service is going away)
            current = null;
            return false;
        }
    }

    /** Fades out and goes. */
    static void off() {
        EdgeGlow glow = current;
        if (glow == null || glow.leaving) return;
        glow.leaving = true;
        glow.view.animate().alpha(0f).setDuration(320).withEndAction(() -> {
            glow.remove();
            if (current == glow) current = null;
        }).start();
    }

    /** At once (the accessibility service stopped). */
    static void gone() {
        if (current != null) current.remove();
        current = null;
    }

    private void remove() {
        view.running = false;
        try {
            windows.removeView(view);
        } catch (RuntimeException ignored) {
            // already gone with the service
        }
    }

    private static final class GlowView extends View {
        // Blue, violet, pink, orange, cyan and round to blue again: the sweep is seamless.
        private static final int[] COLORS = {0xFF4F7BFF, 0xFF9B5CFF, 0xFFFF5CA8, 0xFFFFA24A, 0xFF4FD8FF, 0xFF4F7BFF};

        private final float dp;
        private final Paint haze = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint glow = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Matrix turn = new Matrix();
        private final RectF edge = new RectF();
        private SweepGradient sweep;
        private float radius;
        private String state = "listening";
        private float target, level, angle, pulse;
        private long lastFrame;
        boolean running = true;

        GlowView(Context context) {
            super(context);
            dp = context.getResources().getDisplayMetrics().density;
            for (Paint p : new Paint[] {haze, glow, line}) p.setStyle(Paint.Style.STROKE);
            // Blurred strokes need hardware drawing that supports BlurMaskFilter (Android 9+); older
            // phones get the same look from wider, fainter strokes.
            if (Build.VERSION.SDK_INT >= 28) {
                haze.setMaskFilter(new BlurMaskFilter(28 * dp, BlurMaskFilter.Blur.NORMAL));
                glow.setMaskFilter(new BlurMaskFilter(10 * dp, BlurMaskFilter.Blur.NORMAL));
            }
            line.setStrokeWidth(2.5f * dp);
            radius = 36 * dp; // phones without the corner's real radius (Android 12+ tells it)
        }

        void update(String next, float voice) {
            state = next;
            target = Math.max(0f, Math.min(1f, voice));
            if (lastFrame == 0) {
                lastFrame = SystemClock.uptimeMillis();
                postInvalidateOnAnimation();
            }
        }

        @Override
        protected void onSizeChanged(int w, int h, int oldw, int oldh) {
            sweep = new SweepGradient(w / 2f, h / 2f, COLORS, null);
            for (Paint p : new Paint[] {haze, glow, line}) p.setShader(sweep);
            if (Build.VERSION.SDK_INT >= 31) {
                WindowInsets insets = getRootWindowInsets();
                RoundedCorner corner = insets == null ? null : insets.getRoundedCorner(RoundedCorner.POSITION_TOP_LEFT);
                if (corner != null && corner.getRadius() > 0) radius = corner.getRadius();
            }
            edge.set(0, 0, w, h);
        }

        @Override
        protected void onDraw(Canvas canvas) {
            if (!running || sweep == null) return;
            long now = SystemClock.uptimeMillis();
            float dt = Math.min(0.05f, (now - lastFrame) / 1000f);
            lastFrame = now;

            // How fast the colours go round (degrees a second) and how the glow breathes, by state.
            float speed;
            float strength;
            pulse += dt;
            switch (state) {
                case "thinking":
                    speed = 260;
                    strength = 0.55f + 0.15f * (float) Math.sin(pulse * 2 * Math.PI * 0.9);
                    break;
                case "speaking":
                    speed = 120;
                    strength = 0.7f + 0.3f * (float) Math.abs(Math.sin(pulse * 2 * Math.PI * 1.6));
                    break;
                default: // listening: follows the voice
                    level += (target - level) * Math.min(1f, dt * 12);
                    speed = 80 + 160 * level;
                    strength = 0.5f + 0.5f * level;
            }
            angle = (angle + speed * dt) % 360;
            turn.setRotate(angle, getWidth() / 2f, getHeight() / 2f);
            sweep.setLocalMatrix(turn);

            boolean blur = Build.VERSION.SDK_INT >= 28;
            haze.setStrokeWidth((blur ? 34 : 22) * dp * (0.75f + 0.5f * strength));
            haze.setAlpha((int) (255 * (blur ? 0.55f : 0.22f) * strength));
            glow.setStrokeWidth((blur ? 12 : 8) * dp * (0.8f + 0.4f * strength));
            glow.setAlpha((int) (255 * (blur ? 0.85f : 0.45f) * strength));
            line.setAlpha((int) (255 * (0.6f + 0.4f * strength)));
            // The strokes are centred on the screen's edge: the half inside shows, glowing inwards.
            canvas.drawRoundRect(edge, radius, radius, haze);
            canvas.drawRoundRect(edge, radius, radius, glow);
            canvas.drawRoundRect(edge, radius, radius, line);
            postInvalidateOnAnimation();
        }
    }
}
