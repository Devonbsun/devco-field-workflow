import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid
import zipfile

from PIL import Image
import tracking as t
import tracking_export as packets


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job = 'TEST'
        self.folder = self.pole('101')

    def tearDown(self):
        self.tmp.cleanup()

    def pole(self, ju, code='WC1', close='FIBER TRANSFER COMPLETED', note='Transferred and secured.'):
        folder = self.root / 'JOBS' / self.job / '3_JU_FILES' / (ju + ' - Address')
        (folder / 'photos').mkdir(parents=True)
        (folder / 'transfer_info.txt').write_text(f'JU Record: {ju}\nAddress: Test Street\nLatitude: 41.123456789\nLongitude: -93.987654321\n')
        (folder / 'BILLING_AND_NOTES.txt').write_text(f'STATUS: {close}\nBILLING:\n{code} x1\nNOTES:\n{note}\n')
        image = Image.effect_noise((1600, 1200), 70).convert('RGB')
        for n in (1, 2): image.save(folder / 'photos' / f'{n}.jpg', quality=95)
        return folder

    def row(self, ju='101'):
        return next(r for r in t.state(self.root, self.job)['rows'] if r['ju'] == ju)

    def action(self, kind, **extra):
        row = self.row()
        body = {'action': kind, 'job': self.job, 'selection': [{'ju': row['ju'], 'revision': row['revision']}],
                'request_id': uuid.uuid4().hex, 'reference': 'test reference'}
        body.update(extra)
        return body, t.mutate(self.root, body)

    def test_ledger_is_explicit_and_partial_payments_are_idempotent(self):
        row = self.row(); self.assertEqual(row['stage'], 'ready'); self.assertIsNone(row['bill'])
        self.action('bill'); row = self.row()
        self.assertEqual(row['bill']['amount_cents'], 3918)
        request, _ = self.action('payment', bill_id=row['bill']['id'], amount='10.25')
        t.mutate(self.root, request)
        row = self.row(); self.assertEqual(row['bill']['paid_cents'], 1025); self.assertEqual(row['bill']['due_cents'], 2893)
        self.assertEqual(len(row['bill']['payments']), 1)
        with self.assertRaises(ValueError): self.action('payment', bill_id=row['bill']['id'], amount='28.94')
        self.action('payment', bill_id=row['bill']['id'], amount='28.93')
        self.assertEqual(self.row()['stage'], 'paid')
        self.assertTrue((self.root/'TRACKING/tracking-recovery.sqlite3').exists())

    def test_corrections_preserve_history_and_do_not_rewrite_records(self):
        original = (self.folder/'BILLING_AND_NOTES.txt').read_bytes()
        self.action('bill'); bill = self.row()['bill']
        self.action('payment', bill_id=bill['id'], amount='5')
        with self.assertRaises(ValueError): self.action('cancel_bill', bill_id=bill['id'])
        payment = self.row()['bill']['payments'][0]
        self.action('reverse_payment', payment_id=payment['id'])
        self.action('cancel_bill', bill_id=bill['id'])
        self.assertEqual(self.row()['stage'], 'ready')
        self.assertEqual((self.folder/'BILLING_AND_NOTES.txt').read_bytes(), original)
        kinds = [e['kind'] for e in t.history(self.root, self.job, '101')]
        self.assertIn('billed', kinds); self.assertIn('payment', kinds); self.assertIn('payment_reversed', kinds)

    def test_changes_are_detected_and_billed_amount_stays_fixed(self):
        stale = self.row()
        self.action('bill')
        p=self.folder/'BILLING_AND_NOTES.txt';p.write_text(p.read_text().replace('WC1 x1', 'WC1 x2'))
        current = self.row()
        self.assertEqual(current['amount_cents'], 7836)
        self.assertEqual(current['bill']['amount_cents'], 3918)
        self.assertTrue(current['bill']['changed'])
        with self.assertRaises(t.Conflict):
            t.select(self.root, self.job, [{'ju': '101', 'revision': stale['revision']}])

    def test_missing_notes_unknown_rates_and_legacy_are_never_assumed_ready(self):
        self.pole('102', code='UNKNOWN')
        self.pole('103', note='')
        rows = t.state(self.root, self.job)['rows']
        self.assertEqual([r['ju'] for r in rows if r['ready']], ['101'])
        legacy = self.root/'JOBS/OLD/JOB_PACKET_CURRENT/201 - Test';legacy.mkdir(parents=True)
        (legacy/'transfer_info.txt').write_text('JU Record: 201\nAddress: Test\n')
        (legacy/'BILLING_AND_NOTES.txt').write_text('BILLING\n-----\nWC1F x1\nWORK / FIELD NOTES\n-----\nSaved old note.\nPHOTOS\n-----\n')
        (self.root/'JOBS/OLD/JOB_PACKET_CURRENT_SUMMARY.json').write_text(json.dumps([{'ju':'201','billing':{'WC1F':1}}]))
        row = t.state(self.root, 'OLD')['rows'][0]
        self.assertEqual(row['note'], 'Saved old note.');self.assertEqual(row['lines'][0]['code'], 'WC1F');self.assertFalse(row['ready'])

    def test_multi_ju_bill_rolls_back_if_any_selection_is_not_ready(self):
        self.pole('102', note='')
        rows = t.state(self.root, self.job)['rows']
        with self.assertRaises(ValueError):
            t.mutate(self.root, {'request_id':uuid.uuid4().hex,'job':self.job,'action':'bill',
                                'selection':[{'ju':r['ju'],'revision':r['revision']} for r in rows]})
        self.assertIsNone(self.row()['bill'])

    def test_packets_split_preserve_all_photos_and_hide_contractor_pay(self):
        self.action('bill', reference='PRIVATE_PAY_REFERENCE')
        before = {p: packets.digest(p) for p in self.folder.rglob('*') if p.is_file()}
        with t.open_db(self.root) as db:
            rows = t.enrich(db, t.records(self.root, self.job))
            ident=uuid.uuid4().hex
            db.execute('INSERT INTO exports VALUES(?,?,?,?,?,?)',(ident,self.job,'contractor','queued',t.now(),'{}'))
        one_photo = packets.compact_photo(self.root, rows[0]['_photos'][0])[0].stat().st_size
        limit = one_photo + 90000
        packets.build(self.root, ident, self.job, rows, 'contractor', limit=limit)
        with t.open_db(self.root) as db: result = dict(db.execute('SELECT * FROM exports WHERE id=?',(ident,)).fetchone())
        self.assertEqual(result['status'], 'ready', result['detail'])
        detail=json.loads(result['detail']);self.assertEqual(detail['photo_count'],2);self.assertGreater(len(detail['parts']),1)
        names=[]
        for part in detail['parts']:
            self.assertLess(part['bytes'],limit)
            path=packets.packet_file(self.root,ident,part['name'])
            with zipfile.ZipFile(path) as z:
                self.assertIn('START_HERE.html',z.namelist());self.assertIsNone(z.testzip())
                for name in z.namelist():
                    if '/photos/' in name: names.append(name)
                    elif name.endswith(('.txt','.csv','.html','.json')):
                        text=z.read(name).decode();self.assertNotIn('PRIVATE_PAY_REFERENCE',text);self.assertNotIn('39.18',text)
        self.assertEqual(len(names),len(set(names)));self.assertEqual(len(names),2)
        self.assertEqual(before,{p:packets.digest(p) for p in before})
        self.assertFalse(self.row()['sent_contractor'])
        # A send confirmation records the packet revision, not a later edited record.
        p=self.folder/'BILLING_AND_NOTES.txt';p.write_text(p.read_text()+'New field evidence.\n')
        packets.mark_sent(self.root,ident,uuid.uuid4().hex)
        self.assertTrue(self.row()['sent_contractor']);self.assertFalse(self.row()['sent_contractor_current'])

    def test_boss_export_has_pay_and_never_includes_private_draft(self):
        row=t.records(self.root,self.job)[0]
        (self.folder/'NOTE_DRAFT.json').write_text(json.dumps({'note':'PRIVATE UNSAVED DRAFT'}))
        row=t.records(self.root,self.job)[0]
        self.assertFalse(row['ready'])
        docs=packets.documents(row,'boss',[],uuid.uuid4().hex)
        self.assertIn('39.18',docs['JU_REPORT.txt'].decode())
        self.assertNotIn('PRIVATE UNSAVED DRAFT',b''.join(docs.values()).decode())

    def test_compact_photo_keeps_gps_and_original_bytes(self):
        from PIL.TiffImagePlugin import IFDRational as R
        source=self.folder/'photos/gps.jpg'
        exif=Image.Exif();exif[274]=6
        exif[34853]={1:'N',2:(R(41),R(30),R(12)),3:'W',4:(R(93),R(15),R(6))}
        Image.effect_noise((3000,2000),50).convert('RGB').save(source,quality=100,exif=exif)
        original=packets.digest(source)
        compact,_=packets.compact_photo(self.root,source)
        self.assertNotEqual(compact,source)
        self.assertEqual(original,packets.digest(source))
        with Image.open(compact) as photo:
            self.assertLessEqual(max(photo.size),2048)
            gps=photo.getexif().get_ifd(34853)
            self.assertEqual(gps[1],'N');self.assertEqual(gps[3],'W')
            self.assertEqual(tuple(map(float,gps[2])),(41,30,12))


if __name__ == '__main__': unittest.main()
