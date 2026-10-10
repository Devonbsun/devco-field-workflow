"""Small, complete JU packets; only derived photo copies are compressed."""
import csv
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import uuid
import zipfile

import tracking as t

LIMIT = 10_000_000
WORKER = threading.Lock()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def share_root(root):
    return (Path('/storage/emulated/0/DEVCO/Pole_Transfers/Send_Ready')
            if phone_root(root) else Path(root) / 'SHARE_TEST')


def phone_root(root):
    return Path(root).resolve() == (Path.home() / 'DEVCO_FIELD').resolve() and Path('/storage/emulated/0').is_dir()


def compact_photo(root, source):
    from PIL import Image, ImageOps, UnidentifiedImageError
    checksum = digest(source)
    cache = Path(root) / 'TRACKING/photo-cache'
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (checksum + '-2048-q88.jpg')
    if not target.exists():
        try:
            with Image.open(source) as original:
                picture = ImageOps.exif_transpose(original)
                picture.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                exif = picture.getexif().tobytes()
                if picture.mode != 'RGB':
                    if 'A' in picture.getbands():
                        canvas = Image.new('RGB', picture.size, 'white')
                        canvas.paste(picture, mask=picture.getchannel('A')); picture = canvas
                    else:
                        picture = picture.convert('RGB')
                temp = target.with_suffix('.tmp')
                picture.save(temp, 'JPEG', quality=88, optimize=True, exif=exif,
                             icc_profile=original.info.get('icc_profile'))
                temp.replace(target)
        except UnidentifiedImageError:
            # Preserve formats this installation cannot decode; never omit evidence.
            if source.stat().st_size >= LIMIT - 200000:
                raise ValueError('A photo cannot fit in a small packet: ' + source.name)
            return source, checksum
    chosen = target if target.stat().st_size < source.stat().st_size else source
    if chosen.stat().st_size >= LIMIT - 200000:
        raise ValueError('A photo cannot fit in a small packet: ' + source.name)
    return chosen, checksum


def csv_bytes(rows):
    stream = io.StringIO(); writer = csv.writer(stream)
    for row in rows:
        writer.writerow(["'" + str(v) if str(v).lstrip().startswith(('=', '+', '-', '@')) else v for v in row])
    return ('\ufeff' + stream.getvalue()).encode()


def master_tables(rows, audience):
    """One copy in PART_1 prevents repeated JU reports being added twice."""
    index = [['Job', 'JU', 'Address', 'Close code', 'Record check', 'Photo count', 'Billing codes']]
    billing = [['Job', 'JU', 'Billing code', 'Quantity']]
    if audience == 'boss':
        index[0] += ['Current priced subtotal', 'Billing reference', 'Billed amount', 'Payments recorded', 'Still owed']
        billing[0] += ['Current unit rate', 'Current line amount']
    for record in rows:
        bill = record.get('bill') or {}
        values = [record['job'], record['ju'], record['address'], record['close_code'],
                  'Ready' if record['ready'] else '; '.join(record['issues']), record['photo_count'],
                  '; '.join(l['code'] + ' x' + l['quantity'] for l in record['lines'])]
        if audience == 'boss':
            values += [f"{record['amount_cents']/100:.2f}", bill.get('reference', ''),
                       f"{bill.get('amount_cents',0)/100:.2f}", f"{bill.get('paid_cents',0)/100:.2f}",
                       f"{bill.get('due_cents',0)/100:.2f}"]
        index.append(values)
        for line in record['lines']:
            values = [record['job'], record['ju'], line['code'], line['quantity']]
            if audience == 'boss':
                values += ['' if line['rate_cents'] is None else f"{line['rate_cents']/100:.2f}",
                           '' if line['total_cents'] is None else f"{line['total_cents']/100:.2f}"]
            billing.append(values)
    return {'ALL_JUS.csv': csv_bytes(index), 'ALL_BILLING_CODES.csv': csv_bytes(billing)}


def documents(record, audience, photos, packet_id):
    lines = record['lines']
    bill = record.get('bill')
    text = [f"JOB: {record['job']}", f"JU: {record['ju']}", f"ADDRESS: {record['address']}",
            f"POLE COORDINATES: {record['latitude']}, {record['longitude']}",
            f"CLOSE CODE: {record['close_code'] or 'Not verified'}", '', 'BILLING CODES:']
    text += [f"{line['code']} x{line['quantity']}" for line in lines] or ['No codes recorded']
    text += ['', 'FIELD NOTES:', record['note'] or 'No saved closeout note.', '',
             'RECORD CHECK: ' + ('Ready' if record['ready'] else '; '.join(record['issues'])),
             f"PHOTOS: {record['photo_count']} total; {len(photos)} in this part.",
             'Photo copies are reduced for sharing. Full-resolution originals remain with the field records.',
             'If this JU spans parts, keep all parts together.', 'PACKET: ' + packet_id]
    if audience == 'boss':
        text += ['', 'YOUR BILLING SUMMARY:', 'Recorded billing reference: ' + ((bill or {}).get('reference') or 'None'),
                 'Billing status: ' + ('Recorded as billed' if bill else 'Not marked billed'),
                 f"Current saved codes, priced subtotal: ${record['amount_cents']/100:.2f}"]
        if bill:
            text += [f"Billed amount: ${bill['amount_cents']/100:.2f}",
                     f"Received: ${bill['paid_cents']/100:.2f}", f"Still owed: ${bill['due_cents']/100:.2f}"]
            if bill['changed']:
                text.append('REVIEW: the field record changed after billing; the billed amount has not been changed.')
    text_value = '\n'.join(text) + '\n'
    page = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>JU ' + html.escape(record['ju']) + '</title><style>body{max-width:900px;margin:auto;padding:20px;font:16px system-ui;color:#16222b}'
            'pre{white-space:pre-wrap;font:inherit;line-height:1.5}img{width:100%;height:auto}figure{margin:20px 0}figcaption{overflow-wrap:anywhere}</style>'
            '<h1>JU ' + html.escape(record['ju']) + '</h1><pre>' + html.escape(text_value) + '</pre>')
    for name in photos:
        page += '<figure><img src="photos/' + html.escape(name, quote=True) + '"><figcaption>' + html.escape(name) + '</figcaption></figure>'
    headers = ['Job', 'JU', 'Address', 'Close code', 'Billing code', 'Quantity']
    if audience == 'boss':
        headers += ['Current unit rate', 'Current line amount']
    data = [headers]
    for line in lines:
        row = [record['job'], record['ju'], record['address'], record['close_code'], line['code'], line['quantity']]
        if audience == 'boss':
            row += ['' if line['rate_cents'] is None else f"{line['rate_cents']/100:.2f}",
                    '' if line['total_cents'] is None else f"{line['total_cents']/100:.2f}"]
        data.append(row)
    return {'JU_REPORT.txt': text_value.encode(), 'OPEN_JU.html': page.encode(), 'BILLING_CODES.csv': csv_bytes(data)}


def save_status(root, ident, status, detail):
    with t.LOCK, t.open_db(root) as db:
        db.execute('UPDATE exports SET status=?,detail=? WHERE id=?', (status, t.canonical(detail), ident))


def create(root, job, selection, audience):
    if audience not in ('boss', 'contractor'):
        raise ValueError('Choose Boss or Contractor.')
    with t.LOCK, t.open_db(root) as db:
        busy = db.execute("SELECT id FROM exports WHERE status IN ('queued','building')").fetchone()
        if busy:
            raise t.Conflict('A packet is being prepared. Wait for it to finish.')
        rows = t.enrich(db, t.select(root, job, selection))
        ident = uuid.uuid4().hex
        detail = {'count': len(rows), 'progress': 0, 'snapshots': [t.public(r) for r in rows]}
        db.execute('INSERT INTO exports VALUES(?,?,?,?,?,?)', (ident, job, audience, 'queued', t.now(), t.canonical(detail)))
    thread = threading.Thread(target=build, args=(Path(root), ident, job, rows, audience), daemon=True, name='devco-small-packets')
    thread.start()
    return {'ok': True, 'export_id': ident}


def build(root, ident, job, rows, audience, limit=LIMIT):
    """Create staged ZIPs, verify coverage/size, then publish one current set."""
    detail = {'count': len(rows), 'progress': 0, 'snapshots': [t.public(r) for r in rows]}
    stage = None
    try:
        with WORKER:
            save_status(root, ident, 'building', detail)
            stage = Path(tempfile.mkdtemp(prefix='packet-', dir=Path(root) / 'TRACKING'))
            # A unit is one photo plus its JU record. Metadata repeats across parts,
            # so a part always makes sense independently and no photo is discarded.
            units, manifest = [], []
            for index, record in enumerate(rows):
                base = job + '/JU_' + record['ju']
                if not record['_photos']:
                    units.append((record, None, None))
                for number, source in enumerate(record['_photos'], 1):
                    compact, original_hash = compact_photo(root, source)
                    name = f'PHOTO_{number:03d}' + compact.suffix.lower()
                    relative = base + '/photos/' + name
                    units.append((record, relative, compact))
                    manifest.append({'ju': record['ju'], 'file': relative, 'original_name': source.name,
                                     'original_sha256': original_hash, 'shared_sha256': digest(compact),
                                     'original_bytes': source.stat().st_size, 'shared_bytes': compact.stat().st_size})
                detail['progress'] = index + 1
                save_status(root, ident, 'building', detail)
            groups, group, estimated = [], [], 0
            for record, relative, source in units:
                # Reserve enough room for repeated report/CSV/HTML and manifest rows.
                estimate = (source.stat().st_size if source else 0) + len(t.canonical(t.public(record)).encode()) * 5 + 14000
                if estimate > limit:
                    raise ValueError('A JU record or photo is too large for this packet limit.')
                if group and estimated + estimate >= limit - min(500000, limit // 10):
                    groups.append(group); group = []; estimated = 0
                group.append((record, relative, source)); estimated += estimate
            if group:
                groups.append(group)
            parts, covered = [], []
            for part_no, group in enumerate(groups, 1):
                filename = f'PART_{part_no}.zip'
                path = stage / filename
                group_rows = {r['ju']: r for r, _, _ in group}
                photo_paths = [rel for _, rel, _ in group if rel]
                part_manifest = [p for p in manifest if p['file'] in photo_paths]
                with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED) as archive:
                    if part_no == 1:
                        for name, content in master_tables(rows, audience).items():
                            archive.writestr(name, content)
                    for record, relative, source in group:
                        if source:
                            archive.write(source, relative); covered.append(relative)
                    for ju, record in group_rows.items():
                        names = [Path(rel).name for r, rel, _ in group if r['ju'] == ju and rel]
                        for name, value in documents(record, audience, names, ident).items():
                            archive.writestr(job + '/JU_' + ju + '/' + name, value)
                    # No pay amounts or private payment references in contractor copies.
                    archive.writestr('PHOTO_MANIFEST.json', json.dumps(part_manifest, indent=2))
                    archive.writestr('START_HERE.html', '<!doctype html><meta charset="utf-8"><h1>Job ' + html.escape(job) + '</h1><p>Part ' + str(part_no) + ' of ' + str(len(groups)) + '. Extract this ZIP, then open a JU below.</p>' + ''.join('<p><a href="' + job + '/JU_' + ju + '/OPEN_JU.html">JU ' + ju + ' — ' + html.escape(r['address']) + '</a></p>' for ju, r in group_rows.items()))
                    archive.writestr('README.txt', f'Project {job}\nPart {part_no} of {len(groups)}\nRecipient: {audience}\nExtract this ZIP, then open START_HERE.html or any JU_REPORT.txt.\nPART_1 has ALL_JUS.csv and ALL_BILLING_CODES.csv for the entire set. Use these once for totals; reports may repeat when one JU spans parts.\nSend every part in this set. Every ZIP opens independently.\nPhoto copies are smaller; field originals are unchanged.\nPreparation is not proof of sending, acceptance, billing, or payment.\nPacket ID: {ident}\n')
                with zipfile.ZipFile(path) as archive:
                    if archive.testzip():
                        raise ValueError('Packet integrity check failed.')
                if path.stat().st_size >= limit:
                    raise ValueError('Packet exceeded the size limit; originals are unchanged.')
                parts.append({'name': filename, 'bytes': path.stat().st_size, 'sha256': digest(path), 'jus': sorted(group_rows)})
            if sorted(covered) != sorted(m['file'] for m in manifest):
                raise ValueError('Photo coverage check failed.')
            # Reject source changes made while the packet was being built.
            t.select(root, job, [{'ju': r['ju'], 'revision': r['revision']} for r in rows])
            destination = share_root(root) / job / 'Small_Packets' / audience.title()
            destination.parent.mkdir(parents=True, exist_ok=True)
            archive_root = (Path('/storage/emulated/0/DEVCO/Backups/Tracking_Packets')
                            if phone_root(root) else Path(root) / 'TRACKING/packet-history')
            archive_root.mkdir(parents=True, exist_ok=True)
            # Publish on the same filesystem. Keep previous packets as actual evidence.
            newdir = destination.with_name('.' + destination.name + '-' + ident)
            newdir.mkdir()
            try:
                for part in parts:
                    shutil.copy2(stage / part['name'], newdir / part['name'])
                    if digest(newdir / part['name']) != part['sha256']:
                        raise ValueError('Packet copy verification failed.')
                (newdir / 'README.txt').write_text(f'Job {job}\nSend all {len(parts)} PART files. Each is below 10 MB.\nRecipient: {audience}\nPacket ID: {ident}\n')
                olddir = None
                if destination.exists():
                    olddir = archive_root / (job + '-' + audience + '-' + ident)
                    shutil.move(str(destination), olddir)
                try:
                    newdir.rename(destination)
                except Exception:
                    if olddir: shutil.move(str(olddir), destination)
                    raise
            finally:
                if newdir.exists(): shutil.rmtree(newdir)
            detail.update({'parts': parts, 'folder': str(destination), 'original_bytes': sum(r['original_bytes'] for r in rows),
                           'shared_bytes': sum(p['bytes'] for p in parts), 'photo_count': len(manifest), 'audience': audience})
            with t.LOCK, t.open_db(root) as db:
                # The current stable filenames are replaced; older entries stay in history.
                db.execute("UPDATE exports SET status='archived' WHERE job=? AND audience=? AND status='ready' AND id<>?", (job, audience, ident))
            save_status(root, ident, 'ready', detail)
            t.backup(root)
    except Exception as error:
        detail['error'] = str(error)
        save_status(root, ident, 'failed', detail)
    finally:
        if stage: shutil.rmtree(stage, ignore_errors=True)


def packet_file(root, ident, name):
    with t.open_db(root) as db:
        row = db.execute('SELECT * FROM exports WHERE id=?', (ident,)).fetchone()
    if not row or row['status'] != 'ready':
        raise ValueError('This packet is no longer current. Open the latest packet.')
    detail = json.loads(row['detail'])
    meta = next((p for p in detail['parts'] if p['name'] == name), None)
    if not meta or Path(name).name != name:
        raise ValueError('Packet file not found.')
    path = share_root(root) / row['job'] / 'Small_Packets' / row['audience'].title() / name
    if not path.is_file() or digest(path) != meta['sha256']:
        raise ValueError('Packet changed or missing. Build a fresh packet.')
    return path


def mark_sent(root, ident, request_id, reference=''):
    # Record the exported revision, even if a newer field revision now exists.
    if not re.fullmatch(r'[a-zA-Z0-9_-]{12,100}', str(request_id)) or len(reference) > 250:
        raise ValueError('Invalid send confirmation.')
    signature = t.canonical(['packet_sent', ident, reference])
    with t.LOCK, t.open_db(root) as db:
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
        if prior:
            if prior['signature'] != signature: raise t.Conflict('Request already used.')
            return json.loads(prior['result'])
        packet = db.execute('SELECT * FROM exports WHERE id=?', (ident,)).fetchone()
        if not packet or packet['status'] != 'ready':
            raise ValueError('Open the latest completed packet first.')
        detail = json.loads(packet['detail'])
        for record in detail['snapshots']:
            t.event(db, 'sent_' + packet['audience'], packet['job'], record['ju'],
                    {'revision': record['revision'], 'reference': reference, 'packet_id': ident})
        detail['sent_at'] = t.now()
        db.execute('UPDATE exports SET detail=? WHERE id=?', (t.canonical(detail), ident))
        result = {'ok': True, 'count': len(detail['snapshots'])}
        db.execute('INSERT INTO requests VALUES(?,?,?)', (request_id, signature, t.canonical(result)))
    t.backup(root)
    return result


def share(root, ident, name):
    path = packet_file(root, ident, name)
    command = Path('/data/data/com.termux/files/usr/bin/termux-open')
    if not command.exists():
        raise ValueError('Use Download or open the displayed folder on your phone.')
    subprocess.run([str(command), '--send', '--chooser', '--content-type', 'application/zip', str(path)],
                   check=True, capture_output=True, timeout=10)
    return {'ok': True, 'message': 'Share chooser requested. Choose the recipient yourself. If it does not appear, open the packet folder in My Files.'}


def recover(root):
    with t.open_db(root) as db:
        for row in db.execute("SELECT * FROM exports WHERE status IN ('queued','building')").fetchall():
            detail = json.loads(row['detail']); detail['error'] = 'App restarted during preparation. Build the packet again.'
            db.execute('UPDATE exports SET status=?,detail=? WHERE id=?', ('failed', t.canonical(detail), row['id']))
