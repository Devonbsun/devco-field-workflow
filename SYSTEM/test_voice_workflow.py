import json
import unittest
import urllib.request
from urllib.error import HTTPError
from unittest.mock import patch
from voice_workflow import clean_note,match_close
import test_simple_flow as flow
from note_store import read_note

class Cleanup(unittest.TestCase):
    def test_fillers_and_uncertainty(self):
        result=clean_note('Um, I think it looks like copper, uh, maybe two drops. No work performed.')
        self.assertEqual(result['note'],'I think it looks like copper, maybe two drops. No work performed.')
        self.assertFalse(result['needs_review'])
    def test_explicit_corrections_preserve_earlier_observations(self):
        cases={
          'I checked the pole. There is copper on the pole, sorry, I mean there is fiber on the pole.':'Checked the pole. There is fiber on the pole.',
          'No Windstream on the pole and there is copper underground, sorry I mean there is fiber underground.':'No Windstream on the pole and there is fiber underground.',
          'I took two photos, sorry, three photos.':'I took three photos.',
          'There is copper underground, sorry I mean fiber underground.':'There is fiber underground.',
          'I did not transfer it. Sorry, I mean I did transfer it.':'I did transfer it.',
        }
        for raw,expected in cases.items():
            with self.subTest(raw=raw):self.assertEqual(clean_note(raw)['note'],expected)
    def test_ambiguous_correction_keeps_evidence(self):
        result=clean_note('Copper and fiber are underground, sorry I mean on the pole.')
        self.assertTrue(result['needs_review']);self.assertIn('Copper and fiber',result['note']);self.assertIn('on the pole',result['note'])
        result=clean_note('No copper underground, sorry fiber underground.')
        self.assertTrue(result['needs_review']);self.assertIn('No copper',result['note'])
    def test_no_notes_and_filler_only(self):
        self.assertEqual(clean_note('No notes')['note'],'')
        with self.assertRaises(ValueError):clean_note('um uh erm')
    def test_close_options_and_ambiguity(self):
        cases={'A D S S':'ADSS','Transfer was already completed':'TRANSFER ALREADY COMPLETED','no services on the pole':'NO SERVICES ON POLE','No identifiable Windstream line':'NO IDENTIFIABLE WINDSTREAM LINE ON POLE','fiber transfer completed':'FIBER TRANSFER COMPLETED','we completed the transfer':'FIBER TRANSFER COMPLETED','pending':'PENDING','already completed sorry I mean ADSS':'ADSS'}
        for raw,expected in cases.items():self.assertEqual(match_close(raw)['close'],expected)
        for raw in ['not ADSS','ADSS or pending','maybe completed','transfer not completed','hello','no Windstream and no services']:
            self.assertIsNone(match_close(raw)['close'])

class VoiceEndpoints(unittest.TestCase):
    def setUp(self):
        self.fixture=flow.SimpleFlow();self.fixture.setUp()
        self.base=self.fixture.base;self.folder=self.fixture.folder
    def tearDown(self):self.fixture.tearDown()
    def post(self,path,payload):
        req=urllib.request.Request(self.base+path,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req) as response:return json.load(response)
    def test_voice_note_saved_before_close_without_finalizing(self):
        result=self.post('/voice-note',dict(job='TEST',ju='101',transcript='Um, I surveyed the pole. No services on the pole.',expected_note=''))
        self.assertEqual(read_note(self.folder),'Surveyed the pole. No services on the pole.')
        self.assertFalse((self.folder/'BILLING_AND_NOTES.txt').exists())
        history=list((self.folder/'VOICE_HISTORY').glob('*.json'));self.assertEqual(len(history),1)
        self.assertIn('Um,',json.loads(history[0].read_text())['transcript'])
        result=self.post('/voice-close',dict(job='TEST',ju='101',transcript='no services on the pole'))
        self.assertEqual(result['close'],'NO SERVICES ON POLE')
        self.assertFalse((self.folder/'BILLING_AND_NOTES.txt').exists())
    def test_note_and_active_ju_conflicts_preserve_records(self):
        import devco_app as app
        app.save_note(self.folder,'Typed note')
        payload=dict(job='TEST',ju='101',transcript='Replace it',expected_note='')
        with self.assertRaises(HTTPError) as caught:self.post('/voice-note',payload)
        self.assertEqual(caught.exception.code,409);caught.exception.close()
        self.assertEqual(read_note(self.folder),'Typed note')
        app.active_ju='102';payload['expected_note']='Typed note'
        with self.assertRaises(HTTPError) as caught:self.post('/voice-note',payload)
        self.assertEqual(caught.exception.code,409);caught.exception.close()
        self.assertEqual(read_note(self.folder),'Typed note')
    def test_only_billing_page_autostarts_and_manual_controls_remain(self):
        home=self.fixture.get('/');billing=self.fixture.get('/billing')
        self.assertNotIn('devcoVoiceConfig',home)
        self.assertIn('"autostart": true',billing)
        self.assertIn('Confirm &amp; finalize JU',billing)
        self.assertIn('name="close" value="ADSS"',billing)
        self.assertIn('name="code"',billing)
        self.assertNotIn('mic-button',billing)
        import devco_app as app
        self.assertIn('"autostart": false',app.billing_page('Need another photo'))

if __name__=='__main__':unittest.main()
