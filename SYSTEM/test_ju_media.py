"""Real HTTP upload/closeout checks on disposable JUs only."""
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from unittest.mock import patch

import devco_app as app
from ju_media import save_upload, MAX_BYTES
from job_records import collect, _parse_record
from record_editor import revision
from voice_workflow import match_close

PNG = b'\x89PNG\r\n\x1a\n' + b'test-image'
MP4 = b'\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42' + b'test-video'


class MediaCloseout(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        app.JOBS=root/'JOBS';app.STATE=root/'state.json'
        app.active_job='TEST';app.active_ju='101'
        for job in ['TEST','OTHER']:
            for ju in ['101','102']:
                p=app.JOBS/job/'3_JU_FILES'/(ju+' - Pole');p.mkdir(parents=True)
                (p/'transfer_info.txt').write_text('JU Record: '+ju+'\nAddress: Test Street\nLatitude: 41.6\nLongitude: -93.6\n')
        self.folder=app._ju_folder('TEST','101')
        self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.H)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.tmp.cleanup()
    def upload(self,name='pole.png',data=PNG,job='TEST',ju='101',headers=None):
        req=Request(self.base+'/media-upload?'+urlencode(dict(job=job,ju=ju,name=name)),data=data,
                    headers=headers or {'Content-Type':'application/octet-stream','X-Devco-Upload':'1','Origin':self.base})
        return json.loads(urlopen(req).read())
    def get(self,path):return urlopen(self.base+path)
    def test_upload_pinned_to_job_and_ju_when_active_changes(self):
        before=revision(self.folder);app.active_job='OTHER';app.active_ju='102'
        self.assertTrue(self.upload()['ok']);self.assertTrue(self.upload('pole.mp4',MP4)['ok'])
        self.assertEqual((self.folder/'photos'/'pole.png').read_bytes(),PNG)
        self.assertEqual((self.folder/'videos'/'pole.mp4').read_bytes(),MP4)
        self.assertFalse((app._ju_folder('OTHER','102')/'photos').exists())
        self.assertEqual(revision(self.folder),before)
        self.assertEqual(app.active_job,'OTHER');self.assertEqual(app.active_ju,'102')
        items=json.loads(self.get('/media-list?job=TEST&ju=101').read())
        self.assertEqual({p['kind'] for p in items},{'photo','video'})
        self.assertEqual(collect(app.JOBS/'TEST')[0]['Photo Count'],1)
    def test_retry_and_name_collision_preserve_originals(self):
        a=self.upload();b=self.upload();c=self.upload(data=PNG+b'new')
        self.assertFalse(a['duplicate']);self.assertTrue(b['duplicate']);self.assertNotEqual(c['name'],a['name'])
        self.assertEqual((self.folder/'photos'/'pole.png').read_bytes(),PNG)
        self.assertEqual(len(list((self.folder/'photos').glob('*'))),2)
    def test_invalid_uploads_and_traversal_do_not_write(self):
        for name,data,job,ju in [('x.txt',PNG,'TEST','101'),('../x.png',PNG,'TEST','101'),('x.png',b'bad','TEST','101'),('x.png',PNG,'MISSING','101'),('x.png',PNG,'TEST','404'),('x.png',b'','TEST','101')]:
            with self.assertRaises(HTTPError) as e:self.upload(name,data,job,ju)
            self.assertEqual(e.exception.code,400)
        for headers in [{'Content-Type':'image/png'},{'X-Devco-Upload':'1','Origin':'https://bad.example'}]:
            with self.assertRaises(HTTPError):self.upload(headers=headers)
        self.assertFalse(list(self.folder.rglob('*.png')))
        self.assertFalse(list(self.folder.glob('.upload-*')))
    def test_size_interrupted_and_symlink_protection(self):
        for length,data in [(MAX_BYTES+1,PNG),(len(PNG)+5,PNG)]:
            with self.assertRaises(ValueError):save_upload(vars(app),'TEST','101','x.png',io.BytesIO(data),length)
        self.assertFalse(list(self.folder.glob('.upload-*')))
        outside=Path(self.tmp.name)/'outside';outside.mkdir()
        (self.folder/'videos').symlink_to(outside)
        with self.assertRaises(ValueError):save_upload(vars(app),'TEST','101','x.mp4',io.BytesIO(MP4),len(MP4))
        self.assertFalse(list(outside.iterdir()))
    def test_playback_ranges_and_media_traversal(self):
        self.upload('pole.mp4',MP4)
        items=json.loads(self.get('/media-list?job=TEST&ju=101').read());url=self.base+items[0]['url']
        self.assertEqual(urlopen(url).read(),MP4)
        for value,expected in [('bytes=4-11',MP4[4:12]),('bytes=-5',MP4[-5:]),('bytes=8-',MP4[8:])]:
            r=urlopen(Request(url,headers={'Range':value}));self.assertEqual(r.status,206);self.assertEqual(r.read(),expected)
        with self.assertRaises(HTTPError) as e:urlopen(Request(url,headers={'Range':'bytes=999-'}))
        self.assertEqual(e.exception.code,416)
        with self.assertRaises(HTTPError):self.get('/media?'+urlencode(dict(job='TEST',ju='101',kind='video',name='../pole.mp4')))
    def test_close_codes_state_reason_billing_and_photo_rules(self):
        self.upload('pole.mp4',MP4)
        self.assertFalse(app.save_closeout('TEST','101','NO WINDSTREAM VIOLATION',[],'')[0])
        self.upload()
        self.assertTrue(app.save_closeout('TEST','101','NO WINDSTREAM VIOLATION',[('WC1','1')],'No violation found')[0])
        rec=_parse_record(self.folder/'BILLING_AND_NOTES.txt')
        self.assertEqual(app._ju_state(self.folder),'COMPLETE');self.assertTrue(rec['completed_at']);self.assertEqual(rec['billing'],[('WC1','1')])
        self.assertFalse(app.save_closeout('TEST','101','UNABLE TO COMPLETE',[],'')[0])
        self.assertTrue(app.save_closeout('TEST','101','UNABLE TO COMPLETE',[('WC1','1')],'Access blocked')[0])
        row=collect(app.JOBS/'TEST')[0];self.assertEqual(row['State'],'COMPLETE');self.assertTrue(row['Completed At']);self.assertEqual(row['Billing Codes'],'WC1 x1')
        self.assertEqual(row['Close Code'],'UNABLE TO COMPLETE');self.assertEqual(row['Notes'],'Access blocked')
    def test_manual_voice_and_upload_pages(self):
        billing=self.get('/billing').read().decode()
        for code in ['NO WINDSTREAM VIOLATION','UNABLE TO COMPLETE']:self.assertIn('value="'+code+'"',billing)
        self.assertEqual(match_close('no Windstream violation')['close'],'NO WINDSTREAM VIOLATION')
        self.assertEqual(match_close('unable to complete')['close'],'UNABLE TO COMPLETE')
        self.assertEqual(match_close('no identifiable Windstream line')['close'],'NO IDENTIFIABLE WINDSTREAM LINE ON POLE')
        self.assertIsNone(match_close('maybe no Windstream violation')['close'])
        page=self.get('/upload?job=TEST&ju=101').read().decode()
        self.assertIn('accept="image/*,video/*" multiple',page);self.assertIn('"ju": "101"',page)
        for path in ['/record?job=TEST&ju=101','/packet-ju?job=TEST&ju=101','/']:
            self.assertIn('Upload photos or videos',self.get(path).read().decode())
        with patch('ju_media.subprocess.Popen') as launch:
            self.get('/upload-open?job=TEST&ju=101').read()
            self.assertEqual(launch.call_args.args[0],['termux-open-url',self.base+'/upload?job=TEST&ju=101'])
    def test_saved_upload_reports_spreadsheet_warning(self):
        with patch.object(app,'sync_job',side_effect=OSError('locked')):result=self.upload()
        self.assertTrue(result['ok']);self.assertIn('File saved',result['warning'])
        self.assertTrue((self.folder/'photos'/'pole.png').exists())


if __name__=='__main__':unittest.main()
