"""Audit Solocator originals against every current project's JU photos.

The audit reports missing evidence without altering active navigation, billing,
completion state, or a user's existing photo assignments.
"""
from pathlib import Path
from datetime import datetime
import collections, csv, hashlib, io, json, math, subprocess, time

REPO = Path.home() / "DEVCO_FIELD"
PHOTOS = Path("/storage/emulated/0/Pictures/Solocator")
STATE = REPO / ".gps_photo_audit_state.json"
CACHE = REPO / ".gps_photo_cache.json"
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
# User permits photos taken away from the pole; distance is a screening aid.
NEARBY_METERS = 300
AUDIT_VERSION = 2

def distance(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    v = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 12742000 * math.asin(min(1, math.sqrt(v)))

def bearing(a, b):
    lat1, lat2 = map(math.radians, (a[0], b[0]))
    delta = math.radians(b[1] - a[1])
    return (math.degrees(math.atan2(math.sin(delta) * math.cos(lat2),
            math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta))) + 360) % 360

def current_sources():
    infos, photos = [], []
    for job in sorted((REPO / "JOBS").iterdir()):
        root = job / ("JOB_PACKET_CURRENT" if (job / "JOB_PACKET_CURRENT").is_dir() else "3_JU_FILES")
        for info in sorted(root.glob("*/transfer_info.txt")):
            values = {}
            for line in info.read_text(errors="replace").splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    values[key.strip()] = value.strip()
            try:
                lat, lon = float(values["Latitude"]), float(values["Longitude"])
            except (KeyError, ValueError):
                continue
            infos.append({"path": str(info), "job": job.name,
                          "ju": values.get("JU Record", info.parent.name.split(" - ")[0]),
                          "address": values.get("Address", ""), "lat": lat, "lon": lon})
            for p in info.parent.rglob("*"):
                if p.is_file() and not p.is_symlink() and p.suffix.lower() in IMAGE_TYPES:
                    photos.append(p)
    return infos, photos

def refresh(force=False):
    from project_directory import DIRECTORY, atomic_text, publish_file, remember, sha
    points, assigned = current_sources()
    originals = sorted(p for p in PHOTOS.rglob("*") if p.is_file() and not p.is_symlink()
                       and p.suffix.lower() in IMAGE_TYPES and time.time()-p.stat().st_mtime > 5)
    paths = sorted(set(originals + assigned + [Path(p["path"]) for p in points]))
    stats = {str(p): [p.stat().st_size, p.stat().st_mtime_ns] for p in paths}
    fingerprint = hashlib.sha256(json.dumps(stats, sort_keys=True).encode()).hexdigest()
    old = json.loads(STATE.read_text()) if STATE.exists() else {}
    if not force and old.get("version") == AUDIT_VERSION and old.get("fingerprint") == fingerprint:
        return old.get("summary", {})
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    def digest(p):
        key = str(p)
        data = cache.get(key, {})
        if data.get("stat") != stats[key]:
            data = {"stat": stats[key], "sha256": sha(p)}
            cache[key] = data
        return data["sha256"]
    assigned_hashes = {digest(p) for p in assigned}
    pending = []
    for p in originals:
        digest(p)
        if "gps" not in cache[str(p)] or "direction" not in cache[str(p)]:
            pending.append(p)
    if pending:
        result = subprocess.run(["exiftool", "-json", "-n", "-GPSLatitude", "-GPSLongitude",
                                 "-GPSHPositioningError", "-DateTimeOriginal", "-GPSImgDirection", "-GPSImgDirectionRef"] + [str(p) for p in pending],
                                capture_output=True, text=True, timeout=120, check=True)
        for meta in json.loads(result.stdout):
            data = cache[meta["SourceFile"]]
            data["gps"] = ([meta["GPSLatitude"], meta["GPSLongitude"]]
                           if meta.get("GPSLatitude") is not None and meta.get("GPSLongitude") is not None else None)
            data["taken"] = meta.get("DateTimeOriginal")
            data["direction"] = meta.get("GPSImgDirection")
            data["direction_ref"] = meta.get("GPSImgDirectionRef")
    atomic_text(CACHE, json.dumps(cache))
    review, counts = [], collections.Counter()
    for p in originals:
        item = cache[str(p)]
        counts["checked"] += 1
        if item["sha256"] in assigned_hashes:
            counts["in_current_ju_folders"] += 1
            continue
        gps = item.get("gps")
        nearest = sorted([dict(point, meters=round(distance(gps, (point["lat"], point["lon"])), 2))
                          for point in points], key=lambda v: v["meters"])[:2] if gps else []
        if nearest and nearest[0]["meters"] > NEARBY_METERS:
            counts["outside_nearby_range"] += 1
            continue
        if not gps:
            reason = "GPS unavailable; confirm job and JU"
        elif not nearest:
            reason = "No current JU coordinates available"
        elif len(nearest) > 1 and nearest[1]["meters"] - nearest[0]["meters"] < 15:
            reason = "Nearby competing JUs; compare direction, sequence and visible pole details"
        else:
            reason = "Nearby unfiled candidate; connect using direction, sequence and pole evidence"
        reason = old.get("review_notes", {}).get(item["sha256"], reason)
        direction = item.get("direction")
        if direction is not None and item.get("direction_ref") == "T":
            for candidate in nearest:
                candidate["bearing"] = round(bearing(gps, (candidate["lat"], candidate["lon"])), 1)
                candidate["direction_difference"] = round(abs((direction-candidate["bearing"]+180)%360-180), 1)
        counts["needs_review"] += 1
        review.append({"path": str(p), "sha256": item["sha256"], "gps": gps, "nearest": nearest,
                       "reason": reason, "direction": direction, "direction_ref": item.get("direction_ref")})
    output = DIRECTORY / "Needs_Review"
    output.mkdir(parents=True, exist_ok=True)
    managed = {}
    for item in review:
        src = Path(item["path"])
        name = src.name
        if name in managed and managed[name] != item["sha256"]:
            name = src.stem + "_" + item["sha256"][:10] + src.suffix
        publish_file(src, output / "GPS_Photos" / name)
        item["review_file"] = name
        managed[name] = item["sha256"]
    for name, digest_value in old.get("review_files", {}).items():
        path = output / "GPS_Photos" / name
        if name not in managed and path.exists() and sha(path) == digest_value:
            remember(path)
            path.unlink()
    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerow(["Photo", "Review reason", "Nearest project", "Nearest JU", "Nearest address",
                     "Distance m", "Second project", "Second JU", "Second distance m",
                     "Latitude", "Longitude", "Photo GPS map", "Original photo", "Camera direction degrees",
                     "Direction reference", "Nearest bearing degrees", "Second bearing degrees"])
    for item in review:
        nearest = item["nearest"]
        a = nearest[0] if nearest else {}
        b = nearest[1] if len(nearest) > 1 else {}
        gps = item["gps"] or ["", ""]
        writer.writerow([item["review_file"], item["reason"], a.get("job", ""), a.get("ju", ""),
                         a.get("address", ""), a.get("meters", ""), b.get("job", ""), b.get("ju", ""),
                         b.get("meters", ""), gps[0], gps[1],
                         "https://www.google.com/maps?q=" + str(gps[0]) + "," + str(gps[1]) if item["gps"] else "",
                         item["path"], item.get("direction"), item.get("direction_ref"),
                         a.get("bearing", ""), b.get("bearing", "")])
    for path, content in [
        (output / "GPS_Photo_Review.csv", text.getvalue()),
        (output / "README.txt",
         "GPS PHOTO REVIEW\n\n" + str(counts["needs_review"]) +
         " unfiled photos near the current jobs need review.\nOpen GPS_Photos for the originals and "
         "GPS_Photo_Review.csv for candidate JUs, distances and map links.\n"
         "Photo GPS records where the camera stood, not necessarily the pole location.\n"
         "Nearby screening range: 300 metres; use compass direction, photo sequence and visible pole details.\n"
         "Farther unfiled originals are left in Solocator and omitted from this review.\n"
         "A nearby GPS position is evidence of location, not proof of completion.\n"
         "Confirmed photos belong in the authoritative JU folder; the same job packet then updates automatically.\n"),
        (output / "GPS_Photo_Audit.txt",
         "Checked: " + datetime.now().isoformat(timespec="seconds") + "\n" +
         json.dumps(dict(counts), indent=2) + "\n"
         "This audit includes original Solocator photos and both standard and legacy job packets.\n")]:
        if path.exists():
            remember(path)
        atomic_text(path, content)
    result = {"version": AUDIT_VERSION, "fingerprint": fingerprint, "summary": dict(counts),
              "review_files": managed, "review": review, "review_notes": old.get("review_notes", {})}
    atomic_text(STATE, json.dumps(result, indent=2))
    print("GPS photo audit", json.dumps(dict(counts)), flush=True)
    return dict(counts)

if __name__ == "__main__":
    print(json.dumps(refresh(force=True), indent=2))
