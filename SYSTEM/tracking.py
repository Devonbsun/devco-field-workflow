"""JU handoffs and payment ledger. Reading records never changes field evidence."""
import hashlib
import json
import re
import sqlite3
import threading
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from invoice_total import RATES
from job_records import _parse_info, _parse_record, CLOSE_RULES
from record_editor import RECORD_LOCK, Conflict

IMAGES = {'.jpg', '.jpeg', '.png', '.webp', '.heic'}
LOCK = threading.RLock()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def public(record):
    return {k: v for k, v in record.items() if not k.startswith('_')}


def money(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0 or number > 10000000 or number != number.quantize(Decimal('.01')):
            raise ValueError('Enter a positive dollar amount with no more than two decimal places.')
        return int(number * 100)
    except (InvalidOperation, TypeError):
        raise ValueError('Enter a valid dollar amount.')


@contextmanager
def open_db(root):
    directory = Path(root) / 'TRACKING'
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / 'tracking.sqlite3', timeout=30)
    try:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript('''
          CREATE TABLE IF NOT EXISTS bills(id INTEGER PRIMARY KEY, job TEXT NOT NULL, ju TEXT NOT NULL,
            amount INTEGER NOT NULL CHECK(amount>=0), revision TEXT NOT NULL, snapshot TEXT NOT NULL,
            reference TEXT NOT NULL, created TEXT NOT NULL, cancelled TEXT);
          CREATE UNIQUE INDEX IF NOT EXISTS active_bill ON bills(job,ju) WHERE cancelled IS NULL;
          CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY,bill INTEGER NOT NULL REFERENCES bills(id),
            amount INTEGER NOT NULL CHECK(amount>0),reference TEXT NOT NULL,created TEXT NOT NULL,reversed TEXT);
          CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,job TEXT NOT NULL,
            ju TEXT NOT NULL,created TEXT NOT NULL,detail TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS exports(id TEXT PRIMARY KEY,job TEXT NOT NULL,audience TEXT NOT NULL,
            status TEXT NOT NULL,created TEXT NOT NULL,detail TEXT NOT NULL);
        ''')
        with db:
            yield db
    finally:
        db.close()


def jobs(root):
    return sorted(p.name for p in (Path(root) / 'JOBS').iterdir()
                  if p.is_dir() and not p.is_symlink() and
                  ((p / '3_JU_FILES').is_dir() or (p / 'JOB_PACKET_CURRENT').is_dir()))


def records(root, job):
    if job not in jobs(root):
        raise ValueError('Job not found.')
    source = Path(root) / 'JOBS' / job
    legacy = (source / 'JOB_PACKET_CURRENT').is_dir()
    summary = {}
    if legacy:
        for row in json.loads((source / 'JOB_PACKET_CURRENT_SUMMARY.json').read_text()):
            key = str(row['ju'])
            if key in summary:
                raise ValueError('Duplicate JU in legacy index; review the source.')
            summary[key] = row
    base = source / ('JOB_PACKET_CURRENT' if legacy else '3_JU_FILES')
    rows, seen = [], set()
    with RECORD_LOCK:
        for info_path in sorted(base.glob('*/transfer_info.txt')):
            folder = info_path.parent
            if folder.is_symlink() or info_path.is_symlink():
                continue
            info = _parse_info(info_path)
            ju = str(info.get('JU Record') or folder.name.split(' - ', 1)[0])
            if not re.fullmatch(r'[A-Za-z0-9_-]+', ju) or ju in seen:
                raise ValueError('Invalid or duplicate JU identifier; review the source.')
            seen.add(ju)
            file = folder / 'BILLING_AND_NOTES.txt'
            raw = file.read_text(errors='replace') if file.exists() else ''
            rec = _parse_record(file)
            note = '\n'.join(rec['notes']).strip()
            codes = rec['billing']
            if legacy:
                entry = summary.get(ju)
                if entry is None:
                    raise ValueError('Legacy JU is missing from its index.')
                codes = list(entry.get('billing', {}).items())
                match = re.search(r'^WORK / FIELD NOTES\s*\n-+\n(.*?)(?=\nPHOTOS\s*\n-+|\Z)', raw, re.M | re.S)
                note = match.group(1).strip() if match else note
            photos = sorted(p for p in folder.rglob('*') if p.is_file() and not p.is_symlink()
                            and p.suffix.lower() in IMAGES and not any(x in p.relative_to(folder).parts
                            for x in ('VOICE_HISTORY', 'RECORD_HISTORY')))
            metadata = [{'name': p.relative_to(folder).as_posix(), 'bytes': p.stat().st_size,
                         'mtime': p.stat().st_mtime_ns} for p in photos]
            checks = {'Photos': bool(photos), 'Notes': bool(note), 'Close code': rec['status'] in CLOSE_RULES,
                      'Billing codes': bool(codes)}
            issues, lines, amount = [], [], 0
            need, state = CLOSE_RULES.get(rec['status'], (1, 'NOT COMPLETED'))
            if len(photos) < need:
                checks['Photos'] = False
                issues.append(f'Add photos: {need} required for this close code.')
            if legacy:
                issues.append('Older record: completion and close code need review.')
                checks['Close code'] = False
            elif state != 'COMPLETE':
                checks['Close code'] = False
                issues.append('Finish or review the closing task.')
            for code, quantity in codes:
                code, quantity = str(code), str(quantity)
                if not re.fullmatch(r'[1-9][0-9]{0,3}', quantity):
                    checks['Billing codes'] = False
                    issues.append('Review quantity for ' + code + '.')
                    qty = 0
                else:
                    qty = int(quantity)
                rate = RATES.get(code)
                cents = int(Decimal(str(rate)) * 100) if rate is not None else None
                if cents is None:
                    issues.append('Rate needed for ' + code + '.')
                total = cents * qty if cents is not None else None
                if total is not None:
                    amount += total
                lines.append({'code': code, 'quantity': quantity, 'rate_cents': cents, 'total_cents': total})
            for label, good in checks.items():
                if not good and label in ('Notes', 'Billing codes'):
                    issues.append('Add or review ' + label.lower() + '.')
            # Draft notes are private until explicitly saved into a closeout record.
            draft = folder / 'NOTE_DRAFT.json'
            if not legacy and draft.exists():
                try:
                    if json.loads(draft.read_text()).get('note', '').strip() != note:
                        issues.append('Notes changed since closeout; finish saving the record.')
                except (ValueError, AttributeError):
                    issues.append('Saved note draft needs review.')
            row = {'job': job, 'ju': ju, 'address': info.get('Address', ''), 'close_code': rec['status'],
                   'note': note, 'legacy': legacy, 'checks': checks, 'issues': list(dict.fromkeys(issues)),
                   'lines': lines, 'amount_cents': amount, 'photo_count': len(photos),
                   'original_bytes': sum(p['bytes'] for p in metadata), 'photos': metadata,
                   'latitude': info.get('Latitude', ''), 'longitude': info.get('Longitude', ''),
                   '_folder': folder, '_photos': photos}
            row['ready'] = all(checks.values()) and not row['issues']
            row['revision'] = hashlib.sha256(canonical(public(row)).encode()).hexdigest()
            rows.append(row)
    if legacy and seen != set(summary):
        raise ValueError('Legacy folder/index mismatch; review the source before exporting.')
    return rows


def enrich(db, rows):
    bills = {(r['job'], r['ju']): dict(r) for r in db.execute('SELECT * FROM bills WHERE cancelled IS NULL')}
    payments = {}
    for p in db.execute('SELECT * FROM payments WHERE reversed IS NULL ORDER BY id'):
        payments.setdefault(p['bill'], []).append(dict(p))
    sent = {}
    for e in db.execute("SELECT * FROM events WHERE kind IN ('sent_boss','sent_contractor') ORDER BY id"):
        sent[(e['job'], e['ju'], e['kind'])] = {'date': e['created'], **json.loads(e['detail'])}
    for row in rows:
        bill = bills.get((row['job'], row['ju']))
        row['bill'] = None
        if bill:
            history = payments.get(bill['id'], [])
            paid = sum(p['amount'] for p in history)
            row['bill'] = {'id': bill['id'], 'amount_cents': bill['amount'], 'paid_cents': paid,
                           'due_cents': bill['amount'] - paid, 'reference': bill['reference'],
                           'created': bill['created'], 'payments': history,
                           'changed': bill['revision'] != row['revision']}
        row['stage'] = ('paid' if row['bill']['due_cents'] == 0 else 'billed') if bill else ('ready' if row['ready'] else 'review')
        for audience in ('boss', 'contractor'):
            record = sent.get((row['job'], row['ju'], 'sent_' + audience))
            row['sent_' + audience] = record
            row['sent_' + audience + '_current'] = bool(record and record.get('revision') == row['revision'])
    return rows


def state(root, job):
    with LOCK, open_db(root) as db:
        rows = enrich(db, records(root, job))
        exports = [dict(e) for e in db.execute('SELECT * FROM exports WHERE job=? ORDER BY created DESC LIMIT 12', (job,))]
        for e in exports:
            e['detail'] = json.loads(e['detail'])
            e['detail'].pop('snapshots', None)
        totals = {'ready': sum(r['stage'] == 'ready' for r in rows),
                  'review': sum(r['stage'] == 'review' for r in rows),
                  'billed': sum(bool(r['bill']) for r in rows),
                  'paid': sum(r['stage'] == 'paid' for r in rows),
                  'ready_cents': sum(r['amount_cents'] for r in rows if r['stage'] == 'ready'),
                  'due_cents': sum(r['bill']['due_cents'] for r in rows if r['bill']),
                  'paid_cents': sum(r['bill']['paid_cents'] for r in rows if r['bill']),
                  'contractor': sum(r['sent_contractor_current'] for r in rows)}
        return {'job': job, 'jobs': jobs(root), 'rows': [public(r) for r in rows], 'totals': totals, 'exports': exports}


def select(root, job, selection):
    if not isinstance(selection, list) or not 1 <= len(selection) <= 500:
        raise ValueError('Choose at least one JU, up to 500.')
    index = {r['ju']: r for r in records(root, job)}
    result, seen = [], set()
    for item in selection:
        if not isinstance(item, dict) or item.get('ju') in seen or item.get('ju') not in index:
            raise ValueError('Invalid or duplicate JU selection.')
        row = index[item['ju']]
        if row['revision'] != item.get('revision'):
            raise Conflict('A selected JU changed. Refresh and review before continuing.')
        seen.add(row['ju']); result.append(row)
    return result


def event(db, kind, job, ju, detail):
    db.execute('INSERT INTO events(kind,job,ju,created,detail) VALUES(?,?,?,?,?)',
               (kind, job, ju, now(), canonical(detail)))


def mutate(root, data):
    if not isinstance(data, dict) or not re.fullmatch(r'[a-zA-Z0-9_-]{12,100}', str(data.get('request_id', ''))):
        raise ValueError('A valid request identifier is required.')
    kind, job = data.get('action'), data.get('job')
    reference = str(data.get('reference', '')).strip()
    if len(reference) > 250:
        raise ValueError('Reference is too long.')
    signature = hashlib.sha256(canonical(data).encode()).hexdigest()
    with LOCK, RECORD_LOCK, open_db(root) as db:
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute('SELECT * FROM requests WHERE id=?', (data['request_id'],)).fetchone()
        if prior:
            if prior['signature'] != signature:
                raise Conflict('This request identifier was already used for a different action.')
            return json.loads(prior['result'])
        rows = enrich(db, select(root, job, data.get('selection')))
        if kind == 'bill':
            for row in rows:
                if not row['ready'] or row['bill']:
                    raise ValueError('Only ready, not-yet-billed JUs can be marked billed: ' + row['ju'])
                db.execute('INSERT INTO bills(job,ju,amount,revision,snapshot,reference,created) VALUES(?,?,?,?,?,?,?)',
                    (job, row['ju'], row['amount_cents'], row['revision'], canonical(public(row)), reference, now()))
                event(db, 'billed', job, row['ju'], {'reference': reference, 'amount_cents': row['amount_cents'], 'revision': row['revision']})
        elif kind == 'payment':
            if len(rows) != 1:
                raise ValueError('Record a payment against one JU at a time.')
            row = rows[0]; bill = row['bill']; amount = money(data.get('amount'))
            if not bill or bill['id'] != data.get('bill_id'):
                raise Conflict('The billing entry changed. Refresh first.')
            if amount > bill['due_cents']:
                raise ValueError('Payment exceeds the remaining balance for this JU.')
            db.execute('INSERT INTO payments(bill,amount,reference,created) VALUES(?,?,?,?)', (bill['id'], amount, reference, now()))
            event(db, 'payment', job, row['ju'], {'amount_cents': amount, 'reference': reference, 'bill_id': bill['id']})
        elif kind == 'reverse_payment':
            if len(rows) != 1 or not rows[0]['bill']:
                raise ValueError('Choose one billed JU.')
            payment = db.execute('SELECT * FROM payments WHERE id=? AND bill=? AND reversed IS NULL',
                                 (data.get('payment_id'), rows[0]['bill']['id'])).fetchone()
            if not payment:
                raise Conflict('Payment already reversed or not found.')
            db.execute('UPDATE payments SET reversed=? WHERE id=?', (now(), payment['id']))
            event(db, 'payment_reversed', job, rows[0]['ju'], {'payment_id': payment['id'], 'reason': reference})
        elif kind == 'cancel_bill':
            if len(rows) != 1 or not rows[0]['bill'] or rows[0]['bill']['paid_cents']:
                raise ValueError('Choose one billed JU with no payments. Reverse mistaken payments first.')
            bill = rows[0]['bill']
            if data.get('bill_id') != bill['id']:
                raise Conflict('Billing entry changed. Refresh first.')
            db.execute('UPDATE bills SET cancelled=? WHERE id=?', (now(), bill['id']))
            event(db, 'billing_cancelled', job, rows[0]['ju'], {'bill_id': bill['id'], 'reason': reference})
        elif kind in ('sent_boss', 'sent_contractor'):
            for row in rows:
                event(db, kind, job, row['ju'], {'revision': row['revision'], 'reference': reference})
        else:
            raise ValueError('Unknown tracking action.')
        result = {'ok': True, 'count': len(rows)}
        db.execute('INSERT INTO requests VALUES(?,?,?)', (data['request_id'], signature, canonical(result)))
    backup(root)
    return result


def history(root, job, ju):
    if ju not in {r['ju'] for r in records(root, job)}:
        raise ValueError('JU not found.')
    with open_db(root) as db:
        return [dict(r) for r in db.execute('SELECT * FROM events WHERE job=? AND ju=? ORDER BY id DESC', (job, ju))]


def backup(root):
    """Keep a transaction-consistent recovery copy after ledger changes."""
    target = Path(root) / 'TRACKING' / 'tracking-recovery.sqlite3'
    with LOCK, open_db(root) as source, closing(sqlite3.connect(target)) as destination:
        source.backup(destination)


def ledger_csv(root, job):
    import csv, io
    data = state(root, job)
    out = io.StringIO(); writer = csv.writer(out)
    writer.writerow(['Job', 'JU', 'Address', 'Record status', 'Billing reference', 'Billed', 'Paid', 'Still owed', 'Sent to boss', 'Sent to contractor'])
    safe = lambda v: "'" + str(v) if str(v).lstrip().startswith(('=', '+', '-', '@')) else str(v)
    for r in data['rows']:
        b = r['bill'] or {}
        writer.writerow([safe(job), safe(r['ju']), safe(r['address']), r['stage'], safe(b.get('reference', '')),
                         f"{b.get('amount_cents',0)/100:.2f}", f"{b.get('paid_cents',0)/100:.2f}",
                         f"{b.get('due_cents',0)/100:.2f}", (r['sent_boss'] or {}).get('date', ''),
                         (r['sent_contractor'] or {}).get('date', '')])
    return '\ufeff' + out.getvalue()
