from pathlib import Path
from datetime import datetime
import re, csv
from openpyxl import Workbook

CLOSE_RULES={
 "FIBER TRANSFER COMPLETED":(2,"COMPLETE"),
 "TRANSFER ALREADY COMPLETED":(1,"COMPLETE"),
 "NO SERVICES ON POLE":(1,"COMPLETE"),
 "ADSS":(1,"COMPLETE"),
 "NO IDENTIFIABLE WINDSTREAM LINE ON POLE":(1,"COMPLETE"),
 "PENDING":(1,"PENDING"),
}
HEADERS=["JU","Address","Latitude","Longitude","Navigate","State","Close Code","Photo Count","Billing Codes","Notes","Photo Files","Drive Time","Work Time","Completed At"]

def _parse_info(p):
 d={}
 for line in p.read_text(errors='ignore').splitlines():
  if ':' in line:
   k,v=line.split(':',1); d[k.strip()]=v.strip()
 return d

def _parse_record(p):
 out={"status":"","billing":[],"notes":[],"completed_at":""}
 if not p.exists(): return out
 txt=p.read_text(errors='ignore')
 sts=re.findall(r'^STATUS:\s*(.+)$',txt,re.M)
 if sts: out['status']=sts[-1].strip().upper()
 # Read only the most recent billing section, never code-looking note text.
 blocks=re.findall(r'^BILLING:\n(.*?)(?=^NOTES:|\Z)',txt,re.M|re.S)
 out['billing']=re.findall(r'^([A-Z0-9][A-Z0-9()\- \[\]/]+?)\s+x(\d+)\s*$',blocks[-1] if blocks else '',re.M)
 dates=re.findall(r'^COMPLETED_AT:\s*(.+)$',txt,re.M)
 if dates: out['completed_at']=dates[-1].strip()
 notes=re.findall(r'^NOTES:\n(.*?)(?=^={5,}\s*$|\Z)',txt,re.M|re.S)
 if notes: out['notes']=[notes[-1].strip()]
 return out

def _times(job_dir,ju):
 d=w=0.0; p=job_dir/'1_JOB_WORKFLOW'/'TIME_TRACKING.csv'
 if p.exists():
  try:
   for r in csv.DictReader(p.open()):
    if r.get('JU')==ju:
     sec=float(r.get('Seconds') or 0)
     if r.get('Category')=='Drive': d+=sec
     elif r.get('Category')=='Work': w+=sec
  except Exception: pass
 return d,w

def _fmt(sec):
 sec=int(sec); h,rem=divmod(sec,3600); m,s=divmod(rem,60)
 return f'{h}:{m:02d}:{s:02d}'

def collect(job_dir):
 rows=[]
 for info in sorted((job_dir/'3_JU_FILES').glob('*/transfer_info.txt')):
  v=_parse_info(info); ju=v.get('JU Record',info.parent.name.split(' - ',1)[0])
  photos=sorted([p.name for p in (info.parent/'photos').glob('*') if p.is_file()]) if (info.parent/'photos').exists() else []
  rec=_parse_record(info.parent/'BILLING_AND_NOTES.txt')
  close=rec['status']
  need,state=CLOSE_RULES.get(close,(None,'NOT COMPLETED'))
  if state=='COMPLETE' and len(photos)<need: state='NOT COMPLETED'
  if state=='PENDING' and len(photos)<need: state='NOT COMPLETED'
  drive,work=_times(job_dir,ju)
  rows.append({
   'JU':ju,'Address':v.get('Address',''),'Latitude':v.get('Latitude',''),'Longitude':v.get('Longitude',''),
   'Navigate':f'https://www.google.com/maps/dir/?api=1&destination={v.get("Latitude","")},{v.get("Longitude","")}&travelmode=driving',
   'State':state,'Close Code':close,'Photo Count':len(photos),
   'Billing Codes':'; '.join(f'{c} x{q}' for c,q in rec['billing']),'Notes':'; '.join(rec['notes']),
   'Photo Files':'; '.join(photos),'Drive Time':_fmt(drive),'Work Time':_fmt(work),
   'Completed At':rec.get('completed_at') or datetime.fromtimestamp((info.parent/'BILLING_AND_NOTES.txt').stat().st_mtime).isoformat(timespec='seconds') if state=='COMPLETE' and (info.parent/'BILLING_AND_NOTES.txt').exists() else ''
  })
 return rows

def _write(path,rows):
 wb=Workbook(); ws=wb.active; ws.title='JUs'; ws.append(HEADERS)
 for r in rows:
  ws.append([r[h] for h in HEADERS])
 for cell in ws['E'][1:]:
  if cell.value: cell.hyperlink=cell.value; cell.style='Hyperlink'; cell.value='Navigate'
 ws.freeze_panes='A2'; ws.auto_filter.ref=ws.dimensions
 widths=[14,42,14,14,14,18,42,12,35,45,50,14,14,22]
 for i,w in enumerate(widths,1): ws.column_dimensions[chr(64+i)].width=w
 path.parent.mkdir(parents=True,exist_ok=True); wb.save(path)

def sync_job(job_dir):
 rows=collect(job_dir); out=job_dir/'1_JOB_WORKFLOW'
 jid=job_dir.name
 _write(out/f'{jid}_MASTER.xlsx',rows)
 _write(out/f'{jid}_COMPLETED.xlsx',[r for r in rows if r['State']=='COMPLETE'])
 _write(out/f'{jid}_NOT_COMPLETED.xlsx',[r for r in rows if r['State']!='COMPLETE'])
 return {s:sum(r['State']==s for r in rows) for s in ('COMPLETE','PENDING','NOT COMPLETED')}|{'TOTAL':len(rows)}
