"""Single-stop field interface; data stays in the existing job workflow."""
import html
import json
from record_editor import photo_panel, photo_items, photo_script, PHOTO_STYLE

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
        gallery = photo_panel(job, ju, photo_items(folder, job, ju))
        active = f"""<section><small>CURRENT POLE</small><h1>JU {esc(ju)}</h1><p>{esc(pole["address"])}</p>
        <p><strong>{esc(pole.get("condition_code",""))}</strong><br>{esc(pole.get("condition_desc",""))}</p>
        <div class="row"><a href="/nav?lat={pole['lat']}&lon={pole['lon']}&ju={esc(ju)}">Navigate</a><a href="/hone">Find pole</a><a href="/map">Map</a></div>
        <h2>1. Take photos</h2><p><b id="photos">{photos}</b> photos filed under this JU</p>
        {gallery}
        <h2>2. Notes &amp; codes</h2><a class="primary" href="/billing">Review &amp; finish this JU</a>
        <p class="muted">After saving, the next unfinished JU appears here. Tap Navigate when ready.</p></section>"""
    else:
        active = '<section><h1>Finding your job &amp; pole</h1><p>Your location automatically loads the matching job and JU when you are nearby. Solocator photos can identify it too.</p><a class="primary" href="/map">Open map &amp; route</a></section>'
    st = app["timer_state"](job) if job else {}
    timer = esc(st.get("category") or "Stopped")
    controls = "".join('<button name="action" value="%s">%s</button>' % (v, label) for v,label in [("drive","Drive"),("work","Work"),("break","Break"),("stop","Stop")])
    message = '<p role="status" class="notice">'+esc(msg)+'</p>' if msg else ""
    identity = json.dumps([job,ju]).replace("</","<\\/")
    return """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>DEVCO Field</title>
<style>__PHOTO_STYLE__*{box-sizing:border-box}body{margin:0;background:#09131b;color:#edf4f7;font:17px system-ui}main{max-width:620px;margin:auto;padding:18px}header{display:flex;align-items:center;justify-content:space-between}header b{color:#4cdd92}section,details{background:#13232e;border:1px solid #304754;border-radius:14px;padding:18px;margin:15px 0}h1{margin:6px 0;font-size:30px}h2{font-size:19px;margin:24px 0 8px}p{line-height:1.45}small,.muted{color:#a8bdc9}.muted{font-size:14px}a,button{display:block;border:1px solid #456071;border-radius:10px;padding:14px;color:white;background:#203846;text-align:center;text-decoration:none;font:600 16px system-ui;min-height:48px}.primary{background:#4cdd92;color:#06180e;border:0}.row{display:flex;gap:8px}.row>*{flex:1}.notice{padding:12px;border-left:4px solid #f1b866;background:#352b19}select{width:100%;padding:12px;background:#09131b;color:white;font:16px system-ui;margin:12px 0}summary{cursor:pointer;font-weight:600}#connection{font-size:14px;color:#a8bdc9}</style></head><body><main>
<header><b>DEVCO FIELD</b><a href="/records">JU Files</a></header><div class="row" style="margin-top:14px"><a href="/">Field</a><a href="/records">JU Files</a><a href="/map">Map</a></div>
<p id="location" role="status">Finding your location…</p><p id="connection">Photo filing connected</p>__MESSAGE____ACTIVE__
<details><summary>Job &amp; time · __COUNT__ completed</summary><p>Current job: __JOB__</p>
<form method="post" action="/select"><select name="job">__OPTIONS__</select><button>Switch job</button></form>
<p>Timer: __TIMER__</p><form class="row" method="post" action="/timer">__CONTROLS__</form></details>
</main><script>
const identity=__IDENTITY__;
const saved=new URLSearchParams(location.search).get("saved");
if(saved){try{localStorage.removeItem("devco-closeout:"+saved);}catch(e){}history.replaceState(null,"","/");}
let locating=false,lastLocate=0;
if(navigator.geolocation){
 navigator.geolocation.watchPosition(async p=>{
  if(document.hidden||locating||Date.now()-lastLocate<5000)return;
  locating=true;lastLocate=Date.now();
  try{
   const q=new URLSearchParams({auto:'1',lat:p.coords.latitude,lon:p.coords.longitude,accuracy:p.coords.accuracy});
   const r=await fetch('/gps-nearest?'+q,{cache:'no-store'}),s=await r.json();
   document.getElementById('location').textContent=s.message||s.error||'Waiting for GPS';
   if(s.switched)location.replace('/');
  }catch(e){document.getElementById('location').textContent='Could not locate your JU. Retrying with the next GPS update.';}
  finally{locating=false;}
 },e=>{document.getElementById('location').textContent=e.code===1?'Allow location for DEVCO Field to load jobs automatically. You can also use Solocator or the map.':'Waiting for GPS — move where your phone can get a location.';},{enableHighAccuracy:true,maximumAge:3000,timeout:15000});
}else{document.getElementById('location').textContent='Live location unavailable. Use Solocator or choose from the map.';}
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
</script>__PHOTO_SCRIPT__</body></html>""".replace("__PHOTO_STYLE__",PHOTO_STYLE).replace("__PHOTO_SCRIPT__",photo_script(job,ju) if pole else "").replace("__MESSAGE__",message).replace("__ACTIVE__",active).replace("__COUNT__",str(count)).replace("__JOB__",esc(job or "None")).replace("__OPTIONS__",options).replace("__TIMER__",timer).replace("__CONTROLS__",controls).replace("__IDENTITY__",identity)


def billing_draft_script(job, ju):
    key=json.dumps("devco-closeout:"+str(job)+":"+str(ju)).replace("</","<\\/")
    return """<script>
const f=document.querySelector('form[action="/finish"]'),key=__KEY__;
if(f){
 const fields=[...f.querySelectorAll('input:not([type=hidden]),textarea')],note=f.elements.note,status=document.getElementById('note-save-status');
 let timer,chain=Promise.resolve(),submitting=false,ready=false,lastSaved=note.value;
 try{const saved=JSON.parse(localStorage.getItem(key)||'{}');fields.forEach(e=>{const k=e.name+(e.type==='checkbox'?':'+e.value:'');if(k in saved){if(e.type==='checkbox')e.checked=saved[k];else e.value=saved[k];}});}catch(e){}
 function stash(){const d={};fields.forEach(e=>{d[e.name+(e.type==='checkbox'?':'+e.value:'')]=e.type==='checkbox'?e.checked:e.value;});try{localStorage.setItem(key,JSON.stringify(d));}catch(e){}}
 function save(){
  clearTimeout(timer);stash();
  const text=note.value;
  chain=chain.catch(()=>{}).then(async()=>{
   if(text===lastSaved){status.textContent='Note saved';return;}
   status.textContent='Saving note…';
   const body=new URLSearchParams({job:f.elements.job.value,ju:f.elements.ju.value,note:text});
   const r=await fetch('/note',{method:'POST',body,keepalive:true});
   if(!r.ok)throw Error('Save failed');
   lastSaved=text;status.textContent=note.value===text?'Note saved':'Saving note…';
  });
  chain.catch(()=>{status.textContent='Note not saved to JU yet — retrying. Draft kept on this screen.';});
  return chain;
 }
 f.addEventListener('input',()=>{stash();clearTimeout(timer);status.textContent='Saving note…';timer=setTimeout(()=>save(),500);});
 note.addEventListener('blur',()=>save());
 document.addEventListener('visibilitychange',()=>{if(document.hidden)save();});
 setInterval(()=>{if(note.value!==lastSaved&&!submitting)save();},5000);
 f.addEventListener('submit',async e=>{
  if(ready)return;
  e.preventDefault();if(submitting)return;submitting=true;
  const button=e.submitter||document.activeElement;
  try{
   await save();ready=true;
   const hidden=document.createElement('input');hidden.type='hidden';hidden.name='close';hidden.value=button.value;f.appendChild(hidden);
   HTMLFormElement.prototype.submit.call(f);
  }catch(error){submitting=false;status.textContent='Could not save. Your draft is kept — tap the completion button again when connected.';}
 });
 if(note.value!==lastSaved)save();
}
</script>""".replace("__KEY__",key)
