"""Exercise the real Java audio router against deterministic Android fakes.

Run with Python and a JDK. This does not access any microphone or production JU.
Physical Android Auto / recognizer interoperability still requires a device test.
"""
from pathlib import Path
import subprocess
import tempfile

STUBS = {
    'android/content/Context.java': '''package android.content;
public class Context {
 public static final String AUDIO_SERVICE="audio";
 public android.media.AudioManager audio = new android.media.AudioManager();
 public Object getSystemService(String name) { return audio; }
}''',
    'android/os/Build.java': '''package android.os;
public class Build { public static class VERSION { public static int SDK_INT=36; } }''',
    'android/os/Handler.java': '''package android.os;
import java.util.*;
public class Handler {
 static class Task { Handler owner; Runnable work; long at; Task(Handler h,Runnable r,long t){owner=h;work=r;at=t;} }
 static List<Task> tasks=new ArrayList<Task>(); static long now;
 public boolean post(Runnable r){return postDelayed(r,0);}
 public boolean postDelayed(Runnable r,long delay){tasks.add(new Task(this,r,now+delay));return true;}
 public void removeCallbacksAndMessages(Object token){tasks.removeIf(t->t.owner==this);}
 public static void reset(){tasks.clear();now=0;}
 public static void advance(long ms){long end=now+ms;int limit=1000;
  while(true){Task first=null;for(Task t:tasks)if(t.at<=end&&(first==null||t.at<first.at))first=t;
   if(first==null)break;if(--limit<0)throw new AssertionError("loop");
   tasks.remove(first);now=first.at;first.work.run();
  }now=end;
 }
}''',
    'android/media/AudioDeviceInfo.java': '''package android.media;
public class AudioDeviceInfo { public int id,type;
 public AudioDeviceInfo(int i,int t){id=i;type=t;} public int getId(){return id;} public int getType(){return type;}
}''',
    'android/media/AudioManager.java': '''package android.media;
import java.util.*;
public class AudioManager {
 public static final int MODE_NORMAL=0,MODE_IN_COMMUNICATION=3,STREAM_MUSIC=3,STREAM_VOICE_CALL=0;
 public static final int AUDIOFOCUS_GAIN_TRANSIENT=2,AUDIOFOCUS_REQUEST_GRANTED=1;
 public interface OnAudioFocusChangeListener { void onAudioFocusChange(int change); }
 public int mode,clears,abandons,modeCalls; public boolean mute,grant=true,rejectExternal,connectExternal=true,connectPhone=true,throwSelect;
 public AudioDeviceInfo active,requested; public List<AudioDeviceInfo> devices=new ArrayList<AudioDeviceInfo>();
 public List<Integer> requests=new ArrayList<Integer>(); public OnAudioFocusChangeListener listener;
 public int getMode(){return mode;} public void setMode(int m){mode=m;modeCalls++;}
 public boolean isMicrophoneMute(){return mute;}
 public int requestAudioFocus(OnAudioFocusChangeListener l,int stream,int hint){listener=l;return grant?1:0;}
 public int abandonAudioFocus(OnAudioFocusChangeListener l){abandons++;return 1;}
 public List<AudioDeviceInfo> getAvailableCommunicationDevices(){return devices;}
 public AudioDeviceInfo getCommunicationDevice(){return active;}
 public boolean setCommunicationDevice(AudioDeviceInfo d){
  requests.add(d.type);if(throwSelect)throw new SecurityException("test");
  if(rejectExternal&&d.type!=2)return false;requested=d;
  if((d.type==2&&connectPhone)||(d.type!=2&&connectExternal))active=d;return true;
 }
 public void clearCommunicationDevice(){clears++;active=null;}
}''',
    'com/devco/field/VoiceAudioRouterTest.java': '''package com.devco.field;
import android.content.Context;import android.media.*;import android.os.*;
public class VoiceAudioRouterTest {
 static class Result implements VoiceAudioRouter.Callback {int ready,failed;String error="";
  public void ready(){ready++;}public void failed(String s){failed++;error=s;}
 }
 static Context c;static AudioManager a;static VoiceAudioRouter router;static Result result;static int passed;
 static void setup(){Handler.reset();Build.VERSION.SDK_INT=36;c=new Context();a=c.audio;
  a.devices.add(new AudioDeviceInfo(1,2));a.devices.add(new AudioDeviceInfo(2,7));router=new VoiceAudioRouter(c);result=new Result();}
 static void check(boolean ok){if(!ok)throw new AssertionError("case "+(passed+1));}
 static void pass(String s){passed++;System.out.println("PASS "+s);router.release();}
 public static void main(String[] args){
  setup();a.connectExternal=false;router.prepare(false,result);Handler.advance(1000);
  check(result.ready==0);a.active=a.requested;Handler.advance(699);check(result.ready==0);
  Handler.advance(1);check(result.ready==1&&router.isExternal());router.release();
  check(a.mode==0&&a.clears==1&&a.abandons==1);pass("wait for route and settling, then clean release");

  setup();router.prepare(false,result);router.release();Handler.advance(10000);
  check(result.ready==0&&result.failed==0);pass("cancel invalidates delayed readiness");

  setup();a.rejectExternal=true;router.prepare(false,result);Handler.advance(500);
  check(result.ready==1&&!router.isExternal()&&a.requested.type==2);pass("rejected truck route falls back to phone");

  setup();a.connectExternal=false;router.prepare(false,result);Handler.advance(6500);
  check(result.ready==1&&!router.isExternal()&&a.requests.size()==2);pass("truck connection timeout falls back once");

  setup();a.connectExternal=false;a.connectPhone=false;router.prepare(false,result);Handler.advance(20000);
  check(result.ready==0&&result.failed==1&&a.mode==0&&a.abandons==1&&a.requests.size()==2);
  pass("both unavailable stops with bounded failure and cleanup");

  setup();router.prepare(true,result);Handler.advance(500);
  check(result.ready==1&&a.requests.size()==1&&a.requests.get(0)==2);pass("phone fallback never retries truck");

  setup();a.devices.remove(1);a.devices.add(new AudioDeviceInfo(3,8));router.prepare(false,result);Handler.advance(500);
  check(result.ready==1&&!router.isExternal()&&a.requested.type==2);pass("A2DP media output is not treated as a microphone");

  setup();a.mode=2;router.prepare(false,result);check(result.failed==1&&a.modeCalls==0&&a.requests.isEmpty());
  pass("active telephone call is left alone");

  setup();a.mode=3;router.prepare(false,result);check(result.failed==1&&a.modeCalls==0);
  pass("other communication session is left alone");

  setup();a.grant=false;router.prepare(false,result);check(result.failed==1&&a.modeCalls==0&&a.requests.isEmpty());
  pass("denied audio focus does not start microphone");

  setup();a.mute=true;router.prepare(false,result);check(result.failed==1&&a.mute&&a.requests.isEmpty());
  pass("microphone mute is respected");

  setup();router.prepare(false,result);Handler.advance(500);a.listener.onAudioFocusChange(-2);Handler.advance(0);
  check(result.failed==1&&a.mode==0&&a.clears==1&&a.abandons==1);pass("audio focus loss releases the route");

  setup();router.prepare(false,result);AudioManager.OnAudioFocusChangeListener stale=a.listener;
  Result newer=new Result();router.prepare(true,newer);stale.onAudioFocusChange(-1);Handler.advance(500);
  check(newer.ready==1&&newer.failed==0&&result.ready==0);pass("stale focus loss cannot stop new session");

  setup();a.throwSelect=true;router.prepare(false,result);check(result.failed==1&&a.mode==0&&a.abandons==1);
  pass("route API exception restores audio mode");

  setup();a.devices.remove(1);a.devices.add(new AudioDeviceInfo(5,26));router.prepare(false,result);Handler.advance(500);
  check(result.ready==1&&router.isExternal()&&a.requested.type==26);pass("BLE headset route supported");

  setup();Build.VERSION.SDK_INT=30;router.prepare(false,result);
  check(result.ready==1&&a.requests.isEmpty()&&a.modeCalls==0&&router.promptStream()==3);
  pass("older Android keeps system default routing");

  setup();a.devices.clear();router.prepare(false,result);check(result.failed==1&&a.mode==0&&a.abandons==1);
  pass("missing devices stops cleanly");
  System.out.println(passed+" audio routing scenarios passed");
 }
}''',
}

if __name__ == '__main__':
    router = Path(__file__).resolve().parent / 'src/com/devco/field/VoiceAudioRouter.java'
    with tempfile.TemporaryDirectory(prefix='devco-audio-test-') as directory:
        root = Path(directory)
        for filename, content in STUBS.items():
            target = root / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        subprocess.run(['javac', '-d', str(root), str(router), *map(str, root.rglob('*.java'))], check=True)
        subprocess.run(['java', '-cp', str(root), 'com.devco.field.VoiceAudioRouterTest'], check=True)
