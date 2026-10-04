"""Run the actual native closeout controller with a recognizer that changes focus.

Deterministic integration coverage for the Android Auto failure: successful
capture, phone fallback, saved route between stages, stale callbacks and pause.
Does not record audio or access live job records.
"""
from pathlib import Path
import subprocess
import tempfile
from test_voice_audio import STUBS

EXTRA = {
    'android/Manifest.java': '''package android;
public class Manifest {public static class permission {public static final String RECORD_AUDIO="record";}}''',
    'android/content/pm/PackageManager.java': '''package android.content.pm;
public class PackageManager {public static final int PERMISSION_GRANTED=0;public int checkPermission(String p,String n){return 0;}}''',
    'android/app/Activity.java': '''package android.app;
public class Activity extends android.content.Context {
 public android.content.pm.PackageManager getPackageManager(){return new android.content.pm.PackageManager();}
 public String getPackageName(){return "com.devco.field";}
 public void requestPermissions(String[] permissions,int code){}
}''',
    'android/content/Intent.java': '''package android.content;
public class Intent {public Intent(String s){} public Intent putExtra(String k,Object v){return this;}}''',
    'android/net/Uri.java': '''package android.net;
public class Uri {java.net.URI value;
 public static Uri parse(String s){Uri u=new Uri();u.value=java.net.URI.create(s);return u;}
 public String getScheme(){return value.getScheme();}public String getHost(){return value.getHost();}
 public String getPath(){return value.getPath();}public int getPort(){return value.getPort();}
 public String getQueryParameter(String name){for(String p:value.getQuery().split("&")){String[] x=p.split("=",2);if(x[0].equals(name))return x[1];}return null;}
}''',
    'android/os/Bundle.java': '''package android.os;
public class Bundle {public java.util.ArrayList<String> words;
 public java.util.ArrayList<String> getStringArrayList(String key){return words;}
 public float[] getFloatArray(String key){return new float[]{0.99f};}
}''',
    'android/webkit/WebView.java': '''package android.webkit;
public class WebView {public String url="http://127.0.0.1:8765/billing";
 public java.util.List<String> events=new java.util.ArrayList<String>();
 public String getUrl(){return url;}public void loadUrl(String value){events.add(value);}
}''',
    'android/util/JsonWriter.java': '''package android.util;
import java.io.*;
public class JsonWriter {
 final Writer writer;boolean first=true;public JsonWriter(Writer w){writer=w;}
 public JsonWriter beginObject()throws IOException{writer.write("{");return this;}
 public JsonWriter name(String name)throws IOException{if(!first)writer.write(",");first=false;writer.write("\\\""+name+"\\\":");return this;}
 public JsonWriter value(String value)throws IOException{writer.write("\\\""+value+"\\\"");return this;}
 public JsonWriter endObject()throws IOException{writer.write("}");return this;}public void close(){}
}''',
    'android/speech/RecognitionListener.java': '''package android.speech;
import android.os.Bundle;
public interface RecognitionListener {
 void onReadyForSpeech(Bundle b);void onBeginningOfSpeech();void onRmsChanged(float v);void onBufferReceived(byte[] b);
 void onEndOfSpeech();void onPartialResults(Bundle b);void onResults(Bundle b);void onError(int e);void onEvent(int e,Bundle b);
}''',
    'android/speech/RecognizerIntent.java': '''package android.speech;
public class RecognizerIntent {public static final String ACTION_RECOGNIZE_SPEECH="speech",EXTRA_LANGUAGE_MODEL="model",LANGUAGE_MODEL_FREE_FORM="free",
 EXTRA_LANGUAGE="language",EXTRA_PARTIAL_RESULTS="partial",EXTRA_MAX_RESULTS="max",EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS="complete",
 EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS="possibly",EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS="min";}
''',
    'android/speech/SpeechRecognizer.java': '''package android.speech;
import android.content.*;import android.os.*;
public class SpeechRecognizer {
 public static final String RESULTS_RECOGNITION="results",CONFIDENCE_SCORES="confidence";
 public static final int ERROR_NO_MATCH=7,ERROR_SPEECH_TIMEOUT=6,ERROR_AUDIO=3,ERROR_RECOGNIZER_BUSY=8;
 public static SpeechRecognizer last;public static int starts;public RecognitionListener listener;Context context;
 public static boolean isRecognitionAvailable(Context c){return true;}
 public static SpeechRecognizer createSpeechRecognizer(Context c){last=new SpeechRecognizer();last.context=c;return last;}
 public void setRecognitionListener(RecognitionListener l){listener=l;}
 public void startListening(Intent i){starts++;context.audio.listener.onAudioFocusChange(-2);listener.onReadyForSpeech(new Bundle());}
 public void stopListening(){}public void cancel(){}public void destroy(){}
 public void result(String words){Bundle b=new Bundle();b.words=new java.util.ArrayList<String>();b.words.add(words);listener.onResults(b);}
}''',
    'android/speech/tts/UtteranceProgressListener.java': '''package android.speech.tts;
public abstract class UtteranceProgressListener {public abstract void onStart(String id);public abstract void onDone(String id);public abstract void onError(String id);}''',
    'android/speech/tts/TextToSpeech.java': '''package android.speech.tts;
import android.content.*;import android.os.*;import java.util.*;
public class TextToSpeech {
 public static final int SUCCESS=0,ERROR=-1,LANG_MISSING_DATA=-2,LANG_NOT_SUPPORTED=-3,QUEUE_FLUSH=0;
 public static class Engine {public static final String KEY_PARAM_UTTERANCE_ID="id",KEY_PARAM_STREAM="stream";}
 public interface OnInitListener {void onInit(int status);}
 final Handler handler=new Handler();UtteranceProgressListener progress;
 public TextToSpeech(Context c,OnInitListener l){handler.postDelayed(()->l.onInit(0),1);}
 public int setLanguage(Locale l){return 0;}public void setSpeechRate(float r){}
 public void setOnUtteranceProgressListener(UtteranceProgressListener l){progress=l;}
 public int speak(String text,int queue,HashMap<String,String> params){String id=params.get("id");handler.postDelayed(()->progress.onDone(id),10);return 0;}
 public void stop(){handler.removeCallbacksAndMessages(null);}public void shutdown(){stop();}
}''',
    'com/devco/field/VoiceHandoffTest.java': '''package com.devco.field;
import android.app.*;import android.media.*;import android.net.*;import android.os.*;import android.webkit.*;import android.speech.*;
public class VoiceHandoffTest {
 static Activity a;static WebView web;static VoiceCloseout voice;static int passed;
 static void setup(){Handler.reset();SpeechRecognizer.starts=0;SpeechRecognizer.last=null;
  a=new Activity();a.audio.devices.add(new AudioDeviceInfo(1,2));a.audio.devices.add(new AudioDeviceInfo(2,7));
  web=new WebView();voice=new VoiceCloseout(a,web);voice.onResume();
 }
 static void prompt(String stage){voice.handle(Uri.parse("devco-voice://prompt?session=test&stage="+stage));Handler.advance(1000);}
 static boolean event(String type){return web.events.stream().anyMatch(s->s.contains("\\\"type\\\":\\\""+type+"\\\""));}
 static void check(boolean value){if(!value)throw new AssertionError("case "+(passed+1)+" events="+web.events);}
 static void pass(String name){voice.destroy();passed++;System.out.println("PASS "+name);}
 public static void main(String[] args){
  setup();prompt("notes");check(SpeechRecognizer.starts==1&&event("listening")&&!event("error"));
  check(a.audio.abandons==1&&a.audio.clears==0&&a.audio.mode==3);
  SpeechRecognizer.last.result("Surveyed the pole.");check(event("result")&&a.audio.mode==0&&a.audio.clears==1);
  pass("real closeout survives recognition-service focus loss and delivers transcript");

  setup();prompt("notes");SpeechRecognizer old=SpeechRecognizer.last;old.listener.onError(SpeechRecognizer.ERROR_NO_MATCH);
  Handler.advance(2000);check(SpeechRecognizer.starts==2&&a.audio.requested.type==2&&!event("error"));
  old.result("Late incorrect note");check(!event("result"));SpeechRecognizer.last.result("Correct note");check(event("result"));
  prompt("close");check(SpeechRecognizer.starts==3&&a.audio.requested.type==2&&!event("error"));
  SpeechRecognizer.last.result("ADSS");check(a.audio.mode==0);
  pass("fallback captures through phone, ignores stale result, keeps phone for closing task");

  setup();prompt("notes");SpeechRecognizer paused=SpeechRecognizer.last;voice.onPause();paused.result("Late note");
  Handler.advance(100000);check(!event("result")&&a.audio.mode==0&&SpeechRecognizer.starts==1);
  pass("leaving closeout releases audio and rejects delayed transcript");
  System.out.println(passed+" native closeout integration scenarios passed");
 }
}''',
}

if __name__ == '__main__':
    app = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='devco-handoff-test-') as directory:
        root = Path(directory)
        for filename, content in {**STUBS, **EXTRA}.items():
            if filename.endswith('VoiceAudioRouterTest.java'):
                continue
            target = root / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        sources = [app / 'src/com/devco/field' / name for name in ('VoiceCloseout.java', 'VoiceAudioRouter.java')]
        subprocess.run(['javac', '-d', str(root), *map(str, sources), *map(str, root.rglob('*.java'))], check=True)
        subprocess.run(['java', '-cp', str(root), 'com.devco.field.VoiceHandoffTest'], check=True)
