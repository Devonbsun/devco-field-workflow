package com.devco.field;

import android.app.Activity;
import android.os.Bundle;
import android.view.Window;
import android.content.Intent;
import android.net.Uri;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

public class MainActivity extends Activity {
    private WebView web;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        web = new WebView(this);
        web.setWebViewClient(new WebViewClient() {
            private boolean handle(Uri uri) {
                if (uri == null) return false;
                String scheme = uri.getScheme();
                String host = uri.getHost();

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

            @Override public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handle(Uri.parse(url));
            }
        });
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        setContentView(web);
        startBackend();
        web.loadUrl("http://127.0.0.1:8765");
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
        try {
            Intent i = new Intent();
            i.setClassName("com.termux", "com.termux.app.RunCommandService");
            i.setAction("com.termux.RUN_COMMAND");
            i.putExtra("com.termux.RUN_COMMAND_PATH", "/data/data/com.termux/files/usr/bin/bash");
            i.putExtra("com.termux.RUN_COMMAND_ARGUMENTS", new String[]{
                "-lc",
                "cd ~/DEVCO_FIELD && (pgrep -f 'SYSTEM/devco_app.py' >/dev/null || nohup python ~/DEVCO_FIELD/SYSTEM/devco_app.py > ~/DEVCO_FIELD/.devco_app.log 2>&1 &)"
            });
            i.putExtra("com.termux.RUN_COMMAND_WORKDIR", "/data/data/com.termux/files/home");
            i.putExtra("com.termux.RUN_COMMAND_BACKGROUND", true);
            startService(i);
        } catch (Exception e) {
            Toast.makeText(this, "Starting DEVCO Field...", Toast.LENGTH_SHORT).show();
        }
    }

    @Override public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }
}
