package com.devco.field;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.webkit.WebView;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Locale;
import android.util.JsonWriter;
import java.io.StringWriter;

/** Foreground-only speech, scoped to one loaded local Billing page and session. */
public final class VoiceCloseout {
    private final Activity activity;
    private final WebView web;
    private final Handler handler = new Handler();
    private TextToSpeech tts;
    private SpeechRecognizer recognizer;
    private boolean ttsReady, foreground, awaitingPermission, pendingPrompt, destroyed;
    private String session = "", stage = "";
    private int generation = 0;
    public static final int AUDIO_PERMISSION = 79;

    public VoiceCloseout(Activity activity, WebView web) {
        this.activity = activity;
        this.web = web;
    }

    public static boolean isBilling(String url) {
        if (url == null) return false;
        Uri uri = Uri.parse(url);
        return "http".equals(uri.getScheme()) && "127.0.0.1".equals(uri.getHost())
                && uri.getPort() == 8765 && "/billing".equals(uri.getPath());
    }

    private boolean valid(int ticket) {
        return !destroyed && foreground && ticket == generation && !session.isEmpty() && isBilling(web.getUrl());
    }

    public boolean handle(Uri uri) {
        if (!"devco-voice".equals(uri.getScheme())) return false;
        if (!isBilling(web.getUrl()) || !foreground || destroyed) return true;
        if ("stop".equals(uri.getHost())) { cancel(false); return true; }
        if (!"prompt".equals(uri.getHost())) return true;
        String requestedSession = uri.getQueryParameter("session");
        String requestedStage = uri.getQueryParameter("stage");
        if (requestedSession == null || !requestedSession.matches("[A-Za-z0-9_-]{1,100}")) return true;
        if (!("notes".equals(requestedStage) || "close".equals(requestedStage)
                || "retry-notes".equals(requestedStage) || "retry-close".equals(requestedStage))) return true;
        cancel(false);
        session = requestedSession; stage = requestedStage; pendingPrompt = true;
        if (android.os.Build.VERSION.SDK_INT >= 23 && activity.getPackageManager().checkPermission(
                Manifest.permission.RECORD_AUDIO, activity.getPackageName()) != PackageManager.PERMISSION_GRANTED) {
            awaitingPermission = true;
            event("permission", "Allow microphone access for spoken closeout.", "");
            try {
                java.lang.reflect.Method method = Activity.class.getMethod("requestPermissions", String[].class, Integer.TYPE);
                method.invoke(activity, new Object[]{new String[]{Manifest.permission.RECORD_AUDIO}, Integer.valueOf(AUDIO_PERMISSION)});
            } catch (Exception error) {
                awaitingPermission = false;
                fail("Microphone permission could not be requested. Use the manual controls.");
            }
        } else {
            prepareTts();
        }
        return true;
    }

    private String prompt() {
        if ("notes".equals(stage)) return "What are your notes?";
        if ("close".equals(stage)) return "What is the closing task?";
        if ("retry-notes".equals(stage)) return "I didn't catch that. What are your notes? You can also say no notes.";
        return "What is the closing task? Say ADSS, already completed, no services, no Windstream line, fiber transfer completed, or pending.";
    }

    private void prepareTts() {
        if (!valid(generation) || !pendingPrompt || awaitingPermission) return;
        if (!SpeechRecognizer.isRecognitionAvailable(activity)) {
            fail("Speech recognition is unavailable. Use the manual controls."); return;
        }
        final int ticket = generation;
        handler.removeCallbacksAndMessages(null);
        handler.postDelayed(new Runnable() { @Override public void run() {
            if (valid(ticket)) fail("Voice prompt timed out. Use the manual controls.");
        }}, 15000);
        if (ttsReady) { speak(); return; }
        if (tts != null) return;
        tts = new TextToSpeech(activity, new TextToSpeech.OnInitListener() {
            @Override public void onInit(final int status) {
                handler.post(new Runnable() { @Override public void run() {
                    if (destroyed || tts == null) return;
                    if (status != TextToSpeech.SUCCESS) { fail("Spoken prompts are unavailable. Use the manual controls."); return; }
                    int language = tts.setLanguage(Locale.US);
                    if (language == TextToSpeech.LANG_MISSING_DATA || language == TextToSpeech.LANG_NOT_SUPPORTED) {
                        fail("An English speech voice is unavailable. Use the manual controls."); return;
                    }
                    tts.setSpeechRate(0.88f);
                    tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                        @Override public void onStart(String id) {}
                        @Override public void onDone(final String id) {
                            handler.post(new Runnable() { @Override public void run() {
                                if (id.equals("devco-" + generation) && valid(generation)) {
                                    final int current = generation;
                                    handler.removeCallbacksAndMessages(null);
                                    // Let the speaker finish before opening the microphone.
                                    handler.postDelayed(new Runnable() { @Override public void run() {
                                        if (valid(current)) listen(current);
                                    }}, 350);
                                }
                            }});
                        }
                        @Override public void onError(final String id) {
                            handler.post(new Runnable() { @Override public void run() {
                                if (id.equals("devco-" + generation) && valid(generation)) fail("Could not speak the prompt. Use the manual controls.");
                            }});
                        }
                    });
                    ttsReady = true;
                    if (pendingPrompt && foreground && isBilling(web.getUrl())) speak();
                }});
            }
        });
    }

    private void speak() {
        if (!valid(generation) || !pendingPrompt || !ttsReady) return;
        pendingPrompt = false;
        event("speaking", prompt(), "");
        HashMap<String,String> params = new HashMap<String,String>();
        params.put(TextToSpeech.Engine.KEY_PARAM_UTTERANCE_ID, "devco-" + generation);
        if (tts.speak(prompt(), TextToSpeech.QUEUE_FLUSH, params) == TextToSpeech.ERROR) {
            fail("Could not speak the prompt. Use the manual controls.");
        }
    }

    private void listen(final int ticket) {
        if (!valid(ticket)) return;
        try {
            recognizer = SpeechRecognizer.createSpeechRecognizer(activity);
            recognizer.setRecognitionListener(new RecognitionListener() {
                @Override public void onReadyForSpeech(Bundle params) { if (valid(ticket)) event("listening", "Listening…", ""); }
                @Override public void onBeginningOfSpeech() {}
                @Override public void onRmsChanged(float value) {}
                @Override public void onBufferReceived(byte[] buffer) {}
                @Override public void onEndOfSpeech() { if (valid(ticket)) event("processing", "Processing speech…", ""); }
                @Override public void onPartialResults(Bundle results) {
                    if (!valid(ticket)) return;
                    ArrayList<String> words = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                    if (words != null && !words.isEmpty()) event("partial", "Listening…", words.get(0));
                }
                @Override public void onResults(Bundle results) {
                    if (!valid(ticket)) return;
                    handler.removeCallbacksAndMessages(null);
                    ArrayList<String> words = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                    float[] confidence = results.getFloatArray(SpeechRecognizer.CONFIDENCE_SCORES);
                    ++generation; releaseRecognizer();
                    if (words == null || words.isEmpty() || words.get(0).trim().isEmpty()) { event("retry", "No speech was heard.", ""); return; }
                    if (confidence != null && confidence.length > 0 && confidence[0] >= 0 && confidence[0] < 0.45f) {
                        event("retry", "Speech was unclear. Please repeat.", words.get(0)); return;
                    }
                    event("result", "Speech captured", words.get(0));
                }
                @Override public void onError(int error) {
                    if (!valid(ticket)) return;
                    handler.removeCallbacksAndMessages(null); ++generation; releaseRecognizer();
                    if (error == SpeechRecognizer.ERROR_NO_MATCH || error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT) {
                        event("retry", "No clear speech was heard.", "");
                    } else {
                        event("error", "Speech is unavailable (code " + error + "). Use the manual controls.", "");
                    }
                }
                @Override public void onEvent(int type, Bundle params) {}
            });
            Intent request = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
            request.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
            request.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-US");
            request.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
            request.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
            request.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 2500L);
            request.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 1800L);
            request.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, 5000L);
            recognizer.startListening(request);
            handler.postDelayed(new Runnable() { @Override public void run() {
                if (valid(ticket) && recognizer != null) recognizer.stopListening();
            }}, 90000);
            handler.postDelayed(new Runnable() { @Override public void run() {
                if (valid(ticket)) fail("Speech timed out. Use the manual controls.");
            }}, 100000);
        } catch (Exception error) {
            fail("Could not start listening. Use the manual controls.");
        }
    }

    private void releaseRecognizer() {
        if (recognizer != null) {
            SpeechRecognizer old = recognizer; recognizer = null;
            old.cancel(); old.destroy();
        }
    }

    private void event(String type, String message, String transcript) {
        if (destroyed || !isBilling(web.getUrl()) || session.isEmpty()) return;
        try {
            StringWriter output = new StringWriter();
            JsonWriter data = new JsonWriter(output);
            data.beginObject();
            data.name("session").value(session); data.name("stage").value(stage); data.name("type").value(type);
            data.name("message").value(message); data.name("transcript").value(transcript);
            data.endObject(); data.close();
            String payload = output.toString().replace("\u2028", "\\u2028").replace("\u2029", "\\u2029");
            web.loadUrl("javascript:window.devcoVoiceEvent&&window.devcoVoiceEvent(" + payload + ")");
        } catch (Exception ignored) {}
    }

    private void fail(String message) { event("error",message,""); cancel(false); }

    public void cancel(boolean notify) {
        if (notify && !session.isEmpty()) event("stopped","Voice paused. Your notes are kept; manual controls remain available.","");
        ++generation; pendingPrompt = false; awaitingPermission = false;
        handler.removeCallbacksAndMessages(null);
        if (tts != null) tts.stop();
        releaseRecognizer(); session = ""; stage = "";
    }

    public void onResume() {
        foreground = true;
        if (pendingPrompt && !awaitingPermission) prepareTts();
    }

    public void onPause() {
        foreground = false;
        // The system permission sheet may pause the Activity; keep only that request.
        if (!awaitingPermission) cancel(true);
    }

    public void permissionResult(int[] grantResults) {
        if (!awaitingPermission) return;
        awaitingPermission = false;
        if (grantResults.length == 0 || grantResults[0] != PackageManager.PERMISSION_GRANTED) {
            fail("Microphone access was not granted. Use the manual controls."); return;
        }
        if (foreground) prepareTts();
    }

    public void destroy() {
        cancel(false); destroyed = true;
        if (tts != null) { tts.shutdown(); tts = null; }
    }
}
