"""Single-stop field interface; data stays in the existing job workflow."""
import html
import json

def page(app, msg=""):
    esc = html.escape
    job = app["active_job"]
    ju = app["active_ju"]
    points = app["ju_points"](job) if job else []
    pole = next((p for p in points if p["ju"] == ju), None)
    options = "".join('<option value="%s"%s>%s</option>' % (esc(j), " selected" if j == job else "", esc(j)) for j in app["jobs"]())
    count = sum(p["done"] for p in points)
    if pole:
        folder = app["_ju_folder"](job, ju)
        photos = sum(p.is_file() for p in (folder/"photos").glob("*")) if folder else 0
        active = f"""<section><small>CURRENT POLE</small><h1>JU {esc(ju)}</h1><p>{esc(pole["address"])}</p>
        <p><strong>{esc(pole.get("condition_code",""))}</strong><br>{esc(pole.get("condition_desc",""))}</p>
        <div class="row"><a href="/nav?lat={pole['lat']}&lon={pole['lon']}&ju={esc(ju)}">Navigate</a><a href="/hone">Find pole</a><a href="/map">Map</a></div>
        <h2>1. Take photos</h2><p><b id="photos">{photos}</b> photos filed under this JU</p>
        <a class="primary" href="/camera">Open Solocator</a>
        <h2>2. Notes &amp; codes</h2><a class="primary" href="/billing">Review &amp; finish this JU</a>
        <p class="muted">After saving, the next unfinished JU appears here. Tap Navigate when ready.</p></section>"""
    else:
        active = '<section><h1>Choose your first pole</h1><p>Select a JU on the map. New Solocator photos can also identify the JU by GPS.</p><a class="primary" href="/map">Open map &amp; route</a></section>'
    st = app["timer_state"](job) if job else {}
    timer = esc(st.get("category") or "Stopped")
    controls = "".join('<button name="action" value="%s">%s</button>' % (v, label) for v,label in [("drive","Drive"),("work","Work"),("break","Break"),("stop","Stop")])
    message = '<p role="status" class="notice">'+esc(msg)+'</p>' if msg else ""
    identity = json.dumps([job,ju]).replace("</","<\\/")
    return """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>DEVCO Field</title>
<style>*{box-sizing:border-box}body{margin:0;background:#09131b;color:#edf4f7;font:17px system-ui}main{max-width:620px;margin:auto;padding:18px}header{display:flex;align-items:center;justify-content:space-between}header b{color:#4cdd92}section,details{background:#13232e;border:1px solid #304754;border-radius:14px;padding:18px;margin:15px 0}h1{margin:6px 0;font-size:30px}h2{font-size:19px;margin:24px 0 8px}p{line-height:1.45}small,.muted{color:#a8bdc9}.muted{font-size:14px}a,button{display:block;border:1px solid #456071;border-radius:10px;padding:14px;color:white;background:#203846;text-align:center;text-decoration:none;font:600 16px system-ui;min-height:48px}.primary{background:#4cdd92;color:#06180e;border:0}.row{display:flex;gap:8px}.row>*{flex:1}.notice{padding:12px;border-left:4px solid #f1b866;background:#352b19}select{width:100%;padding:12px;background:#09131b;color:white;font:16px system-ui;margin:12px 0}summary{cursor:pointer;font-weight:600}#connection{font-size:14px;color:#a8bdc9}</style></head><body><main>
<header><b>DEVCO FIELD</b><a href="/map">Map &amp; route</a></header>
<p id="connection">Photo filing connected</p>__MESSAGE____ACTIVE__
<details><summary>Job &amp; time · __COUNT__ completed</summary><p>Current job: __JOB__</p>
<form method="post" action="/select"><select name="job">__OPTIONS__</select><button>Switch job</button></form>
<p>Timer: __TIMER__</p><form class="row" method="post" action="/timer">__CONTROLS__</form></details>
</main><script>
const identity=__IDENTITY__;
const saved=new URLSearchParams(location.search).get("saved");
if(saved){try{localStorage.removeItem("devco-closeout:"+saved);}catch(e){}history.replaceState(null,"","/");}
let checking=false;
async function check(){
 if(checking||document.hidden)return;
 checking=true;
 try{
  const response=await fetch('/status',{cache:'no-store'});
  if(!response.ok)throw Error('connection');
  const s=await response.json();
  document.getElementById('connection').textContent=s.notice||'Watching for new Solocator photos';
  if(JSON.stringify([s.job,s.ju])!==JSON.stringify(identity)){location.replace('/');return;}
  const el=document.getElementById('photos');if(el)el.textContent=s.photos;
 }catch(e){document.getElementById('connection').textContent='Connection lost — reopen Termux, then return here. Saved records remain on your phone.';}
 finally{checking=false;}
}
setInterval(check,3000);document.addEventListener('visibilitychange',check);check();
</script></body></html>""".replace("__MESSAGE__",message).replace("__ACTIVE__",active).replace("__COUNT__",str(count)).replace("__JOB__",esc(job or "None")).replace("__OPTIONS__",options).replace("__TIMER__",timer).replace("__CONTROLS__",controls).replace("__IDENTITY__",identity)

def billing_draft_script(job, ju):
    key = json.dumps("devco-closeout:"+str(job)+":"+str(ju)).replace("</","<\\/")
    return """<script>
const f=document.querySelector('form[action="/finish"]'),key=__KEY__;
if(f){
 const fields=[...f.querySelectorAll('input:not([type=hidden]),textarea')];
 try{const saved=JSON.parse(localStorage.getItem(key)||'{}');fields.forEach(e=>{const k=e.name+(e.type==='checkbox'?':'+e.value:'');if(k in saved){if(e.type==='checkbox')e.checked=saved[k];else e.value=saved[k];}});}catch(e){}
 f.addEventListener('input',()=>{const d={};fields.forEach(e=>{d[e.name+(e.type==='checkbox'?':'+e.value:'')]=e.type==='checkbox'?e.checked:e.value;});try{localStorage.setItem(key,JSON.stringify(d));}catch(e){}});
}
</script>""".replace("__KEY__",key)
