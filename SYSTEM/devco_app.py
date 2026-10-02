from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs
import html, json, os, subprocess, threading
ROOT=Path.home()/"DEVCO_FIELD"; JOBS=ROOT/"JOBS"; STATE=ROOT/".devco_app_state.json"
lock=threading.Lock(); field_proc=None; active_job=None

def jobs(): return sorted([p.name for p in JOBS.iterdir() if (p/"3_JU_FILES").is_dir()])
def count_jus(job): return len(list((JOBS/job/"3_JU_FILES").glob("*/transfer_info.txt")))
def completed(job):
    root=JOBS/job/"3_JU_FILES"; return sum((p.parent/"BILLING_AND_NOTES.txt").exists() for p in root.glob("*/transfer_info.txt"))
def page(msg=""):
    js=jobs(); selected=active_job or (js[0] if js else "")
    total=count_jus(selected) if selected else 0; done=completed(selected) if selected else 0
    running=field_proc is not None and field_proc.poll() is None
    opts=''.join(f'<option value="{html.escape(j)}" {"selected" if j==selected else ""}>{html.escape(j)}</option>' for j in js)
    return f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>DEVCO Field</title><style>
body{{font-family:system-ui;background:#0b1118;color:#eef4fa;margin:0}}main{{max-width:520px;margin:auto;padding:22px}}h1{{font-size:28px}}.card{{background:#151f2b;border-radius:18px;padding:18px;margin:14px 0}}select,button{{width:100%;font-size:18px;padding:16px;border-radius:12px;margin:7px 0}}button{{font-weight:700;border:0}}.start{{background:#36c275}}.stop{{background:#ef6262}}.muted{{color:#9fb0c0}}.big{{font-size:32px;font-weight:800}}.ok{{color:#55d98b}}</style></head><body><main>
<h1>DEVCO Field</h1><div class="card"><div class="muted">JOB</div><form method="post" action="/select"><select name="job">{opts}</select><button>Select Job</button></form></div>
<div class="card"><div class="muted">STATUS</div><div class="big {'ok' if running else ''}">{'RUNNING' if running else 'STOPPED'}</div><p>{done} completed / {total} JUs</p><form method="post" action="/{'stop' if running else 'start'}"><button class="{'stop' if running else 'start'}">{'Stop Field Mode' if running else 'Start Field Mode'}</button></form></div>
<div class="card"><b>Photo workflow</b><p class="muted">Take Solocator photos normally. GPS matching and JU recording run underneath this screen.</p></div>{'<div class="card">'+html.escape(msg)+'</div>' if msg else ''}
</main></body></html>'''

def start_field():
    global field_proc
    if not active_job: return 'Select a job first.'
    if field_proc and field_proc.poll() is None: return 'Field Mode is already running.'
    job=JOBS/active_job; env=os.environ.copy(); env.update(DEVCO_JOB=str(job),DEVCO_JOB_ID=active_job,DEVCO_JU_ROOT=str(job/'3_JU_FILES'))
    log=open(job/'1_JOB_WORKFLOW'/'field_app.log','a',buffering=1)
    field_proc=subprocess.Popen(['python',str(ROOT/'SYSTEM'/'field_workflow.py')],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    return 'Field Mode started.'
class H(BaseHTTPRequestHandler):
    def send(self,msg=''):
        b=page(msg).encode(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self): self.send()
    def do_POST(self):
        global active_job, field_proc
        n=int(self.headers.get('Content-Length','0')); data=parse_qs(self.rfile.read(n).decode())
        if self.path=='/select':
            j=data.get('job',[''])[0]; active_job=j if j in jobs() else active_job; msg='Job selected.'
        elif self.path=='/start': msg=start_field()
        elif self.path=='/stop':
            if field_proc and field_proc.poll() is None: field_proc.terminate(); msg='Field Mode stopped.'
            else: msg='Field Mode is not running.'
        else: msg='Unknown action.'
        self.send(msg)
    def log_message(self,*a): pass
if __name__=='__main__':
    js=jobs(); active_job=js[0] if js else None
    print('DEVCO Field app: http://127.0.0.1:8765',flush=True); ThreadingHTTPServer(('127.0.0.1',8765),H).serve_forever()
