"""Regression tests use disposable job folders, never production records."""
import tempfile, unittest, threading, urllib.request, urllib.parse, json
from pathlib import Path
from unittest.mock import patch
import devco_app as app

class SimpleFlow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        app.JOBS=Path(self.tmp.name)/"JOBS"
        app.STATE=Path(self.tmp.name)/"state.json"
        app.active_job="TEST";app.active_ju="101"
        app.photo_notice="Watching for new Solocator photos"
        self.folder=app.JOBS/"TEST"/"3_JU_FILES"/"101 - Test"
        self.folder.mkdir(parents=True)
        (self.folder/"transfer_info.txt").write_text("JU Record: 101\nAddress: Test street\nLatitude: 41.6\nLongitude: -93.6\n")
        second=self.folder.parent/"102 - Next";second.mkdir()
        (second/"transfer_info.txt").write_text("JU Record: 102\nAddress: Next street\nLatitude: 41.7\nLongitude: -93.7\n")
        (self.folder/"photos").mkdir()
        (self.folder/"photos"/"one.jpg").write_bytes(b"test")
        (self.folder/"photos"/"two.jpg").write_bytes(b"test")
        self.server=app.ThreadingHTTPServer(("127.0.0.1",0),app.H)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base="http://127.0.0.1:"+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.tmp.cleanup()
    def get(self,path):
        return urllib.request.urlopen(self.base+path).read().decode()
    def test_pages_status_and_form_identity(self):
        home=self.get("/")
        self.assertIn("1. Take photos",home)
        self.assertNotIn("FIELD TOOLS",home)
        self.assertNotIn("watchPosition",home)
        self.assertEqual(json.loads(self.get("/status"))["photos"],2)
        billing=self.get("/billing")
        self.assertIn('name="job" value="TEST"',billing)
        self.assertIn('name="ju" value="101"',billing)
        self.assertIn("localStorage",billing)
        self.assertIn("leaflet",self.get("/map"))
    def test_gps_cannot_replace_selected_pole(self):
        state=json.loads(self.get("/gps-nearest?lat=41.7&lon=-93.7&accuracy=5"))
        self.assertFalse(state["switched"]);self.assertEqual(app.active_ju,"101")
    def test_stale_form_does_not_save(self):
        data=urllib.parse.urlencode(dict(job="TEST",ju="102",close="TRANSFER ALREADY COMPLETED")).encode()
        response=urllib.request.urlopen(self.base+"/finish",data=data).read().decode()
        self.assertIn("Nothing was saved",response)
        self.assertFalse((self.folder/"BILLING_AND_NOTES.txt").exists())
    def test_successful_closeout_and_next_pole(self):
        with patch.object(app,"sync_job") as sync:
            data=urllib.parse.urlencode(dict(job="TEST",ju="101",close="FIBER TRANSFER COMPLETED",code="WC1F",qty_WC1F="1",note="test")).encode()
            response=urllib.request.urlopen(self.base+"/finish",data=data)
            self.assertIn("saved=TEST:101",response.url)
            self.assertEqual(app.active_ju,"102")
            self.assertIn("WC1F x1",(self.folder/"BILLING_AND_NOTES.txt").read_text())
            sync.assert_called_once()
    def test_photo_matching_and_validation(self):
        photo=Path(self.tmp.name)/"new.jpg";photo.write_bytes(b"image")
        with patch.object(app,"_photo_gps",return_value=(41.6,-93.6)),patch.object(app,"sync_job"):
            result=app.import_solocator_photo(photo,quiet=True)
            self.assertEqual(result["ju"],"101")
            self.assertTrue((self.folder/"photos"/"new.jpg").exists())
        self.assertFalse(app.save_closeout("TEST","101","PENDING",[],"")[0])
        self.assertFalse(app.save_closeout("TEST","101","FIBER TRANSFER COMPLETED",[],"")[0])

if __name__=="__main__":unittest.main()
