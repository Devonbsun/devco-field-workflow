from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import html, json, os, subprocess, threading, zipfile, time, csv, math
from datetime import datetime
import xml.etree.ElementTree as ET
ROOT=Path.home()/"DEVCO_FIELD"; JOBS=ROOT/"JOBS"; STATE=ROOT/".devco_app_state.json"
lock=threading.Lock(); field_proc=None; active_job=None; active_ju=None


def _time_dir(job):
    d=JOBS/job/"1_JOB_WORKFLOW"; d.mkdir(parents=True,exist_ok=True); return d
def _time_state_path(job): return _time_dir(job)/"TIME_STATE.json"
def _time_log_path(job): return _time_dir(job)/"TIME_TRACKING.csv"

def timer_state(job):
    try:
        d=json.loads(_time_state_path(job).read_text())
        d["elapsed"]=max(0,time.time()-float(d.get("start_ts",0))) if d.get("running") else 0
        return d
    except Exception:
        return {"running":False,"category":"","ju":"","start_ts":0,"elapsed":0}

def _append_time(job,state,end_ts):
    start=float(state.get("start_ts",end_ts)); secs=max(0,end_ts-start)
    path=_time_log_path(job); fresh=not path.exists()
    with path.open("a",newline="") as f:
        w=csv.writer(f)
        if fresh: w.writerow(["Date","Job","JU","Category","Start","End","Seconds"])
        w.writerow([datetime.fromtimestamp(start).strftime("%Y-%m-%d"),job,state.get("ju",""),state.get("category","Other"),
                    datetime.fromtimestamp(start).isoformat(timespec="seconds"),datetime.fromtimestamp(end_ts).isoformat(timespec="seconds"),round(secs,1)])

def stop_timer(job):
    with lock:
        st=timer_state(job)
        if st.get("running"): _append_time(job,st,time.time())
        _time_state_path(job).write_text(json.dumps({"running":False,"category":"","ju":"","start_ts":0}))
    return st

def start_timer(job,category,ju=""):
    category=category.title()
    if category not in ("Drive","Work","Break","Other"): category="Other"
    with lock:
        old=timer_state(job); now=time.time()
        if old.get("running") and old.get("category")==category and old.get("ju","")==ju: return old
        if old.get("running"): _append_time(job,old,now)
        st={"running":True,"category":category,"ju":ju or "","start_ts":now}
        _time_state_path(job).write_text(json.dumps(st))
    return st

def today_summary(job):
    totals={"Drive":0.0,"Work":0.0,"Break":0.0,"Other":0.0}
    today=datetime.now().strftime("%Y-%m-%d"); path=_time_log_path(job)
    if path.exists():
        try:
            with path.open(newline="") as f:
                for r in csv.DictReader(f):
                    if r.get("Date")==today and r.get("Category") in totals:
                        totals[r["Category"]]+=float(r.get("Seconds") or 0)
        except Exception: pass
    st=timer_state(job)
    if st.get("running") and st.get("category") in totals: totals[st["category"]]+=st.get("elapsed",0)
    return totals

def ju_times(job,ju):
    totals={"Drive":0.0,"Work":0.0}; path=_time_log_path(job)
    if path.exists():
        try:
            with path.open(newline="") as f:
                for r in csv.DictReader(f):
                    if r.get("JU")==ju and r.get("Category") in totals:
                        totals[r["Category"]]+=float(r.get("Seconds") or 0)
        except Exception: pass
    st=timer_state(job)
    if st.get("running") and st.get("ju")==ju and st.get("category") in totals: totals[st["category"]]+=st.get("elapsed",0)
    return totals

def fmt_time(sec):
    sec=int(max(0,sec)); h,rem=divmod(sec,3600); m,s=divmod(rem,60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def jobs(): return sorted([p.name for p in JOBS.iterdir() if (p/"3_JU_FILES").is_dir()])
def count_jus(job): return len(list((JOBS/job/"3_JU_FILES").glob("*/transfer_info.txt")))
def completed(job):
    root=JOBS/job/"3_JU_FILES"; return sum((p.parent/"BILLING_AND_NOTES.txt").exists() for p in root.glob("*/transfer_info.txt"))

def ju_points(job):
    out=[]
    root=JOBS/job/"3_JU_FILES"
    for info in root.glob("*/transfer_info.txt"):
        try:
            vals={}
            for line in info.read_text(errors="ignore").splitlines():
                if ":" in line:
                    k,v=line.split(":",1); vals[k.strip()]=v.strip()
            lat=float(vals.get("Latitude","")); lon=float(vals.get("Longitude",""))
            ju=vals.get("JU Record", info.parent.name.split(" - ",1)[0])
            address=vals.get("Address","")
            done=(info.parent/"BILLING_AND_NOTES.txt").exists()
            out.append({"ju":ju,"address":address,"lat":lat,"lon":lon,"done":done})
        except Exception:
            pass
    return out


def route_points(job):
    xlsx=JOBS/job/"2_ROUTE"/f"{job}_ROUTE.xlsx"
    if not xlsx.exists(): return []
    try:
        with zipfile.ZipFile(xlsx) as z:
            root=ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
            ns={"m":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            rows=[]
            for row in root.findall(".//m:row",ns):
                vals={}
                for c in row.findall("m:c",ns):
                    ref=c.get("r",""); col=''.join(x for x in ref if x.isalpha())
                    v=c.find("m:v",ns)
                    inline=c.find("m:is/m:t",ns)
                    vals[col]=(inline.text if inline is not None else (v.text if v is not None else ""))
                if vals.get("B") and vals.get("D") and vals.get("E") and vals.get("B")!="JU":
                    try: rows.append({"stop":vals.get("A",""),"ju":str(vals["B"]),"address":vals.get("C",""),"lat":float(vals["D"]),"lon":float(vals["E"])})
                    except: pass
            return rows
    except Exception: return []

def _miles(a,b):
    # Fast haversine distance for route optimization.
    r=3958.7613
    p1,p2=math.radians(a["lat"]),math.radians(b["lat"])
    dp=math.radians(b["lat"]-a["lat"]); dl=math.radians(b["lon"]-a["lon"])
    x=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(min(1,math.sqrt(x)))

def _route_miles(seq):
    return sum(_miles(seq[i-1],seq[i]) for i in range(1,len(seq)))

def _route_plan_path(job):
    return _time_dir(job)/"OPTIMIZED_ROUTE.json"

def _build_optimized_route(job):
    pts=[dict(x) for x in ju_points(job) if not x["done"]]
    if not pts: return []
    order={r["ju"]:i for i,r in enumerate(route_points(job))}
    pts.sort(key=lambda x:order.get(x["ju"],10**9))
    start=pts[0]
    remaining=pts[1:]; route=[start]; current=start
    while remaining:
        nxt=min(remaining,key=lambda x:_miles(current,x))
        route.append(nxt); remaining.remove(nxt); current=nxt
    n=len(route)
    for _ in range(4):
        improved=False
        for i in range(1,n-2):
            a,b=route[i-1],route[i]
            for k in range(i+1,min(n-1,i+70)):
                c,d=route[k],route[k+1]
                if _miles(a,b)+_miles(c,d) > _miles(a,c)+_miles(b,d)+0.01:
                    route[i:k+1]=reversed(route[i:k+1]); improved=True
        if not improved: break
    return route

def optimized_route(job):
    # Persist one master route. Selecting/visiting a JU never rebuilds it.
    # New JUs are inserted into the existing route at the cheapest position.
    path=_route_plan_path(job)
    current={x["ju"]:dict(x) for x in ju_points(job)}
    try:
        saved=json.loads(path.read_text()) if path.exists() else []
    except Exception:
        saved=[]
    if not saved:
        saved=_build_optimized_route(job)
    # Refresh coordinates/status while preserving route order.
    plan=[current[x["ju"]] for x in saved if x.get("ju") in current]
    known={x["ju"] for x in plan}
    for ju,p in current.items():
        if ju in known: continue
        if not plan: plan.append(p); continue
        best_i=len(plan); best_cost=float("inf")
        for i in range(len(plan)+1):
            if i==0: cost=_miles(p,plan[0])
            elif i==len(plan): cost=_miles(plan[-1],p)
            else: cost=_miles(plan[i-1],p)+_miles(p,plan[i])-_miles(plan[i-1],plan[i])
            if cost<best_cost: best_cost=cost; best_i=i
        plan.insert(best_i,p)
    path.write_text(json.dumps(plan,indent=2))
    return plan

def route40(job):
    # Sliding window over the persistent route: completed stops drop out and
    # the next unfinished stop is pulled in. The remaining route never reshuffles.
    plan=optimized_route(job)
    current={x["ju"]:x for x in ju_points(job)}
    unfinished=[current[x["ju"]] for x in plan if x["ju"] in current and not current[x["ju"]]["done"]]
    return unfinished[:40]

def launch_google_maps(lat, lon, ju=""):
    try:
        lat=float(lat); lon=float(lon)
    except Exception:
        return False
    uri=f"google.navigation:q={lat},{lon}&mode=d"
    try:
        # Bring Maps up as a fresh foreground task. This avoids the DEVCO
        # WebView immediately reclaiming focus after /nav redirects.
        subprocess.run(["am","force-stop","com.google.android.apps.maps"],
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3)
        r=subprocess.run(["am","start","-W","-a","android.intent.action.VIEW","-d",uri,
                          "-p","com.google.android.apps.maps","-f","0x10000000"],
                         stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
        if r.returncode==0: return True
    except Exception:
        pass
    try:
        url=f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}&travelmode=driving"
        subprocess.Popen(["termux-open-url",url],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def map_page():
    js=jobs(); selected=active_job or (js[0] if js else "")
    points=ju_points(selected) if selected else []
    route=route40(selected) if selected else []
    data=json.dumps(points).replace("</","<\\/")
    route_data=json.dumps(route).replace("</","<\\/")
    return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DEVCO Map</title>
<link rel="stylesheet" href="/static/leaflet.css">
<style>html,body,#map{{height:100%;margin:0}}body{{font-family:system-ui}}#bar{{position:absolute;z-index:1000;top:10px;left:10px;right:10px;background:#071019ee;padding:12px;border-radius:16px;border:1px solid #314653;box-shadow:0 8px 24px #0008;color:white;display:flex;gap:8px;align-items:center}}#bar a{{color:white;text-decoration:none;background:#26384b;padding:10px 12px;border-radius:10px}}#bar span{{flex:1}}.nav,.activate{{display:inline-block;padding:9px 12px;background:#36c275;color:#07140d!important;border-radius:9px;text-decoration:none;font-weight:700;border:0;margin:3px}}.activate{{background:#168cff;color:white!important}}</style></head>
<body><div id="bar"><a href="/">← Dashboard</a><span><b>{html.escape(selected)}</b> · {len(points)} JUs · <b>{len(route)}-STOP OPTIMIZED ROUTE</b> · <b>GPS/OFFLINE READY</b></span></div><div id="map"></div>
<script src="/static/leaflet.js"></script><script>
const pts={data}; const route={route_data}; const map=L.map('map');
const tiles=L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:20,attribution:'© OpenStreetMap'}});
if(navigator.onLine) tiles.addTo(map);
map.getContainer().style.background='#101b23';
window.addEventListener('online',()=>{{if(!map.hasLayer(tiles))tiles.addTo(map)}});
window.addEventListener('offline',()=>{{if(map.hasLayer(tiles))map.removeLayer(tiles)}});
const bounds=[];
if(route.length){{
  const line=route.map(r=>[r.lat,r.lon]);
  L.polyline(line,{{color:'#20e66b',weight:5,opacity:.85}}).addTo(map);
  route.forEach((r,i)=>{{
    let rm=L.marker([r.lat,r.lon],{{icon:L.divIcon({{className:'',html:'<div style="width:30px;height:30px;border-radius:50%;background:#071019;color:#20e66b;border:2px solid #20e66b;display:grid;place-items:center;font:900 12px system-ui;box-shadow:0 2px 8px #000;cursor:pointer">'+(i+1)+'</div>',iconSize:[30,30],iconAnchor:[15,15]}})}}).addTo(map);
    rm.bindTooltip('Stop '+(i+1)+' · JU '+r.ju);
    rm.bindPopup('<b>Route Stop '+(i+1)+'</b><br>JU '+r.ju+'<br>'+r.address+'<br><br><form method="post" action="/activate" style="display:inline"><input type="hidden" name="ju" value="'+r.ju+'"><button class="activate">Make Active JU</button></form><a class="nav" href="/nav?lat='+r.lat+'&lon='+r.lon+'&ju='+encodeURIComponent(r.ju)+'">Navigate</a>');
  }});
}}
pts.forEach(p=>{{let m=L.circleMarker([p.lat,p.lon],{{radius:p.done?7:9,color:p.done?'#6b7b88':'#e53935',fillColor:p.done?'#6b7b88':'#ff3b30',fillOpacity:.9,weight:3}}).addTo(map);
m.bindPopup('<b>JU '+p.ju+'</b><br>'+p.address+'<br><b>'+(p.done?'COMPLETED':'NOT COMPLETE')+'</b><br><br><form method="post" action="/activate" style="display:inline"><input type="hidden" name="ju" value="'+p.ju+'"><button class="activate">Make Active JU</button></form><a class="nav" href="/nav?lat='+p.lat+'&lon='+p.lon+'&ju='+encodeURIComponent(p.ju)+'">Navigate</a>'); bounds.push([p.lat,p.lon]);}});
if(bounds.length) map.fitBounds(bounds,{{padding:[25,25]}}); else map.setView([41.6,-93.6],9);
if(navigator.geolocation) navigator.geolocation.watchPosition(x=>{{let q=[x.coords.latitude,x.coords.longitude]; if(window.me) window.me.setLatLng(q); else window.me=L.circleMarker(q,{{radius:8,color:'#168cff',fillColor:'#168cff',fillOpacity:1}}).addTo(map).bindPopup('You are here');}},()=>{{}},{{enableHighAccuracy:true}});
</script></body></html>"""

def active_card():
    if not active_ju or not active_job:
        return '<div class="card"><div class="muted">ACTIVE JU</div><div class="big">None selected</div><p class="muted">Open the map and tap a JU to make it active.</p></div>'
    match=next((x for x in ju_points(active_job) if x["ju"]==active_ju),None)
    if not match: return ''
    nav=f'https://www.google.com/maps/dir/?api=1&destination={match["lat"]},{match["lon"]}&travelmode=driving'
    state='COMPLETED' if match["done"] else 'NOT COMPLETE'
    return f'<div class="card"><div class="muted">ACTIVE JU</div><div class="big">{html.escape(match["ju"])}</div><p>{html.escape(match["address"])}</p><p><b>{state}</b></p><a href="/hone" style="display:block;text-align:center;background:#168cff;color:white;text-decoration:none;font-weight:800;padding:16px;border-radius:12px;margin-bottom:9px">🎯 Hone In to JU</a><a href="{nav}" style="display:block;text-align:center;background:#36c275;color:#07140d;text-decoration:none;font-weight:800;padding:14px;border-radius:12px">Road Navigation</a></div>'

def hone_page():
    if not active_job or not active_ju:
        return '<html><body style="font-family:system-ui;background:#0b1118;color:white;padding:25px"><h2>No active JU</h2><a style="color:#6cf" href="/map">Select one from the map</a></body></html>'
    q=next((x for x in ju_points(active_job) if x["ju"]==active_ju),None)
    if not q: return '<html><body>JU not found.</body></html>'
    data=json.dumps(q)
    return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"><title>Hone to JU</title>
<style>html,body{{margin:0;height:100%;background:#071019;color:white;font-family:system-ui;overflow:hidden}}#top{{position:absolute;z-index:2;top:0;left:0;right:0;padding:14px;text-align:center;background:#071019dd}}#ju{{font-size:18px;font-weight:800}}#dist{{font-size:54px;font-weight:900;line-height:1}}#accuracy{{color:#9fb0c0;font-size:13px}}#stage{{height:100%;display:flex;align-items:center;justify-content:center;flex-direction:column}}#arrow{{width:0;height:0;border-left:72px solid transparent;border-right:72px solid transparent;border-bottom:185px solid #20e66b;transform-origin:50% 58%;filter:drop-shadow(0 0 18px #20e66b88)}}#bearing{{font-size:20px;font-weight:700;margin-top:20px}}#msg{{font-size:18px;text-align:center;padding:12px;max-width:90%}}#back{{position:absolute;z-index:3;left:12px;top:12px;color:white;text-decoration:none;background:#26384b;padding:9px 12px;border-radius:10px}}.hit #arrow{{font-size:120px}}.hit #dist{{font-size:65px}}</style></head>
<body><a id="back" href="/">←</a><div id="top"><div id="ju">JU {html.escape(q["ju"])} · {html.escape(q["address"])}</div><div id="dist">-- m</div><div id="accuracy">Waiting for GPS…</div></div>
<div id="stage"><div id="arrow"></div><div id="bearing">Move toward the arrow</div><div id="msg">Allow precise location. Hold the phone flat and walk a few steps so direction can stabilize.</div></div>
<script>
const target={data}; let heading=null,last=null;
function rad(x){{return x*Math.PI/180}} function deg(x){{return x*180/Math.PI}}
function distance(a,b,c,d){{let R=6371000,p1=rad(a),p2=rad(c),dp=rad(c-a),dl=rad(d-b);let x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x));}}
function bearing(a,b,c,d){{let p1=rad(a),p2=rad(c),dl=rad(d-b);return (deg(Math.atan2(Math.sin(dl)*Math.cos(p2),Math.cos(p1)*Math.sin(p2)-Math.sin(p1)*Math.cos(p2)*Math.cos(dl)))+360)%360;}}
function render(pos){{let lat=pos.coords.latitude,lon=pos.coords.longitude,d=distance(lat,lon,target.lat,target.lon),br=bearing(lat,lon,target.lat,target.lon);document.getElementById('dist').textContent=d<100?d.toFixed(1)+' m':Math.round(d)+' m';document.getElementById('accuracy').textContent='GPS accuracy ±'+Math.round(pos.coords.accuracy)+' m';let h=heading;if(h==null && pos.coords.heading!=null && !isNaN(pos.coords.heading))h=pos.coords.heading;if(h==null && last) h=bearing(last[0],last[1],lat,lon);if(h!=null){{let turn=((br-h+540)%360)-180;document.getElementById('arrow').style.transform='rotate('+turn+'deg)';document.getElementById('bearing').textContent=Math.abs(turn)<15?'Straight ahead':(turn>0?'Turn right':'Turn left');}} last=[lat,lon];if(d<=15 && pos.coords.accuracy<=25 && !window.workStarted){{window.workStarted=true;fetch('/timer',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:'action=work'}}).catch(()=>{{}});}} if(d<=3){{document.body.classList.add('hit');document.getElementById('arrow').style.border='5px solid #20e66b';document.getElementById('arrow').style.borderRadius='50%';document.getElementById('arrow').style.width='110px';document.getElementById('arrow').style.height='110px';document.getElementById('arrow').style.transform='none';document.getElementById('bearing').textContent='TARGET — WITHIN 3 METERS';document.getElementById('msg').textContent='You are at the JU coordinate. GPS accuracy can be larger than the remaining distance.';}}}}
if(window.DeviceOrientationEvent) window.addEventListener('deviceorientationabsolute',e=>{{if(e.alpha!=null)heading=(360-e.alpha)%360;}},true);
navigator.geolocation.watchPosition(render,e=>{{document.getElementById('msg').textContent='Location unavailable: '+e.message;}},{{enableHighAccuracy:true,maximumAge:0,timeout:10000}});
</script></body></html>"""

def page(msg=""):
    js=jobs(); selected=active_job or (js[0] if js else "")
    total=count_jus(selected) if selected else 0; done=completed(selected) if selected else 0; remain=max(0,total-done)
    running=field_proc is not None and field_proc.poll() is None
    tstate=timer_state(selected) if selected else {"running":False,"category":"","ju":"","elapsed":0}
    daily=today_summary(selected) if selected else {"Drive":0,"Work":0,"Break":0,"Other":0}
    opts=''.join(f'<option value="{html.escape(j)}" {"selected" if j==selected else ""}>{html.escape(j)}</option>' for j in js)
    active=next((x for x in ju_points(selected) if x["ju"]==active_ju),None) if active_ju and selected else None
    if active:
        nav=f'https://www.google.com/maps/dir/?api=1&destination={active["lat"]},{active["lon"]}&travelmode=driving'
        jt=ju_times(selected,active["ju"])
        active_html=f'<section class="hero"><div class="eyebrow">ACTIVE JU</div><div class="ju">{html.escape(active["ju"])}</div><div class="addr">📍 {html.escape(active["address"])}</div><div class="pill">{"✓ COMPLETED" if active["done"] else "● INCOMPLETE"}</div><div class="jutimes"><span>🚙 Drive {fmt_time(jt["Drive"])}</span><span>🛠 Work {fmt_time(jt["Work"])}</span></div><div class="actions"><a class="primary" href="/hone">⌖ Hone In</a><a class="secondary" href="/nav?lat={active["lat"]}&lon={active["lon"]}&ju={html.escape(active["ju"])}">➤ Google Maps</a></div><a class="secondary wide" href="/map">◈ Show Route 40</a></section>'
    else: active_html='<section class="hero"><div class="eyebrow">ACTIVE JU</div><div class="ju">No JU selected</div><div class="addr">Open the map and choose a pole to begin.</div><a class="primary wide" href="/map">Open Job Map</a></section>'
    timer_label=(tstate.get("category") or "Stopped") + ((" · JU "+tstate.get("ju","")) if tstate.get("ju") else "")
    timer_html=f"""<div class="timerpanel"><div class="timerhead"><div><div class="eyebrow">DAILY TIME</div><b>{html.escape(timer_label)}</b></div><div class="liveclock" id="liveclock">{fmt_time(tstate.get("elapsed",0)) if tstate.get("running") else fmt_time(sum(daily.values()))}</div></div><div class="cats"><div class="cat">DRIVE<b>{fmt_time(daily["Drive"])}</b></div><div class="cat">WORK<b>{fmt_time(daily["Work"])}</b></div><div class="cat">BREAK<b>{fmt_time(daily["Break"])}</b></div><div class="cat">OTHER<b>{fmt_time(daily["Other"])}</b></div></div><div class="timerbuttons"><form method="post" action="/timer"><input type="hidden" name="action" value="drive"><button>🚙 Drive</button></form><form method="post" action="/timer"><input type="hidden" name="action" value="work"><button class="work">🛠 Work</button></form><form method="post" action="/timer"><input type="hidden" name="action" value="break"><button class="break">☕ Break</button></form><form method="post" action="/timer"><input type="hidden" name="action" value="stop"><button>■ Stop</button></form></div></div>"""
    return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>DEVCO Field</title><style>
*{{box-sizing:border-box}}html,body{{margin:0;background:#050b10;color:#f5f9fc;font-family:system-ui}}body{{background:radial-gradient(circle at top,#123044,#07131b 38%,#050b10 70%);min-height:100vh;padding-bottom:80px}}main{{max-width:600px;margin:auto;padding:16px}}.top{{display:flex;justify-content:space-between;align-items:center;padding:8px 2px 15px}}.brand{{font-size:27px;font-weight:900}}.brand b{{color:#20e66b}}.signal{{font-size:11px;color:#20e66b;border:1px solid #18743b;background:#092618;padding:7px 9px;border-radius:99px}}.card,.job,.hero,.tool,.mode,.stat{{background:linear-gradient(145deg,#10212c,#09151d);border:1px solid #263d49;box-shadow:0 10px 28px #0007}}.job,.hero,.mode{{border-radius:19px;padding:15px}}.job form{{display:flex;gap:8px}}select{{flex:1;min-width:0;background:#132630;color:white;border:1px solid #334b58;border-radius:12px;padding:13px;font-size:15px;font-weight:700}}button{{border:0;border-radius:11px;padding:12px 14px;font-weight:850}}.job button{{background:#203642;color:white}}.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin:11px 0 14px}}.stat{{border-radius:16px;padding:12px 6px;text-align:center}}.num{{font-size:24px;font-weight:950}}.label,.eyebrow{{font-size:10px;color:#8fa7b5;letter-spacing:1px;font-weight:800}}.green{{color:#20e66b}}.orange{{color:#ff9d2e}}.ju{{font-size:31px;font-weight:950;margin:4px 0}}.addr{{color:#c3d1d9;margin-bottom:12px}}.pill{{display:inline-block;background:#4b250d;color:#ffb25b;border:1px solid #a44c15;padding:5px 9px;border-radius:8px;font-size:11px;font-weight:900;margin-bottom:14px}}.actions{{display:grid;grid-template-columns:1fr 1fr;gap:9px}}a{{text-decoration:none}}.primary,.secondary{{display:block;text-align:center;border-radius:12px;padding:14px;font-weight:900}}.primary{{background:linear-gradient(135deg,#0ab847,#20e66b);color:#021009}}.secondary{{background:#142a36;color:white;border:1px solid #35505f}}.wide{{margin-top:14px}}.sectiontitle{{font-size:11px;color:#8fa7b5;font-weight:850;letter-spacing:1.2px;margin:18px 3px 8px}}.tools{{display:grid;grid-template-columns:1fr 1fr;gap:9px}}.tool{{border-radius:17px;padding:15px;color:white;min-height:100px}}.tool.map{{border-color:#167443;background:linear-gradient(145deg,#0d2b20,#0b1d20)}}.ico{{font-size:25px;margin-bottom:8px}}.tool b{{display:block}}.tool small{{color:#91a7b5}}.mode{{margin-top:12px;display:flex;align-items:center;gap:10px}}.dot{{width:10px;height:10px;border-radius:50%;background:{'#20e66b' if running else '#667985'}}}.modeinfo{{flex:1}}.modeinfo small{{display:block;color:#91a7b5}}.start{{background:#20e66b;color:#021009}}.stop{{background:#ef5350;color:white}}.jutimes{{display:flex;gap:15px;color:#a9bbc6;font-size:12px;margin:-4px 0 13px}}.timerpanel{{margin-top:12px;background:linear-gradient(145deg,#0d1f29,#09151d);border:1px solid #28414f;border-radius:19px;padding:15px}}.timerhead{{display:flex;justify-content:space-between;align-items:center}}.liveclock{{font-size:26px;font-weight:950;color:#20e66b}}.cats{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:11px}}.cat{{background:#101d25;border-radius:10px;padding:8px 3px;text-align:center;font-size:9px;color:#91a7b5}}.cat b{{display:block;color:white;font-size:13px;margin-top:2px}}.timerbuttons{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:10px}}.timerbuttons form{{margin:0}}.timerbuttons button{{width:100%;font-size:10px;padding:10px 3px;background:#18303d;color:white}}.timerbuttons .work{{background:#167443}}.timerbuttons .break{{background:#6b481c}}.bottom{{position:fixed;bottom:0;left:0;right:0;background:#071117f5;border-top:1px solid #233742;z-index:20}}.nav{{max-width:600px;margin:auto;display:grid;grid-template-columns:repeat(4,1fr)}}.nav a{{color:#8fa6b4;text-align:center;padding:10px 2px;font-size:10px;font-weight:750}}.nav span{{display:block;font-size:20px}}.nav .on{{color:#20e66b}}
</style></head><body><main><div class="top"><div class="brand">DEVCO <b>FIELD</b></div><div class="signal">● OFFLINE READY</div></div><div class="job"><form method="post" action="/select"><select name="job">{opts}</select><button>Switch</button></form></div><div class="stats"><div class="stat"><div class="num">{total}</div><div class="label">JUs</div></div><div class="stat"><div class="num green">{done}</div><div class="label">Complete</div></div><div class="stat"><div class="num orange">{remain}</div><div class="label">Remaining</div></div></div>{active_html}<div class="sectiontitle">FIELD TOOLS</div><div class="tools"><a class="tool map" href="/map"><div class="ico">◈</div><b>Job Map</b><small>JUs, GPS & route</small></a><a class="tool" href="/hone"><div class="ico">⌖</div><b>Hone In</b><small>Live 3 m guidance</small></a><div class="tool"><div class="ico">▣</div><b>Photos</b><small>Solocator matching</small></div><div class="tool"><div class="ico">▤</div><b>Billing & Notes</b><small>Production record</small></div></div>{timer_html}<div class="mode"><div class="dot"></div><div class="modeinfo"><b>Field Mode {'Running' if running else 'Stopped'}</b><small>{done} of {total} completed</small></div><form method="post" action="/{'stop' if running else 'start'}"><button class="{'stop' if running else 'start'}">{'Stop' if running else 'Start'}</button></form></div><script>const runTimer={str(bool(tstate.get("running"))).lower()},baseTimer={float(tstate.get("elapsed",0))},timerStart=Date.now();function tf(x){{x=Math.floor(Math.max(0,x));let h=Math.floor(x/3600),m=Math.floor((x%3600)/60),q=x%60;return h?h+":"+String(m).padStart(2,"0")+":"+String(q).padStart(2,"0"):m+":"+String(q).padStart(2,"0")}}if(runTimer)setInterval(()=>{{let e=document.getElementById("liveclock");if(e)e.textContent=tf(baseTimer+(Date.now()-timerStart)/1000)}},1000);</script></main><div class="bottom"><div class="nav"><a class="on" href="/map"><span>◈</span>Map</a><a href="/"><span>⌖</span>Active JU</a><a href="/"><span>▣</span>Photos</a><a href="/"><span>•••</span>More</a></div></div></body></html>"""

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
    def do_GET(self):
        path=urlparse(self.path).path
        if path in ("/static/leaflet.js","/static/leaflet.css"):
            f=ROOT/"SYSTEM"/"vendor"/path.rsplit("/",1)[-1]
            if f.exists():
                b=f.read_bytes(); self.send_response(200); self.send_header("Content-Type","application/javascript" if path.endswith(".js") else "text/css"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return
        if path == "/nav":
            q=parse_qs(urlparse(self.path).query)
            lat=q.get("lat",[""])[0]; lon=q.get("lon",[""])[0]
            launch_google_maps(lat,lon,q.get("ju",[""])[0])
            self.send_response(303); self.send_header("Location","/map"); self.end_headers(); return
        if path == "/map":
            b=map_page().encode(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
        elif urlparse(self.path).path == "/hone":
            b=hone_page().encode(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
        else: self.send()
    def do_POST(self):
        global active_job, field_proc, active_ju
        n=int(self.headers.get('Content-Length','0')); data=parse_qs(self.rfile.read(n).decode())
        if self.path=='/select':
            j=data.get('job',[''])[0]
            if j in jobs(): active_job=j; active_ju=None
            msg='Job selected.'
        elif self.path=='/activate':
            j=data.get('ju',[''])[0]
            valid={x['ju'] for x in ju_points(active_job)} if active_job else set()
            if j in valid:
                active_ju=j
                start_timer(active_job,"Drive",j)
                self.send_response(303); self.send_header('Location','/'); self.end_headers(); return
            msg='JU not found.'
        elif self.path=='/timer':
            action=data.get('action',[''])[0].lower()
            if not active_job: msg='Select a job first.'
            elif action=='stop': stop_timer(active_job); msg='Timer stopped.'
            elif action in ('drive','work','break','other'):
                start_timer(active_job,action,active_ju or ''); msg=f'{action.title()} timer started.'
            else: msg='Unknown timer action.'
        elif self.path=='/start': msg=start_field()
        elif self.path=='/stop':
            # Stopping Field Mode also ends the active time category at this exact moment.
            # This writes the final Drive/Work/Break segment to TIME_TRACKING.csv.
            if active_job:
                stop_timer(active_job)
            if field_proc and field_proc.poll() is None:
                field_proc.terminate(); msg='Field Mode stopped. Time tracking stopped.'
            else:
                msg='Field Mode is not running. Time tracking stopped.'
        else: msg='Unknown action.'
        self.send(msg)
    def log_message(self,*a): pass
if __name__=='__main__':
    js=jobs(); active_job=js[0] if js else None
    print('DEVCO Field app: http://127.0.0.1:8765',flush=True); ThreadingHTTPServer(('127.0.0.1',8765),H).serve_forever()
