package com.devco.field;

import android.app.Activity;
import android.os.Bundle;
import android.view.Window;
import android.content.Intent;
import android.net.Uri;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebChromeClient;
import android.webkit.GeolocationPermissions;
import android.Manifest;
import android.content.pm.PackageManager;
import android.widget.Toast;
import android.os.Handler;

public class MainActivity extends Activity {
    private WebView web;
    private VoiceCloseout voice;
    private final Handler hostHandler = new Handler();
    private boolean foreground = false, probing = false, backendLoaded = false;
    private boolean commandPermissionRequested = false;
    private long lastStartAttempt = 0;
    private final Runnable hostMonitor = new Runnable() {
        @Override public void run() {
            if (foreground) { checkBackend(); hostHandler.postDelayed(this, 5000); }
        }
    };
    private String pendingGeoOrigin;
    private GeolocationPermissions.Callback pendingGeoCallback;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        web = new WebView(this);
        web.setWebViewClient(new WebViewClient() {
            private boolean handle(Uri uri) {
                if (uri == null) return false;
                if (voice != null && voice.handle(uri)) return true;
                String scheme = uri.getScheme();
                String host = uri.getHost();

                // Launch from the foreground Activity, not the background Termux host.
                if ("http".equals(scheme) && "127.0.0.1".equals(host)
                        && uri.getPort() == 8765 && "/camera".equals(uri.getPath())) {
                    openSolocator();
                    return true;
                }

                // DEVCO local /nav links are converted here into a native
                // Google Maps navigation intent. This works even when Maps
                // is already open.
                if (("http".equals(scheme) || "https".equals(scheme))
                        && "127.0.0.1".equals(host)
                        && "/nav".equals(uri.getPath())) {
                    String lat = uri.getQueryParameter("lat");
                    String lon = uri.getQueryParameter("lon");
                    if (lat != null && lon != null) {
                        openGoogleMaps(lat, lon);
                    }
                    return true;
                }

                // Never trap Google/geo navigation links inside the WebView.
                if ("geo".equals(scheme) || "google.navigation".equals(scheme)
                        || (host != null && (host.equals("maps.google.com")
                        || host.equals("www.google.com") && uri.getPath() != null
                        && uri.getPath().startsWith("/maps")))) {
                    try {
                        startActivity(new Intent(Intent.ACTION_VIEW, uri));
                    } catch (Exception e) {
                        Toast.makeText(MainActivity.this, "Unable to open Maps", Toast.LENGTH_SHORT).show();
                    }
                    return true;
                }
                return false;
            }

            @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap icon) {
                if (voice != null) voice.cancel(false);
            }

            @Override public void onPageFinished(WebView view, String url) {
                if (VoiceCloseout.isBilling(url) && url.equals(view.getUrl())) {
                    view.loadUrl("javascript:window.devcoVoiceReady&&window.devcoVoiceReady()");
                }
            }

            @Override public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handle(Uri.parse(url));
            }

            @Override public void onReceivedError(WebView view, int code, String description, String failingUrl) {
                if (failingUrl != null && failingUrl.startsWith("http://127.0.0.1:8765")
                        && (failingUrl.equals(view.getUrl()) || failingUrl.equals("http://127.0.0.1:8765/"))) {
                    backendLoaded = false;
                    showConnecting();
                    startBackend();
                }
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
                if (android.os.Build.VERSION.SDK_INT < 23 ||
                        getPackageManager().checkPermission(Manifest.permission.ACCESS_FINE_LOCATION, getPackageName()) == PackageManager.PERMISSION_GRANTED) {
                    callback.invoke(origin, true, false);
                } else {
                    pendingGeoOrigin = origin;
                    pendingGeoCallback = callback;
                    requestLocationPermission();
                }
            }
        });
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setGeolocationEnabled(true);
        voice = new VoiceCloseout(this, web);
        setContentView(web);
        showConnecting();
    }


    private void showConnecting() {
        web.loadDataWithBaseURL(null, "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
                + "<body style='background:#101820;color:white;font-family:sans-serif;padding:32px'>"
                + "<h2>Connecting to DEVCO</h2><p>Starting your field workspace. This page reconnects automatically.</p>"
                + "<p>If Android asks, allow DEVCO to run commands in Termux.</p></body></html>", "text/html", "UTF-8", null);
    }

    private void checkBackend() {
        if (probing || !foreground) return;
        probing = true;
        new Thread(new Runnable() {
            @Override public void run() {
                boolean ready = false;
                java.net.HttpURLConnection connection = null;
                try {
                    connection = (java.net.HttpURLConnection) new java.net.URL("http://127.0.0.1:8765/health").openConnection();
                    connection.setConnectTimeout(2000);
                    connection.setReadTimeout(2000);
                    connection.setUseCaches(false);
                    if (connection.getResponseCode() == 200) {
                        java.io.BufferedReader reader = new java.io.BufferedReader(new java.io.InputStreamReader(connection.getInputStream(), "UTF-8"));
                        String body = reader.readLine();
                        reader.close();
                        String compact = body == null ? "" : body.replaceAll("\\s+", "");
                        ready = compact.contains("\"service\":\"devco-field\"") && compact.contains("\"ready\":true");
                    }
                } catch (Exception ignored) {
                } finally {
                    if (connection != null) connection.disconnect();
                }
                final boolean healthy = ready;
                hostHandler.post(new Runnable() {
                    @Override public void run() {
                        probing = false;
                        if (!foreground) return;
                        if (healthy) {
                            if (!backendLoaded) {
                                backendLoaded = true;
                                web.loadUrl("http://127.0.0.1:8765/");
                            }
                        } else {
                            // Keep any open notes intact while the host recovers.
                            startBackend();
                        }
                    }
                });
            }
        }, "devco-host-check").start();
    }

    @Override protected void onResume() {
        super.onResume();
        foreground = true;
        if (voice != null) voice.onResume();
        startBackend();
        hostHandler.removeCallbacks(hostMonitor);
        hostHandler.post(hostMonitor);
    }

    @Override protected void onPause() {
        if (voice != null) voice.onPause();
        foreground = false;
        hostHandler.removeCallbacks(hostMonitor);
        super.onPause();
    }

    @Override protected void onDestroy() {
        if (voice != null) voice.destroy();
        foreground = false;
        hostHandler.removeCallbacksAndMessages(null);
        super.onDestroy();
    }

    private void openSolocator() {
        try {
            Intent launch = getPackageManager().getLaunchIntentForPackage("com.solocator");
            if (launch == null) {
                launch = new Intent(Intent.ACTION_MAIN);
                launch.addCategory(Intent.CATEGORY_LAUNCHER);
                launch.setClassName("com.solocator", "com.solocator.splash.SplashActivity");
            }
            startActivity(launch);
        } catch (Exception e) {
            Toast.makeText(this, "Solocator could not open. Check that it is installed and enabled.", Toast.LENGTH_LONG).show();
        }
    }

    private void openGoogleMaps(String lat, String lon) {
        Uri nav = Uri.parse("google.navigation:q=" + Uri.encode(lat + "," + lon) + "&mode=d");
        Intent intent = new Intent(Intent.ACTION_VIEW, nav);
        intent.setPackage("com.google.android.apps.maps");
        try {
            startActivity(intent);
        } catch (Exception e) {
            // Fallback still leaves DEVCO Field and opens an external handler.
            Uri webUri = Uri.parse("https://www.google.com/maps/dir/?api=1&destination="
                    + Uri.encode(lat + "," + lon) + "&travelmode=driving");
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, webUri));
            } catch (Exception ignored) {
                Toast.makeText(this, "Google Maps is unavailable", Toast.LENGTH_SHORT).show();
            }
        }
    }

    private void startBackend() {
        if (getPackageManager().checkPermission("com.termux.permission.RUN_COMMAND", getPackageName()) != PackageManager.PERMISSION_GRANTED) {
            if (!commandPermissionRequested) {
                commandPermissionRequested = true;
                try {
                    java.lang.reflect.Method method = Activity.class.getMethod("requestPermissions", String[].class, Integer.TYPE);
                    method.invoke(this, new Object[]{new String[]{"com.termux.permission.RUN_COMMAND"}, Integer.valueOf(78)});
                } catch (Exception e) {
                    Toast.makeText(this, "Allow DEVCO Field to run commands in Termux in Android app permissions.", Toast.LENGTH_LONG).show();
                }
            }
            return;
        }
        long now = android.os.SystemClock.elapsedRealtime();
        if (lastStartAttempt != 0 && now - lastStartAttempt < 15000) return;
        lastStartAttempt = now;
        try {
            Intent i = new Intent();
            i.setClassName("com.termux", "com.termux.app.RunCommandService");
            i.setAction("com.termux.RUN_COMMAND");
            i.putExtra("com.termux.RUN_COMMAND_PATH", "/data/data/com.termux/files/usr/bin/bash");
            i.putExtra("com.termux.RUN_COMMAND_ARGUMENTS", new String[]{
                "/data/data/com.termux/files/home/DEVCO_FIELD/SYSTEM/devco-host", "ensure"
            });
            i.putExtra("com.termux.RUN_COMMAND_WORKDIR", "/data/data/com.termux/files/home/DEVCO_FIELD");
            i.putExtra("com.termux.RUN_COMMAND_BACKGROUND", true);
            i.putExtra("com.termux.RUN_COMMAND_COMMAND_LABEL", "DEVCO host recovery");
            startService(i);
        } catch (Exception e) {
            Toast.makeText(this, "Open Termux once, then return to DEVCO. Host startup: " + e.getClass().getSimpleName(), Toast.LENGTH_LONG).show();
        }
    }

    private void requestLocationPermission() {
        try {
            java.lang.reflect.Method m = Activity.class.getMethod("requestPermissions", String[].class, Integer.TYPE);
            m.invoke(this, new Object[]{new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION}, Integer.valueOf(77)});
        } catch (Exception e) {
            if (pendingGeoCallback != null) {
                pendingGeoCallback.invoke(pendingGeoOrigin, false, false);
                pendingGeoCallback = null;
                pendingGeoOrigin = null;
            }
        }
    }

    // Called by Android 6+ after the reflected runtime permission request.
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        if (requestCode == VoiceCloseout.AUDIO_PERMISSION && voice != null) {
            voice.permissionResult(grantResults); return;
        }
        if (requestCode == 78) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                lastStartAttempt = 0;
                startBackend();
                checkBackend();
            } else {
                Toast.makeText(this, "DEVCO needs permission to start its Termux host automatically.", Toast.LENGTH_LONG).show();
            }
            return;
        }
        if (requestCode == 77 && pendingGeoCallback != null) {
            boolean allowed = grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED;
            pendingGeoCallback.invoke(pendingGeoOrigin, allowed, false);
            pendingGeoCallback = null;
            pendingGeoOrigin = null;
        }
    }

    @Override public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }
}
