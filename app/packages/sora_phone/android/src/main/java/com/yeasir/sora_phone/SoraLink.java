package com.yeasir.sora_phone;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.net.ConnectivityManager;
import android.net.LinkAddress;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.URI;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import io.flutter.plugin.common.MethodChannel;
import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;

/**
 * The phone's line to the Sora server, app open or closed, like Windows' Phone Link: it lives in
 * Sora's accessibility service (which Android keeps running while it is on), so there is no
 * notification, no mic and no Flutter engine — one idle WebSocket.
 *
 * <ul>
 *   <li>Commands from the server ("open YouTube on my phone" said on the PC, the PC's clipboard) are
 *   run by {@link SoraPhonePlugin} as the app would run them.</li>
 *   <li>What the owner copies, and new screenshots, go straight to the server ({@link SoraClip}).</li>
 *   <li>Connecting with no delay: the PC's Sora says "I'm on" over UDP (port {@link #ANNOUNCE_PORT})
 *   when it starts, wakes from sleep, and now and then while this phone isn't connected; this
 *   connects the moment it hears it. A dropped line is retried at once, then less often (a minute
 *   at most); Wi-Fi coming back and the screen coming on retry at once too. Away from the home Wi-Fi
 *   (a server on a home address) it doesn't try at all.</li>
 *   <li>The PC got a new address from the router: it says so in the same hello, or after a few
 *   misses this looks for it on the Wi-Fi.</li>
 *   <li>The battery level goes to the server (for "battery below N%" routines) from the system's
 *   battery broadcast, only when the percentage or charging changes, and once per connection.</li>
 * </ul>
 * While connected it shows a quiet "Connected to <PC>" notification ({@link LinkNotification}) whose
 * Disconnect keeps it off until Connect (there, or in the app's Settings).
 * The app gives it the server address and the device token ({@code link} on the plugin channel).
 * While it runs, the app and the "Hey Sora" service don't open their own line (one per device:
 * a second one would replace the first).
 */
final class SoraLink {
    private static final String TAG = "SoraLink";
    static final int ANNOUNCE_PORT = 48765;
    private static final String PREFS = "sora_link";
    private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");
    private static final long[] RETRY_MS = {300, 1000, 2000, 4000, 8000, 15000, 30000, 60000};

    private static SoraLink current;

    static synchronized void start(Context context) {
        if (current == null) current = new SoraLink(context.getApplicationContext());
        current.begin();
    }

    static synchronized void stop() {
        if (current != null) current.end();
        current = null;
    }

    /** From the app: where the server is and this phone's token (nulls: signed out). */
    static void configure(Context context, String server, String token) {
        String base = server == null ? null : server.replaceAll("/+$", "");
        SharedPreferences p = prefs(context);
        boolean same = Objects.equals(p.getString("server", null), base) && Objects.equals(p.getString("token", null), token);
        if (!same) {
            SharedPreferences.Editor e = p.edit();
            if (base == null || token == null) e.remove("server").remove("token");
            else e.putString("server", base).putString("token", token);
            e.commit(); // read back at once by the line's thread
        }
        SoraLink link;
        synchronized (SoraLink.class) {
            link = current;
        }
        if (link == null) return;
        if (same) link.soon(); // the app opened: nothing new, but no harm in trying now if down
        else link.restart();
    }

    /** The app's language, for the notification. */
    static void setBangla(Context context, boolean bangla) {
        if (prefs(context).getBoolean("bangla", false) == bangla) return;
        prefs(context).edit().putBoolean("bangla", bangla).commit();
        refreshNotification();
    }

    static boolean paused(Context context) {
        return prefs(context).getBoolean("paused", false);
    }

    /** Disconnect / Connect (the notification's button or the app's Settings). */
    static void setPaused(Context context, boolean paused) {
        prefs(context).edit().putBoolean("paused", paused).commit();
        SoraLink link = current;
        if (paused) {
            if (link != null) {
                link.handler.post(() -> {
                    link.handler.removeCallbacks(link.connectTask);
                    link.handler.removeCallbacks(link.goneTask);
                    link.drop();
                });
            }
            LinkNotification.paused(context);
        } else {
            LinkNotification.cancel(context);
            if (link != null) link.soon();
        }
    }

    /** The notification again as things stand (it was switched on, or the language changed). */
    static void refreshNotification() {
        SoraLink link = current;
        if (link == null) return;
        if (link.open) LinkNotification.stillConnected(link.context, link.pcName);
        else if (paused(link.context)) LinkNotification.paused(link.context);
    }

    /** The line is up right now. */
    static boolean online() {
        SoraLink link = current;
        return link != null && link.open;
    }

    /** True while this line runs signed in: the app and the "Hey Sora" service then leave it to it. */
    static boolean active() {
        SoraLink link = current;
        return link != null && link.running && link.server() != null && link.token() != null;
    }

    /** A message for the server over the open line (a phone notification); dropped when the line is down. */
    static void sendEvent(String json) {
        SoraLink link = current;
        if (link == null) return;
        link.handler.post(() -> {
            if (link.open && link.ws != null) link.ws.send(json);
        });
    }

    /** Sends a copy or a screenshot to the server; false when there is no line set up (signed out). */
    static boolean sendClip(String method, Object args) {
        SoraLink link = current;
        if (link == null || link.token() == null) return false;
        if (paused(link.context)) return true; // disconnected by the owner: not shared
        link.http.dispatcher().executorService().execute(() -> link.postClip(method, args));
        return true;
    }

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    // ------------------------------------------------------------------ the line

    private final Context context;
    private final OkHttpClient http;
    private final HandlerThread thread = new HandlerThread("sora-link");
    private final Handler handler;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService scanner = Executors.newCachedThreadPool();
    private final Runnable connectTask = this::connect;
    // the notification goes a moment after the line drops, unless it is back by then (a restart)
    private final Runnable goneTask = () -> LinkNotification.gone(contextOf());
    private volatile String pcName = "";
    // Touched on the line's thread only, except the volatile ones.
    private WebSocket ws;
    private long connectingSince;
    private int failures;
    private long scanAllowedAt;
    private volatile boolean running, open;
    private volatile String epoch; // the server run this line is connected to (from its hello)
    private DatagramSocket announcements;
    private ConnectivityManager.NetworkCallback networkCallback;
    private BroadcastReceiver screenOn;
    private BroadcastReceiver battery;
    // The battery as the phone last said and as the server last heard it (the line's thread).
    private int batteryLevel = -1, sentLevel = -1;
    private boolean charging, sentCharging;

    private SoraLink(Context context) {
        this.context = context;
        http = new OkHttpClient.Builder()
                .connectTimeout(4, TimeUnit.SECONDS)
                .readTimeout(60, TimeUnit.SECONDS)
                .pingInterval(30, TimeUnit.SECONDS) // a PC that vanished without closing is noticed
                .build();
        thread.start();
        handler = new Handler(thread.getLooper());
        SoraClip.on = prefs(context).getBoolean("clipboard_on", SoraClip.on);
    }

    private Context contextOf() {
        return context;
    }

    private String server() {
        return prefs(context).getString("server", null);
    }

    private String token() {
        return prefs(context).getString("token", null);
    }

    private void begin() {
        if (running) return;
        running = true;
        listenForAnnouncements();
        watchNetwork();
        watchScreen();
        watchBattery();
        handler.post(connectTask);
    }

    private void end() {
        running = false;
        handler.removeCallbacksAndMessages(null);
        handler.post(() -> {
            drop();
            thread.quitSafely();
        });
        if (!paused(context)) LinkNotification.gone(context);
        DatagramSocket socket = announcements;
        announcements = null;
        if (socket != null) socket.close();
        try {
            if (networkCallback != null) context.getSystemService(ConnectivityManager.class).unregisterNetworkCallback(networkCallback);
        } catch (Exception ignored) {
            // already gone
        }
        try {
            if (screenOn != null) context.unregisterReceiver(screenOn);
        } catch (Exception ignored) {
            // already gone
        }
        try {
            if (battery != null) context.unregisterReceiver(battery);
        } catch (Exception ignored) {
            // already gone
        }
        networkCallback = null;
        screenOn = null;
        battery = null;
        scanner.shutdownNow();
    }

    /** Forgets the current connection (cancel: a dead one would wait for its timeout to close). */
    private void drop() {
        if (ws != null) ws.cancel();
        ws = null;
        open = false;
        epoch = null;
    }

    /** New address or token: drop the line and connect again now. */
    private void restart() {
        handler.post(() -> {
            drop();
            failures = 0;
            handler.removeCallbacks(connectTask);
            connect();
        });
    }

    /** Try now if the line is down (Wi-Fi came back, the screen came on, the app opened). */
    private void soon() {
        handler.post(() -> {
            if (ws != null) return; // up, or connecting
            failures = 0;
            handler.removeCallbacks(connectTask);
            connect();
        });
    }

    /** The server said "I'm on" (it started, or the PC woke up): connect now unless already on that run. */
    private void heard(String helloEpoch) {
        handler.post(() -> {
            if (open && helloEpoch != null && helloEpoch.equals(epoch)) return; // fine as it is
            if (!open && ws != null && System.currentTimeMillis() - connectingSince < 1500) return; // on its way
            drop(); // connecting to nothing, or a line from before the PC slept
            failures = 0;
            handler.removeCallbacks(connectTask);
            connect();
        });
    }

    private void connect() {
        if (!running || ws != null) return;
        String server = server(), token = token();
        if (server == null || token == null) return; // the app hasn't signed in yet
        if (paused(context)) return; // the owner tapped Disconnect
        if (!reachableFromHere(server)) return; // away from home: Wi-Fi coming back will call soon()
        connectingSince = System.currentTimeMillis();
        Request req = new Request.Builder()
                .url(server.replaceFirst("^http", "ws") + "/ws")
                .header("Authorization", "Bearer " + token)
                .build();
        ws = http.newWebSocket(req, new Listener());
    }

    /** A server at a home (private) address can only be reached on Wi-Fi or Ethernet. */
    private boolean reachableFromHere(String server) {
        try {
            InetAddress host = InetAddress.getByName(URI.create(server).getHost()); // a literal: no lookup
            if (!(host.isSiteLocalAddress() || host.isLinkLocalAddress())) return true;
        } catch (Exception e) {
            return true; // a name: let the connection find out
        }
        ConnectivityManager cm = context.getSystemService(ConnectivityManager.class);
        if (cm == null) return true;
        for (Network n : cm.getAllNetworks()) { // Wi-Fi with no internet may not be the default network
            NetworkCapabilities caps = cm.getNetworkCapabilities(n);
            if (caps != null && (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
                    || caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET))) return true;
        }
        return false;
    }

    private void lost(WebSocket from, boolean byServer) {
        handler.post(() -> {
            if (ws != from) return; // already replaced
            ws = null;
            open = false;
            epoch = null;
            if (!running) return;
            long delay = byServer && failures == 0 ? 0 : RETRY_MS[Math.min(failures, RETRY_MS.length - 1)];
            failures++;
            handler.removeCallbacks(goneTask);
            if (!paused(context)) handler.postDelayed(goneTask, 4000);
            if (failures >= 4 && System.currentTimeMillis() >= scanAllowedAt) {
                scanAllowedAt = System.currentTimeMillis() + 5 * 60_000;
                scanner.execute(this::scanWifi);
            }
            handler.postDelayed(connectTask, delay);
        });
    }

    private final class Listener extends WebSocketListener {
        @Override
        public void onOpen(WebSocket socket, Response response) {
            handler.post(() -> {
                if (ws != socket) return;
                open = true;
                failures = 0;
                sentLevel = -1; // a new line: tell this server run where the battery is
                sendBattery();
            });
            Log.i(TAG, "connected to " + server());
            try {
                socket.send(new JSONObject()
                        .put("type", "info")
                        .put("model", Build.MANUFACTURER + " " + Build.MODEL)
                        .put("link", "background")
                        .toString());
            } catch (Exception ignored) {
                // just the description
            }
            http.dispatcher().executorService().execute(SoraLink.this::loadClipboardSetting);
        }

        @Override
        public void onMessage(WebSocket socket, String text) {
            try {
                JSONObject msg = new JSONObject(text);
                switch (msg.optString("type")) {
                    case "hello":
                        epoch = msg.optString("epoch", null);
                        pcName = msg.optString("server", "");
                        handler.post(() -> {
                            if (ws != socket) return;
                            handler.removeCallbacks(goneTask);
                            LinkNotification.connected(context, pcName);
                        });
                        break;
                    case "ping":
                        socket.send("{\"type\":\"pong\"}");
                        break;
                    case "command":
                        run(socket, msg.optString("id", null), msg.optString("action"), msg.optJSONObject("params"));
                        break;
                    case "device_status": // the PC came online or went away: the open app's Devices screen shows it
                        SoraClip.toApps("event", text);
                        break;
                    default:
                        break; // events for the app's screens
                }
            } catch (Exception e) {
                Log.w(TAG, "bad message: " + e);
            }
        }

        @Override
        public void onClosing(WebSocket socket, int code, String reason) {
            if (code == 4401 || code == 4001) prefs(context).edit().remove("token").apply(); // signed out on the server
            socket.close(1000, null);
        }

        @Override
        public void onClosed(WebSocket socket, int code, String reason) {
            lost(socket, true); // the server restarting or the PC waking: straight back
        }

        @Override
        public void onFailure(WebSocket socket, Throwable t, Response response) {
            lost(socket, false);
        }
    }

    /** Runs a command the server sent, as the app would, and answers it. */
    private void run(WebSocket socket, String id, String action, JSONObject params) {
        Map<String, Object> p = params == null ? new HashMap<>() : toMap(params);
        if ("clipboard_sync".equals(action)) rememberClipboard(Boolean.TRUE.equals(p.get("on")));
        main.post(() -> new SoraPhonePlugin(context).runFor(action, p, new MethodChannel.Result() {
            @Override
            public void success(Object result) {
                reply(socket, id, true, result, null);
            }

            @Override
            public void error(String code, String message, Object details) {
                reply(socket, id, false, null, message == null ? code : message);
            }

            @Override
            public void notImplemented() {
                reply(socket, id, false, null, "this phone can't do " + action + " yet");
            }
        }));
    }

    private static void reply(WebSocket socket, String id, boolean ok, Object data, String error) {
        try {
            JSONObject r = new JSONObject().put("type", "result").put("id", id).put("ok", ok);
            if (ok) r.put("data", data == null ? JSONObject.NULL : data);
            else r.put("error", error);
            socket.send(r.toString());
        } catch (Exception ignored) {
            // the line went away; the server times the command out
        }
    }

    private static Map<String, Object> toMap(JSONObject o) {
        Map<String, Object> m = new HashMap<>();
        for (Iterator<String> keys = o.keys(); keys.hasNext(); ) {
            String k = keys.next();
            m.put(k, plain(o.opt(k)));
        }
        return m;
    }

    private static Object plain(Object v) {
        if (v == JSONObject.NULL) return null;
        if (v instanceof JSONObject) return toMap((JSONObject) v);
        if (v instanceof JSONArray) {
            JSONArray a = (JSONArray) v;
            List<Object> list = new ArrayList<>();
            for (int i = 0; i < a.length(); i++) list.add(plain(a.opt(i)));
            return list;
        }
        return v;
    }

    // ------------------------------------------------------------------ clipboard

    private void rememberClipboard(boolean on) {
        SoraClip.on = on;
        prefs(context).edit().putBoolean("clipboard_on", on).apply();
    }

    private void loadClipboardSetting() {
        String server = server(), token = token();
        if (server == null || token == null) return;
        Request req = new Request.Builder().url(server + "/api/clipboard/settings")
                .header("Authorization", "Bearer " + token).build();
        try (Response res = http.newCall(req).execute()) {
            if (res.isSuccessful() && res.body() != null) {
                rememberClipboard(new JSONObject(res.body().string()).optBoolean("enabled", false));
            }
        } catch (Exception ignored) {
            // keep the last known setting
        }
    }

    @SuppressWarnings("unchecked")
    private void postClip(String method, Object args) {
        String server = server(), token = token();
        if (server == null || token == null) return;
        Request.Builder req = new Request.Builder().header("Authorization", "Bearer " + token);
        try {
            if ("clipboard".equals(method)) {
                req.url(server + "/api/clipboard")
                        .post(RequestBody.create(new JSONObject().put("text", args).toString(), JSON));
            } else {
                Map<String, Object> shot = (Map<String, Object>) args;
                String name = String.valueOf(shot.get("name"));
                req.url(server + "/api/clipboard/image").post(new MultipartBody.Builder()
                        .setType(MultipartBody.FORM)
                        .addFormDataPart("name", name)
                        .addFormDataPart("image", name, RequestBody.create((byte[]) shot.get("bytes"), MediaType.get("image/png")))
                        .build());
            }
            try (Response ignored = http.newCall(req.build()).execute()) {
                // sent (or the server said no: sync off) — nothing to do either way
            }
        } catch (Exception e) {
            Log.i(TAG, "copy not sent: " + e); // away from home
        }
    }

    // ------------------------------------------------------------------ hearing and finding the server

    /** The PC's Sora says "I'm on" (UDP): connect now, to its new address if it moved. */
    private void listenForAnnouncements() {
        Thread t = new Thread(() -> {
            try (DatagramSocket socket = new DatagramSocket(null)) {
                socket.setReuseAddress(true); // a line from a moment ago may still hold the port
                socket.bind(new InetSocketAddress(ANNOUNCE_PORT));
                announcements = socket;
                byte[] buf = new byte[512];
                while (running) {
                    DatagramPacket packet = new DatagramPacket(buf, buf.length);
                    socket.receive(packet); // blocks: costs nothing while waiting
                    JSONObject hello;
                    try {
                        hello = new JSONObject(new String(packet.getData(), 0, packet.getLength(), "UTF-8"));
                    } catch (Exception e) {
                        continue;
                    }
                    if (!"sora".equals(hello.optString("name")) || token() == null) continue;
                    String url = "http://" + packet.getAddress().getHostAddress() + ":" + hello.optInt("port", 8000);
                    String helloEpoch = hello.optString("epoch", null);
                    if (url.equals(server())) {
                        heard(helloEpoch);
                    } else {
                        scanner.execute(() -> {
                            if (isOurServer(url)) adopt(url);
                        });
                    }
                }
            } catch (Exception e) {
                if (running) Log.i(TAG, "not listening for the PC: " + e);
            }
        }, "sora-announce");
        t.setDaemon(true);
        t.start();
    }

    /** Wi-Fi (or any network) is back: try now instead of waiting out the pause. */
    private void watchNetwork() {
        ConnectivityManager cm = context.getSystemService(ConnectivityManager.class);
        if (cm == null) return;
        networkCallback = new ConnectivityManager.NetworkCallback() {
            @Override
            public void onAvailable(Network network) {
                soon();
            }
        };
        try {
            cm.registerDefaultNetworkCallback(networkCallback);
        } catch (Exception e) {
            networkCallback = null;
        }
    }

    /** The owner picked the phone up: if the line is down, try now (it may have slept through a retry). */
    private void watchScreen() {
        screenOn = new BroadcastReceiver() {
            @Override
            public void onReceive(Context c, Intent intent) {
                soon();
            }
        };
        IntentFilter f = new IntentFilter(Intent.ACTION_SCREEN_ON);
        f.addAction(Intent.ACTION_USER_PRESENT);
        try {
            if (Build.VERSION.SDK_INT >= 33) context.registerReceiver(screenOn, f, Context.RECEIVER_NOT_EXPORTED);
            else context.registerReceiver(screenOn, f);
        } catch (Exception e) {
            screenOn = null;
        }
    }

    /** The system's sticky battery broadcast: its current value right away, then each change. */
    private void watchBattery() {
        battery = new BroadcastReceiver() {
            @Override
            public void onReceive(Context c, Intent intent) {
                int level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
                int scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, 100);
                if (level < 0 || scale <= 0) return;
                int percent = Math.round(level * 100f / scale);
                boolean plugged = intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0;
                handler.post(() -> {
                    batteryLevel = percent;
                    charging = plugged;
                    sendBattery();
                });
            }
        };
        IntentFilter f = new IntentFilter(Intent.ACTION_BATTERY_CHANGED);
        try {
            if (Build.VERSION.SDK_INT >= 33) context.registerReceiver(battery, f, Context.RECEIVER_NOT_EXPORTED);
            else context.registerReceiver(battery, f);
        } catch (Exception e) {
            battery = null;
        }
    }

    /** On the line's thread. The broadcast also comes for voltage and temperature: only a new percentage
     * or plugging in/out is sent. */
    private void sendBattery() {
        if (!open || ws == null || batteryLevel < 0) return;
        if (batteryLevel == sentLevel && charging == sentCharging) return;
        try {
            String status = new JSONObject().put("type", "status").put("battery", batteryLevel).put("charging", charging).toString();
            if (ws.send(status)) {
                sentLevel = batteryLevel;
                sentCharging = charging;
            }
        } catch (Exception ignored) {
            // the line went away: sent again when it is back
        }
    }

    /** Sora answers at [base] and accepts this phone's token. */
    private boolean isOurServer(String base) {
        OkHttpClient quick = http.newBuilder().connectTimeout(700, TimeUnit.MILLISECONDS).readTimeout(4, TimeUnit.SECONDS)
                .pingInterval(0, TimeUnit.SECONDS).build();
        try (Response health = quick.newCall(new Request.Builder().url(base + "/api/health").build()).execute()) {
            if (!health.isSuccessful() || health.body() == null) return false;
            if (!"sora".equals(new JSONObject(health.body().string()).optString("name"))) return false;
        } catch (Exception e) {
            return false;
        }
        String token = token();
        if (token == null) return false;
        try (Response me = quick.newCall(new Request.Builder().url(base + "/api/me")
                .header("Authorization", "Bearer " + token).build()).execute()) {
            return me.isSuccessful();
        } catch (Exception e) {
            return false;
        }
    }

    private void adopt(String url) {
        if (url.equals(server())) return;
        Log.i(TAG, "server now at " + url);
        configure(context, url, token());
    }

    /** The PC got a new address from the router: look at every address on this Wi-Fi. */
    private void scanWifi() {
        ConnectivityManager cm = context.getSystemService(ConnectivityManager.class);
        if (cm == null) return;
        // The Wi-Fi itself, not the default network: with a VPN on (1.1.1.1, a work VPN) that is the
        // VPN, and the scan used to give up there.
        InetAddress mine = null;
        for (Network n : cm.getAllNetworks()) {
            NetworkCapabilities caps = cm.getNetworkCapabilities(n);
            LinkProperties props = cm.getLinkProperties(n);
            if (caps == null || props == null || !caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
                    || caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) continue;
            for (LinkAddress a : props.getLinkAddresses()) {
                if (a.getAddress() instanceof Inet4Address) mine = a.getAddress();
            }
            if (mine != null) break;
        }
        if (mine == null) return;
        byte[] ip = mine.getAddress();
        String prefix = (ip[0] & 255) + "." + (ip[1] & 255) + "." + (ip[2] & 255) + ".";
        int port = 8000;
        try {
            String saved = server();
            if (saved != null && URI.create(saved).getPort() > 0) port = URI.create(saved).getPort();
        } catch (Exception ignored) {
            // keep 8000
        }
        ExecutorService pool = Executors.newFixedThreadPool(32);
        AtomicReference<String> found = new AtomicReference<>();
        List<Future<?>> jobs = new ArrayList<>();
        for (int host = 1; host < 255; host++) {
            if (host == (ip[3] & 255)) continue;
            String addr = prefix + host;
            String base = "http://" + addr + ":" + port;
            int p = port;
            jobs.add(pool.submit(() -> {
                if (found.get() == null && portOpen(addr, p) && isOurServer(base)) found.compareAndSet(null, base);
            }));
        }
        for (Future<?> j : jobs) {
            try {
                j.get();
            } catch (Exception ignored) {
                // that address didn't answer
            }
        }
        pool.shutdown();
        String url = found.get();
        if (url != null) adopt(url);
    }

    private static boolean portOpen(String host, int port) {
        try (java.net.Socket s = new java.net.Socket()) {
            s.connect(new InetSocketAddress(host, port), 500);
            return true;
        } catch (Exception e) {
            return false;
        }
    }
}
