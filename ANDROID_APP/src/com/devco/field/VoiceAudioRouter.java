package com.devco.field;

import android.content.Context;
import android.media.AudioManager;
import android.os.Build;
import android.os.Handler;
import java.util.List;

/** Owns audio only while a foreground closeout prompt/listen is active. */
public final class VoiceAudioRouter {
    public interface Callback {
        void ready();
        void failed(String message);
    }

    private final AudioManager audio;
    private final Handler handler = new Handler();
    private int generation;
    private boolean focusHeld, modeOwned, routeOwned, external, recognizing;
    private Object selected;
    private Callback callback;
    private AudioManager.OnAudioFocusChangeListener focusListener;

    public VoiceAudioRouter(Context context) {
        audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
    }

    public boolean isExternal() { return external; }
    public String label() { return external ? "truck/headset audio" : "phone audio"; }
    public int promptStream() {
        return modeOwned ? AudioManager.STREAM_VOICE_CALL : AudioManager.STREAM_MUSIC;
    }

    public void prepare(boolean phoneOnly, Callback next) {
        release();
        callback = next;
        final int ticket = generation;
        if (audio == null) { fail("Audio service is unavailable."); return; }
        try {
            // Never take over an active call or another communication session.
            if (audio.getMode() != AudioManager.MODE_NORMAL) {
                fail("Another call or voice session is using audio. Finish it, then reopen Billing/Closeout."); return;
            }
            if (audio.isMicrophoneMute()) {
                fail("The microphone is muted. Enable microphone access, then reopen Billing/Closeout."); return;
            }
            focusListener = new AudioManager.OnAudioFocusChangeListener() {
                @Override public void onAudioFocusChange(final int change) {
                    handler.post(new Runnable() { @Override public void run() {
                        // Focus governs prompt playback. SpeechRecognizer runs in another
                        // service and may acquire its own focus when we hand off capture.
                        if (ticket == generation && focusHeld && !recognizing
                                && (change == AudioManager.AUDIOFOCUS_LOSS
                                || change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT)) {
                            fail("Voice paused because another app needs audio. Your notes are kept; reopen Billing/Closeout when ready.");
                        }
                    }});
                }
            };
            int stream = Build.VERSION.SDK_INT >= 31 ? AudioManager.STREAM_VOICE_CALL : AudioManager.STREAM_MUSIC;
            focusHeld = audio.requestAudioFocus(focusListener, stream,
                    AudioManager.AUDIOFOCUS_GAIN_TRANSIENT) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED;
            if (!focusHeld) { fail("Audio is busy. Finish the other voice session, then reopen Billing/Closeout."); return; }
            if (Build.VERSION.SDK_INT < 31) { next.ready(); return; }
            // Public API 31+ methods are reflected because the phone's build jar is older.
            List<?> devices = (List<?>) AudioManager.class.getMethod("getAvailableCommunicationDevices").invoke(audio);
            Object current = AudioManager.class.getMethod("getCommunicationDevice").invoke(audio);
            Object phone = null, preferred = null;
            for (Object device : devices) {
                int type = deviceValue(device, "getType");
                if (type == 2) phone = device; // TYPE_BUILTIN_SPEAKER, with matching phone microphone
                if (!phoneOnly && isMicrophoneRoute(type)) {
                    if (preferred == null || type == 7 || type == 26) preferred = device;
                    if (sameDevice(device, current)) { preferred = device; break; }
                }
            }
            // Find the speaker even if the current external device ended the first loop.
            if (phone == null) for (Object device : devices) {
                if (deviceValue(device, "getType") == 2) { phone = device; break; }
            }
            selected = preferred != null ? preferred : phone;
            external = preferred != null;
            if (selected == null) { fail("No usable microphone route is available."); return; }
            audio.setMode(AudioManager.MODE_IN_COMMUNICATION);
            modeOwned = true;
            if (!select(selected)) {
                if (!external || phone == null || !select(phone)) { fail("Could not connect the microphone."); return; }
                selected = phone; external = false;
            }
            waitForRoute(ticket, 0, phone);
        } catch (Exception error) {
            fail("Could not prepare audio. Reopen Billing/Closeout or use the manual controls.");
        }
    }

    private static boolean isMicrophoneRoute(int type) {
        // Wired headset, Bluetooth SCO/HFP, USB device/headset, BLE headset. A2DP has no mic.
        return type == 3 || type == 7 || type == 11 || type == 22 || type == 26;
    }

    private static int deviceValue(Object device, String method) throws Exception {
        return ((Integer) Class.forName("android.media.AudioDeviceInfo").getMethod(method).invoke(device)).intValue();
    }

    private static boolean sameDevice(Object first, Object second) throws Exception {
        return first != null && second != null && deviceValue(first, "getId") == deviceValue(second, "getId");
    }

    private boolean select(Object device) throws Exception {
        boolean accepted = ((Boolean) AudioManager.class.getMethod("setCommunicationDevice",
                Class.forName("android.media.AudioDeviceInfo")).invoke(audio, device)).booleanValue();
        routeOwned = routeOwned || accepted;
        return accepted;
    }

    private void waitForRoute(final int ticket, final int polls, final Object phone) {
        if (ticket != generation || callback == null) return;
        try {
            Object active = AudioManager.class.getMethod("getCommunicationDevice").invoke(audio);
            if (sameDevice(selected, active)) {
                // Give the audio path a settling interval before speaking or recording.
                handler.postDelayed(new Runnable() { @Override public void run() {
                    if (ticket == generation && callback != null) callback.ready();
                }}, 500);
                return;
            }
            if (polls >= 30) {
                if (external && phone != null) {
                    AudioManager.class.getMethod("clearCommunicationDevice").invoke(audio);
                    routeOwned = false;
                    if (!select(phone)) { fail("The truck microphone did not connect, and phone audio is unavailable."); return; }
                    selected = phone; external = false;
                    waitForRoute(ticket, 0, null);
                } else fail("The microphone connection timed out. Reopen Billing/Closeout or use the manual controls.");
                return;
            }
            handler.postDelayed(new Runnable() { @Override public void run() {
                waitForRoute(ticket, polls + 1, phone);
            }}, 200);
        } catch (Exception error) {
            fail("The microphone connection was interrupted. Reopen Billing/Closeout.");
        }
    }

    private void fail(String message) {
        Callback target = callback;
        release();
        if (target != null) target.failed(message);
    }

    /** End prompt playback focus before starting the separate recognition service.
     * Keep the selected communication route until the transcript, error or cancel.
     */
    public boolean beginRecognition() {
        if (callback == null || audio == null) return false;
        if (audio.getMode() == AudioManager.MODE_IN_CALL || audio.getMode() == AudioManager.MODE_RINGTONE) {
            fail("A phone call is using audio. Finish it, then reopen Billing/Closeout.");
            return false;
        }
        recognizing = true;
        abandonPromptFocus();
        return true;
    }

    private void abandonPromptFocus() {
        boolean held = focusHeld;
        // Clear first: a queued or synchronous loss belongs to the finished prompt.
        focusHeld = false;
        if (held && audio != null && focusListener != null) {
            try { audio.abandonAudioFocus(focusListener); } catch (Exception ignored) {}
        }
    }

    public void release() {
        ++generation;
        handler.removeCallbacksAndMessages(null);
        callback = null;
        if (audio != null) {
            if (routeOwned && Build.VERSION.SDK_INT >= 31) {
                try { AudioManager.class.getMethod("clearCommunicationDevice").invoke(audio); } catch (Exception ignored) {}
            }
            if (modeOwned) {
                try { audio.setMode(AudioManager.MODE_NORMAL); } catch (Exception ignored) {}
            }
            abandonPromptFocus();
        }
        routeOwned = modeOwned = focusHeld = external = recognizing = false;
        selected = null; focusListener = null;
    }
}
