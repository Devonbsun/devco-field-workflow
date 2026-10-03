"""Durable per-JU note drafts, independent of closeout validation."""
import json, os, tempfile
from job_records import _parse_record

def read_note(folder):
    path=folder/"NOTE_DRAFT.json"
    if path.exists():
        return json.loads(path.read_text())["note"]
    return "\n".join(_parse_record(folder/"BILLING_AND_NOTES.txt")["notes"])

def save_note(folder, note):
    fd,path=tempfile.mkstemp(prefix=".note-",dir=folder)
    try:
        with os.fdopen(fd,"w") as f:
            json.dump({"note":note},f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(path,folder/"NOTE_DRAFT.json")
    finally:
        if os.path.exists(path):os.unlink(path)
