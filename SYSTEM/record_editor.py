"""Pinned JU edits and photo access, independent of the GPS-selected field stop."""
import hashlib
import html
import json
import os
import tempfile
import threading
from functools import wraps
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from job_records import _parse_info, _parse_record, CLOSE_RULES
from note_store import read_note, save_note

RECORD_LOCK = threading.RLock()
IMAGE_TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}

class Conflict(ValueError):
    pass


def record_write(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        with RECORD_LOCK:
            return function(*args, **kwargs)
    return guarded


def folder_for(app, job, ju):
    if job not in app['jobs']() or not ju:
        raise ValueError('JU not found')
    folder = app['_ju_folder'](job, ju)
    if folder is None:
        raise ValueError('JU not found')
    return folder


def revision(folder):
    digest = hashlib.sha256()
    for name in ('BILLING_AND_NOTES.txt', 'NOTE_DRAFT.json'):
        p = folder / name
        digest.update(name.encode())
        digest.update(p.read_bytes() if p.exists() else b'')
    return digest.hexdigest()


def photo_items(folder, job, ju):
    root = folder / 'photos'
    items = []
    for p in sorted(root.glob('*'), key=lambda p: p.stat().st_mtime, reverse=True):
        if p.is_file() and p.suffix.lower() in IMAGE_TYPES and p.resolve().parent == root.resolve():
            items.append({'name': p.name, 'url': '/photo?' + urlencode({'job': job, 'ju': ju, 'name': p.name})})
    return items


def record_data(app, job, ju):
    with RECORD_LOCK:
        folder = folder_for(app, job, ju)
        info = _parse_info(folder / 'transfer_info.txt')
        record = _parse_record(folder / 'BILLING_AND_NOTES.txt')
        return {'job': job, 'ju': ju, 'address': info.get('Address', ''),
                'status': record['status'], 'state': app['_ju_state'](folder),
                'note': read_note(folder), 'billing': record['billing'],
                'revision': revision(folder), 'photos': photo_items(folder, job, ju)}


def atomic_text(path, content):
    fd, temp = tempfile.mkstemp(prefix='.record-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def save_edit(app, job, ju, expected, note, selected):
    with RECORD_LOCK:
        folder = folder_for(app, job, ju)
        if not expected or revision(folder) != expected:
            raise Conflict('This JU changed since you opened it. Your draft is kept. Reopen the saved record before replacing it.')
        recpath = folder / 'BILLING_AND_NOTES.txt'
        rec = _parse_record(recpath)
        allowed = set(app['BILLING_CODES']) | {'TRIP CHARGE'} | {c for c, q in rec['billing']}
        codes = []
        seen = set()
        for code, qty in selected:
            if code not in allowed or code in seen:
                raise ValueError('Unknown or duplicate billing code')
            if not str(qty).isdigit() or not 1 <= int(qty) <= 9999:
                raise ValueError('Quantities must be whole numbers from 1 to 9999')
            codes.append((code, str(int(qty))))
            seen.add(code)
        if rec['status'] == 'FIBER TRANSFER COMPLETED' and not codes:
            raise ValueError('A completed transfer needs at least one billing code')
        if len(note) > 50000:
            raise ValueError('Notes are too long')
        before = {name: (folder / name).read_text() if (folder / name).exists() else None
                  for name in ('BILLING_AND_NOTES.txt', 'NOTE_DRAFT.json')}
        history = folder / 'RECORD_HISTORY'
        history.mkdir(exist_ok=True)
        atomic_text(history / (datetime.now().strftime('%Y%m%dT%H%M%S%f') + '.json'), json.dumps(before))
        photos = sorted(p.name for p in (folder / 'photos').glob('*') if p.is_file())
        completed = rec.get('completed_at', '')
        # Editing notes is not a completion event. Older records keep their
        # original photo-date fallback instead of acquiring a file-edit date.
        content = '\n' + '=' * 50 + f'\nJU: {ju}\n'
        if completed:
            content += f'COMPLETED_AT: {completed}\n'
        content += '\nPHOTOS:\n' + ''.join(f'- {name}\n' for name in photos)
        content += '\nSTATUS: ' + (rec['status'] or 'NOT COMPLETED') + '\n\nBILLING:\n'
        content += ''.join(f'{code} x{qty}\n' for code, qty in codes) or 'No billing codes entered\n'
        content += '\nNOTES:\n' + note + '\n'
        try:
            save_note(folder, note)
            atomic_text(recpath, content)
        except Exception:
            for name, value in before.items():
                if value is None:
                    (folder / name).unlink(missing_ok=True)
                else:
                    atomic_text(folder / name, value)
            raise
        warning = ''
        try:
            app['sync_job'](app['JOBS'] / job)
        except Exception:
            warning = 'Record saved. Spreadsheet refresh failed; tap Save again to retry.'
        return {'ok': True, 'revision': revision(folder), 'warning': warning}


STYLE = '''*{box-sizing:border-box}body{margin:0;background:#09131b;color:#edf4f7;font:17px system-ui}main{max-width:760px;margin:auto;padding:18px}header,nav,.row{display:flex;gap:10px;align-items:center}header{justify-content:space-between}header b{color:#4cdd92}nav{margin:18px 0}nav>*{flex:1}a,button{color:inherit}a.button,button{display:block;background:#203846;border:1px solid #456071;border-radius:10px;padding:13px;text-align:center;text-decoration:none;font:600 16px system-ui;min-height:48px;cursor:pointer}.primary{background:#4cdd92!important;color:#06180e!important;border:0!important}section,.card{display:block;background:#13232e;border:1px solid #304754;border-radius:14px;padding:18px;margin:14px 0}.card{text-decoration:none}h1{font-size:29px;margin:8px 0}h2{font-size:21px}p{line-height:1.5}small,.muted{color:#a8bdc9}.muted{font-size:14px}input,select,textarea{width:100%;padding:13px;background:#09131b;color:#edf4f7;border:1px solid #456071;border-radius:8px;font:16px system-ui;margin:8px 0}textarea{min-height:180px;resize:vertical}.code-row{display:grid;grid-template-columns:1fr 90px 48px;gap:8px;align-items:center}.code-row button{padding:10px}.savebar{position:sticky;bottom:0;background:#09131b;padding:12px 0}.savebar button{width:100%}[hidden]{display:none!important}.notice{color:#f1c580}#save-status{min-height:24px}.badge{font-size:13px;color:#4cdd92}'''

PHOTO_STYLE = '''.photo-window{background:#071019;border:1px solid #304754;border-radius:12px;overflow:hidden;margin:12px 0}.photo-window .empty{padding:28px 16px;text-align:center;color:#a8bdc9}.photo-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;padding:5px}.photo-grid a{display:block;padding:0;border:0;background:none;min-width:0;min-height:0}.photo-grid>div:first-child{grid-column:1/-1}.photo-grid img{display:block;width:100%;height:100px;object-fit:cover;border-radius:6px}.photo-grid>div:first-child img{height:260px;object-fit:contain}.photo-grid span{display:block;font-size:12px;overflow-wrap:anywhere;padding:5px}.photo-help{font-size:14px;color:#a8bdc9}'''


def photo_panel(job, ju, items, camera=True):
    escaped = html.escape
    tiles = ''.join('<a href="' + escaped(p['url'], quote=True) + '"><img loading="lazy" src="' + escaped(p['url'], quote=True) + '" alt="' + escaped(p['name'], quote=True) + '"><span>' + escaped(p['name']) + '</span></a>' for p in items)
    body = '<div class="photo-grid">' + tiles + '</div>' if tiles else '<div class="empty">No photos filed yet.<br>Take a Solocator photo to get started.</div>'
    button = '<a class="button primary" href="/camera">Take Photo · Solocator</a><p class="photo-help">Take the photo in Solocator, then return here. New GPS-matched photos appear automatically. Tap a photo to view it.</p>' if camera else ''
    from ju_media import upload_link
    button += upload_link(job, ju)
    return '<div id="photo-window" class="photo-window">' + body + '</div>' + button


def photo_script(job, ju):
    url = json.dumps('/media-list?' + urlencode({'job': job, 'ju': ju}))
    return '''<script>
let photoFingerprint='',photoBusy=false;
async function refreshPhotos(){
 if(document.hidden||photoBusy)return;photoBusy=true;
 try{const r=await fetch(__URL__,{cache:'no-store'});if(!r.ok)throw Error();const items=await r.json();
 const fingerprint=JSON.stringify(items);if(fingerprint===photoFingerprint)return;photoFingerprint=fingerprint;
 const panel=document.getElementById('photo-window');if(!panel)return;panel.replaceChildren();
 if(!items.length){const empty=document.createElement('div');empty.className='empty';empty.textContent='No photos or videos filed yet. Take a photo or upload files below.';panel.append(empty);return;}
 const grid=document.createElement('div');grid.className='photo-grid';
 items.forEach(p=>{const box=document.createElement('div'),a=document.createElement('a'),caption=document.createElement('span');a.href=p.url;caption.textContent=p.name;if(p.kind==='video'){const v=document.createElement('video');v.src=p.url;v.controls=true;v.preload='none';v.playsInline=true;v.style.width='100%';box.append(v);a.textContent=p.name;box.append(a);}else if(/[.](heic|heif)$/i.test(p.name)){a.textContent=p.name+' · Open original';box.append(a);}else{const img=document.createElement('img');img.src=p.url;img.alt=p.name;img.loading='lazy';a.append(img,caption);box.append(a);}grid.append(box);});panel.append(grid);
 }catch(e){}finally{photoBusy=false;}
}
setInterval(refreshPhotos,3000);document.addEventListener('visibilitychange',refreshPhotos);refreshPhotos();
</script>'''.replace('__URL__', url)


def shell(title, body, extra=''):
    return '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + html.escape(title) + ' · DEVCO</title><style>' + STYLE + PHOTO_STYLE + '</style></head><body><main><header><b>DEVCO FIELD</b><a href="/">Active JU</a></header><nav><a class="button" href="/">Field</a><a class="button primary" href="/records">JU Files</a><a class="button" href="/map">Map</a></nav>' + body + '</main>' + extra + '</body></html>'


def records_page(app, job):
    if job not in app['jobs']():
        job = app['active_job'] or next(iter(app['jobs']()), '')
    esc = html.escape
    options = ''.join('<option value="' + esc(j) + '"' + (' selected' if j == job else '') + '>' + esc(j) + '</option>' for j in app['jobs']())
    cards = []
    # Enumerate files directly so records without coordinates remain editable.
    for info in sorted((app['JOBS'] / job / '3_JU_FILES').glob('*/transfer_info.txt')) if job else []:
        values = _parse_info(info)
        ju = values.get('JU Record', info.parent.name.split(' - ', 1)[0])
        rec = _parse_record(info.parent / 'BILLING_AND_NOTES.txt')
        note = read_note(info.parent)
        state = app['_ju_state'](info.parent)
        codes = '; '.join(c + ' ×' + q for c, q in rec['billing']) or 'No billing codes'
        address = values.get('Address', '')
        search = ' '.join((ju, address, note, codes, rec['status'])).lower()
        cards.append('<a class="card ju-card" data-search="' + esc(search, quote=True) + '" data-state="' + esc(state) + '" href="/record?' + esc(urlencode({'job': job, 'ju': ju})) + '"><span class="badge">' + esc(state) + '</span><h2>JU ' + esc(ju) + '</h2><p>' + esc(address) + '</p><p>' + esc(codes) + '</p><small>' + esc(note[:150] or 'No notes yet') + '</small></a>')
    body = '<h1>JU Files</h1><p class="muted">Open any JU to upload photos and videos or edit notes and billing codes.</p><form method="get" action="/records"><label>Project<select name="job">' + options + '</select></label><button>Show project</button></form><label>Search JUs, addresses, notes or codes<input id="search" type="search" placeholder="JU number, street, or note"></label><label>Status<select id="filter"><option value="">All JUs</option>COMPLETE</option><option>PENDING</option><option>NOT COMPLETED</option></select></label><p id="count" role="status">' + str(len(cards)) + ' JUs</p>' + ''.join(cards) + '<p id="empty" hidden>No JUs match this search.</p>'
    script = '''<script>const search=document.getElementById('search'),filter=document.getElementById('filter'),cards=[...document.querySelectorAll('.ju-card')];function applyFilter(){let count=0;const q=search.value.trim().toLowerCase();cards.forEach(c=>{c.hidden=!(c.dataset.search.includes(q)&&(!filter.value||c.dataset.state===filter.value));if(!c.hidden)count++;});document.getElementById('count').textContent=count+' JUs';document.getElementById('empty').hidden=count!==0;}search.addEventListener('input',applyFilter);filter.addEventListener('change',applyFilter);</script>'''
    return shell('JU Files', body, script)


def edit_page(app, job, ju):
    record = record_data(app, job, ju)
    esc = html.escape
    seed = json.dumps({**record, 'allowed': list(dict.fromkeys(app['BILLING_CODES'] + ['TRIP CHARGE'] + [c for c, q in record['billing']]))}).replace('</', '<\\/')
    body = '<a href="/map?' + esc(urlencode({'job': job})) + '">← Map</a> · <a href="/records?' + esc(urlencode({'job': job})) + '">← All JU files</a><section><small>PROJECT ' + esc(job) + '</small><h1>JU ' + esc(ju) + '</h1><p>' + esc(record['address']) + '</p><p class="badge">' + esc(record['status'] or 'NOT COMPLETED') + '</p><h2>Photos &amp; videos</h2>' + photo_panel(job, ju, record['photos'], camera=False) + '</section><section><form id="editor"><label for="notes"><h2>Notes</h2></label><textarea id="notes"></textarea><h2>Billing codes</h2><p class="muted">Add or remove codes and adjust quantities. This saves this JU without changing its completion status or your current field stop.</p><div id="codes"></div><button id="add-code" type="button">+ Add billing code</button><div class="savebar"><p id="save-status" role="status">Saved record loaded</p><button class="primary" type="submit">Save changes</button></div></form><a id="reload-record" href="" hidden>Reopen saved record (your draft stays on this phone)</a><button id="restore-draft" type="button" hidden>Restore my unsaved draft</button></section>'
    script = '''<script>
const initial=__SEED__,form=document.getElementById('editor'),notes=document.getElementById('notes'),codes=document.getElementById('codes'),status=document.getElementById('save-status');
const draftKey='devco-record:'+initial.job+':'+initial.ju;let revision=initial.revision,dirty=false,saving=false,keptDraft=null;
function addCode(code='',qty='1'){const row=document.createElement('div');row.className='code-row';const select=document.createElement('select');select.setAttribute('aria-label','Billing code');const blank=new Option('Choose code','');select.add(blank);initial.allowed.forEach(c=>select.add(new Option(c==='TRIP CHARGE'?'Trip Charge ($40)':c,c)));select.value=code;const quantity=document.createElement('input');quantity.type='number';quantity.min='1';quantity.max='9999';quantity.step='1';quantity.value=qty;quantity.setAttribute('aria-label','Quantity');const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label','Remove billing code');remove.onclick=()=>{row.remove();changed();};row.append(select,quantity,remove);codes.append(row);}
function values(){return {job:initial.job,ju:initial.ju,revision,note:notes.value,billing:[...codes.children].map(r=>[r.querySelector('select').value,r.querySelector('input').value])};}
function fill(data){notes.value=data.note;codes.replaceChildren();data.billing.forEach(([c,q])=>addCode(c,q));}
function stash(){try{localStorage.setItem(draftKey,JSON.stringify(values()));}catch(e){}}
function changed(){dirty=true;stash();status.textContent='Unsaved changes · tap Save changes';}
fill(initial);
try{const draft=JSON.parse(localStorage.getItem(draftKey)||'null');if(draft){if(draft.revision===revision){fill(draft);changed();status.textContent='Unsaved draft restored · tap Save changes';}else{keptDraft=draft;document.getElementById('restore-draft').hidden=false;status.textContent='Saved record loaded. A previous draft is available to restore.';}}}catch(e){}
document.getElementById('restore-draft').onclick=()=>{if(keptDraft){fill(keptDraft);changed();document.getElementById('restore-draft').hidden=true;}};
form.addEventListener('input',changed);form.addEventListener('change',changed);document.getElementById('add-code').onclick=()=>{addCode();changed();};
window.addEventListener('beforeunload',e=>{if(dirty){stash();e.preventDefault();e.returnValue='';}});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&dirty)stash();});
form.addEventListener('submit',async e=>{e.preventDefault();if(saving)return;const payload=values();if(payload.billing.some(([c,q])=>!c||!/^\\d+$/.test(q)||+q<1||+q>9999)){status.textContent='Choose a code and a whole-number quantity for every row.';return;}if(new Set(payload.billing.map(x=>x[0])).size!==payload.billing.length){status.textContent='Use one row per code and adjust its quantity.';return;}
 saving=true;stash();status.textContent='Saving…';const controls=[...form.querySelectorAll('input,textarea,button,select')];controls.forEach(c=>c.disabled=true);
 try{const r=await fetch('/record-save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const result=await r.json();if(!r.ok){if(r.status===409)document.getElementById('reload-record').hidden=false;throw Error(result.error||'Save failed');}revision=result.revision;dirty=false;try{localStorage.removeItem(draftKey);localStorage.removeItem('devco-closeout:'+initial.job+':'+initial.ju);}catch(e){}status.textContent=result.warning||'Saved to JU file and spreadsheets';}
 catch(error){status.textContent=error.message+' — your draft is kept on this phone.';}
 finally{saving=false;controls.forEach(c=>c.disabled=false);}
});
</script>'''.replace('__SEED__', seed)
    return shell('JU ' + ju, body, script + photo_script(job, ju))
