import html
import json
from pathlib import Path
from voice_workflow import CLOSE_LABELS


def voice_card():
    options='<option value="">Choose the closing task</option>'+''.join('<option value="'+html.escape(key)+'">'+html.escape(label)+'</option>' for key,label in CLOSE_LABELS.items())
    return '''<div class="card" id="voice-card"><h2>VOICE CLOSEOUT</h2>
<p id="voice-status" role="status">Preparing your spoken notes and closeout…</p>
<p id="voice-heard" aria-live="polite"></p>
<button class="no" type="button" id="voice-manual">Use manual controls</button>
<div id="voice-review" hidden><h3>Review before finalizing</h3>
<p><b>Cleaned note</b></p><p id="voice-note-preview" style="white-space:pre-wrap"></p>
<p id="voice-caution" style="color:#f1c580"></p><p>Edit the note in the Notes box below if needed.</p>
<label for="voice-close" style="display:block">Closing task</label>
<select id="voice-close" style="width:100%;padding:13px;font:16px system-ui;background:#071019;color:white;border:1px solid #456071">'''+options+'''</select>
<p>Select billing codes below. Choose Trip Charge ($40) when applicable.</p>
<button id="voice-finalize" class="go" type="submit" name="close" value="" disabled>Confirm &amp; finalize JU</button>
<details><summary>Original dictation</summary><p id="voice-original" style="white-space:pre-wrap"></p></details>
</div></div>'''


def voice_script(job,ju,autostart=True):
    config=json.dumps({'job':job,'ju':ju,'autostart':autostart}).replace('</','<\\/')
    return '<script>window.devcoVoiceConfig='+config+';</script><script src="/static/voice-closeout.js"></script>'
