package com.yeasir.sora_phone;

import android.app.Activity;
import android.os.Bundle;

/**
 * An invisible screen, open for a moment after the owner taps "Copy": Android lets only the app in
 * front read the clipboard, so this reads it as soon as it has the focus and closes.
 */
public class ClipReaderActivity extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().getDecorView().postDelayed(this::finish, 1500); // in case the focus never comes
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (!hasFocus) return;
        try {
            SoraClip.readNow(getApplicationContext());
        } finally {
            finish();
            overridePendingTransition(0, 0);
        }
    }
}
