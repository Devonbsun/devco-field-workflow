"""JU-pinned original media uploads and bounded streaming video playback."""
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from record_editor import RECORD_LOCK, folder_for, photo_items, photo_panel, photo_script, shell

PHOTO_TYPES = {'.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.png':'image/png',
               '.webp':'image/webp', '.gif':'image/gif', '.heic':'image/heic', '.heif':'image/heif'}
VIDEO_TYPES = {'.mp4':'video/mp4', '.mov':'video/quicktime', '.m4v':'video/mp4',
               '.webm':'video/webm', '.3gp':'video/3gpp'}
MAX_BYTES = 90_000_000  # Leave room for each original in a <100 MB job packet part.


def upload_link(job, ju):
    query = html.escape(urlencode({'job':job, 'ju':ju}), quote=True)
    return ('<a class="button primary" style="margin-top:12px" href="/upload-open?'+query+'">'
            'Upload photos or videos</a><p class="photo-help">Choose files in your phone browser. '
            'Originals save to this JU. Up to 90 MB per file.</p>')


def media_items(folder, job, ju):
    items = []
    for directory, types, kind in [('photos',PHOTO_TYPES,'photo'),('videos',VIDEO_TYPES,'video')]:
        root = folder / directory
        if root.is_symlink(): continue
        for p in root.glob('*'):
            if p.is_file() and not p.is_symlink() and p.suffix.lower() in types:
                items.append({'name':p.name, 'kind':kind, 'bytes':p.stat().st_size,
                              'url':'/media?'+urlencode({'job':job,'ju':ju,'kind':kind,'name':p.name}),
                              '_time':p.stat().st_mtime})
    items.sort(key=lambda p:p.pop('_time'), reverse=True)
    return items


def valid_signature(head, suffix):
    if suffix in ('.jpg','.jpeg'): return head.startswith(b'\xff\xd8\xff')
    if suffix == '.png': return head.startswith(b'\x89PNG\r\n\x1a\n')
    if suffix == '.gif': return head[:6] in (b'GIF87a',b'GIF89a')
    if suffix == '.webp': return head[:4] == b'RIFF' and head[8:12] == b'WEBP'
    if suffix == '.webm': return head.startswith(b'\x1a\x45\xdf\xa3')
    if suffix in ('.heic','.heif'): return head[4:8] == b'ftyp' and any(x in head[8:40] for x in (b'heic',b'heix',b'hevc',b'mif1',b'msf1'))
    return head[4:8] == b'ftyp' or (suffix == '.mov' and head[4:8] in (b'moov',b'mdat',b'wide'))


def save_upload(app, job, ju, name, stream, length):
    folder = folder_for(app,job,ju)
    if not name or len(name)>180 or Path(name).name!=name or re.search(r'[\\\x00-\x1f\x7f]',name) or name.startswith('.'):
        raise ValueError('Invalid filename')
    suffix = Path(name).suffix.lower()
    if suffix not in PHOTO_TYPES and suffix not in VIDEO_TYPES:
        raise ValueError('Choose a JPG, PNG, WebP, GIF, HEIC, MP4, MOV, M4V, WebM, or 3GP file')
    if not 0 < length <= MAX_BYTES: raise ValueError('Each file must be between 1 byte and 90 MB')
    directory = 'videos' if suffix in VIDEO_TYPES else 'photos'
    root = folder / directory
    if root.is_symlink(): raise ValueError('Media folder is unavailable')
    root.mkdir(exist_ok=True)
    if shutil.disk_usage(root).free < length + 10_000_000: raise ValueError('Not enough free storage on the phone')
    # Temporary bytes are outside photos/, so incomplete uploads cannot count as evidence.
    fd, temp = tempfile.mkstemp(prefix='.upload-', dir=folder)
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd,'wb') as out:
            remaining = length
            head = b''
            while remaining:
                chunk = stream.read(min(1024*1024,remaining))
                if not chunk: raise ValueError('Upload interrupted. Please choose the file again')
                if len(head)<64: head += chunk[:64-len(head)]
                out.write(chunk); digest.update(chunk); remaining -= len(chunk)
            out.flush(); os.fsync(out.fileno())
        if not valid_signature(head,suffix): raise ValueError('The file contents do not match its photo/video type')
        duplicate = False
        with RECORD_LOCK:
            # Retrying an interrupted response must not create duplicate evidence.
            destination = root/name
            for candidate in root.glob('*'):
                if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size != length: continue
                with candidate.open('rb') as source:
                    existing = hashlib.file_digest(source,'sha256').hexdigest()
                if existing == digest.hexdigest():
                    destination = candidate; duplicate = True; break
            if not duplicate:
                if destination.exists(): destination = root/(Path(name).stem+'_'+uuid.uuid4().hex[:10]+suffix)
                os.replace(temp,destination)
        warning = ''
        try: app['sync_job'](app['JOBS']/job)
        except Exception: warning = 'File saved. Spreadsheet refresh is pending.'
        return {'ok':True,'job':job,'ju':ju,'name':destination.name,'kind':'video' if directory=='videos' else 'photo',
                'duplicate':duplicate,'warning':warning}
    finally:
        if os.path.exists(temp): os.unlink(temp)


def upload_page(job, ju, folder):
    esc = html.escape
    config = json.dumps({'job':job,'ju':ju,'maxBytes':MAX_BYTES}).replace('</','<\\/')
    gallery = photo_panel(job,ju,photo_items(folder,job,ju),camera=False)
    # The picker page is already in the phone browser; don't offer another browser hop.
    gallery = gallery.split('<a class="button primary" style="margin-top:12px"')[0]
    body = '<h1>Upload to JU '+esc(ju)+'</h1><p>Project '+esc(job)+'</p>'
    body += '''<section><label for="ju-media">Choose photos or videos</label>
<input id="ju-media" type="file" accept="image/*,video/*" multiple>
<p class="muted">Original files are preserved. Up to 90 MB each. Videos stay with this JU; closeout photo requirements still apply.</p>
<button id="upload-start" class="primary" type="button">Upload selected files</button>
<progress id="upload-progress" max="100" value="0" style="width:100%" hidden></progress>
<p id="upload-status" role="status" aria-live="polite">Select one or more files.</p><ul id="upload-results"></ul>
<p>When finished, return to Devco Field. Your files appear under this JU automatically.</p></section>'''
    body += '<h2>Photos &amp; videos</h2>'+gallery
    script = r'''<script>
const mediaTarget=__CONFIG__,picker=document.getElementById('ju-media'),start=document.getElementById('upload-start'),message=document.getElementById('upload-status'),progress=document.getElementById('upload-progress'),results=document.getElementById('upload-results');
function uploadOne(file,index,total){return new Promise((resolve,reject)=>{
 const xhr=new XMLHttpRequest(),query=new URLSearchParams({job:mediaTarget.job,ju:mediaTarget.ju,name:file.name});
 xhr.open('POST','/media-upload?'+query);xhr.timeout=600000;
 xhr.setRequestHeader('Content-Type',file.type||'application/octet-stream');xhr.setRequestHeader('X-Devco-Upload','1');
 xhr.upload.onprogress=e=>{if(e.lengthComputable){progress.value=e.loaded/e.total*100;message.textContent='Uploading '+index+'/'+total+': '+file.name+' ('+Math.round(progress.value)+'%)';}};
 xhr.onload=()=>{try{const data=JSON.parse(xhr.responseText);if(xhr.status>=200&&xhr.status<300&&data.ok)resolve(data);else reject(Error(data.error||'Upload failed'));}catch(e){reject(Error('Upload response was lost. Retry this file; duplicates are detected.'));}};
 xhr.onerror=xhr.ontimeout=xhr.onabort=()=>reject(Error('Connection interrupted. Retry this file.'));
 xhr.send(file);
});}
start.onclick=async()=>{
 if(window.devcoMediaUploading)return;
 const files=[...picker.files];if(!files.length){message.textContent='Choose at least one photo or video.';return;}
 window.devcoMediaUploading=true;start.disabled=picker.disabled=true;progress.hidden=false;results.replaceChildren();let saved=0;
 try{for(let i=0;i<files.length;i++){
  const file=files[i],row=document.createElement('li');results.append(row);progress.value=0;
  try{if(!file.size||file.size>mediaTarget.maxBytes)throw Error('File must be between 1 byte and 90 MB');
   message.textContent='Uploading '+(i+1)+'/'+files.length+': '+file.name;
   const data=await uploadOne(file,i+1,files.length);saved++;row.textContent=(data.duplicate?'Already saved: ':'Saved: ')+data.name+(data.warning?' — '+data.warning:'');refreshPhotos();
  }catch(error){row.textContent=file.name+': '+error.message;}
 }message.textContent=saved+'/'+files.length+' files saved to JU '+mediaTarget.ju+'.'+(saved<files.length?' Select failed files to retry.':' You can return to Devco Field.');if(saved===files.length)picker.value='';
 }finally{window.devcoMediaUploading=false;start.disabled=picker.disabled=false;progress.hidden=true;}
};
window.addEventListener('beforeunload',e=>{if(window.devcoMediaUploading){e.preventDefault();e.returnValue='';}});
</script>'''.replace('__CONFIG__',config)
    return shell('Upload to JU '+ju,body,photo_script(job,ju)+script)


def serve_file(handler,path,mime):
    size = path.stat().st_size; start=0; end=size-1; status=200
    value = handler.headers.get('Range')
    if value:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)',value)
        if not match or not any(match.groups()):
            handler.reply('Invalid byte range',status=416); return
        a,b=match.groups()
        if a: start=int(a); end=min(int(b),end) if b else end
        else: start=max(0,size-int(b))
        if start>end or start>=size:
            handler.send_response(416);handler.send_header('Content-Range',f'bytes */{size}');handler.end_headers();return
        status=206
    handler.send_response(status);handler.send_header('Content-Type',mime)
    handler.send_header('Accept-Ranges','bytes');handler.send_header('Cache-Control','no-store')
    handler.send_header('X-Content-Type-Options','nosniff');handler.send_header('Content-Length',str(end-start+1))
    if status==206: handler.send_header('Content-Range',f'bytes {start}-{end}/{size}')
    handler.end_headers()
    try:
        with path.open('rb') as source:
            source.seek(start);remaining=end-start+1
            while remaining:
                block=source.read(min(1024*1024,remaining))
                if not block:break
                handler.wfile.write(block);remaining-=len(block)
    except (BrokenPipeError,ConnectionResetError): pass


def handle_get(handler,app,path):
    if path not in ('/upload-open','/upload','/media-list','/media'): return False
    q=parse_qs(urlparse(handler.path).query);job=q.get('job',[''])[0];ju=q.get('ju',[''])[0]
    try:
        folder=folder_for(app,job,ju)
        if path=='/upload-open':
            target='http://127.0.0.1:'+str(handler.server.server_port)+'/upload?'+urlencode({'job':job,'ju':ju})
            subprocess.Popen(['termux-open-url',target],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            handler.reply(shell('Upload to JU '+ju,'<h1>Upload to JU '+html.escape(ju)+'</h1><p>The upload picker is opening in your phone browser. Return to Devco Field after uploading.</p><a class="button" href="'+html.escape('/record?'+urlencode({'job':job,'ju':ju}))+'">Return to this JU</a><p><a href="'+html.escape(target)+'">Open upload page here</a></p>'));return True
        if path=='/upload': handler.reply(upload_page(job,ju,folder));return True
        if path=='/media-list': handler.reply(json.dumps(media_items(folder,job,ju)),'application/json');return True
        kind=q.get('kind',[''])[0];name=q.get('name',[''])[0]
        directory,types=('photos',PHOTO_TYPES) if kind=='photo' else ('videos',VIDEO_TYPES) if kind=='video' else ('',{})
        root=folder/directory;p=root/name
        if not name or Path(name).name!=name or p.suffix.lower() not in types or root.is_symlink() or p.is_symlink() or p.resolve().parent!=root.resolve() or not p.is_file():raise ValueError('Media not found')
        serve_file(handler,p,types[p.suffix.lower()])
    except (ValueError,FileNotFoundError) as error: handler.reply(html.escape(str(error)),status=404)
    except OSError: handler.reply('Could not open the upload picker. Open the JU in your phone browser and try again.',status=503)
    return True


def handle_post(handler,app):
    if urlparse(handler.path).path!='/media-upload':return False
    try:
        origin=handler.headers.get('Origin')
        expected='http://127.0.0.1:'+str(handler.server.server_port)
        if handler.headers.get('X-Devco-Upload')!='1' or (origin and origin!=expected):raise ValueError('Invalid upload origin')
        q=parse_qs(urlparse(handler.path).query)
        length=int(handler.headers.get('Content-Length','0'))
        if handler.headers.get('Transfer-Encoding'):raise ValueError('Upload length required')
        handler.connection.settimeout(120)
        data=save_upload(app,q.get('job',[''])[0],q.get('ju',[''])[0],q.get('name',[''])[0],handler.rfile,length)
        handler.reply(json.dumps(data),'application/json')
    except (ValueError,TypeError) as error:handler.reply(json.dumps({'error':str(error)}),'application/json',400)
    except (OSError,TimeoutError):handler.reply(json.dumps({'error':'Upload did not finish. Check storage and retry the file.'}),'application/json',503)
    return True
