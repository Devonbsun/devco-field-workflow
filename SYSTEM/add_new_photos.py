from pathlib import Path
import subprocess, json, math, shutil, re

MASTER = Path.home() / "des_moines_photo_work" / "Des_Moines_59_Transfer_Files"
PHOTO_SOURCE = Path("/storage/emulated/0/Pictures/Solocator")
LOG = Path.home() / ".des_moines_processed_photos.txt"
MAX_DISTANCE_METERS = 120

def distance_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2-lat1)
    dl = math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def gps_from_photo(photo):
    cmd = [
        "exiftool", "-j", "-n",
        "-GPSLatitude", "-GPSLongitude",
        str(photo)
    ]
    try:
        data = json.loads(subprocess.check_output(cmd, text=True))[0]
        return float(data["GPSLatitude"]), float(data["GPSLongitude"])
    except:
        return None

# -----------------------------
# READ ALL MASTER POLES
# -----------------------------
poles = []

for folder in MASTER.iterdir():
    if not folder.is_dir():
        continue

    info = folder / "transfer_info.txt"
    if not info.exists():
        continue

    text = info.read_text(errors="ignore")

    def get(pattern):
        m = re.search(pattern, text, re.I | re.M)
        return m.group(1).strip() if m else ""

    ju = get(r"^JU(?: Record)?:\s*(.+)$")
    address = get(r"^Address:\s*(.*)$")
    lat = get(r"^Latitude:\s*([-\d.]+)")
    lon = get(r"^Longitude:\s*([-\d.]+)")

    if not lat or not lon:
        continue

    poles.append({
        "folder": folder,
        "ju": ju or folder.name.split()[0],
        "address": address or "GPS-based pole location",
        "lat": float(lat),
        "lon": float(lon)
    })

if not poles:
    print("ERROR: No master pole coordinates found.")
    raise SystemExit

# -----------------------------
# LOAD PROCESSED PHOTO LOG
# -----------------------------
processed = set()

if LOG.exists():
    processed = {
        x.strip()
        for x in LOG.read_text(errors="ignore").splitlines()
        if x.strip()
    }

photos = sorted(
    [
        p for p in PHOTO_SOURCE.iterdir()
        if p.is_file()
        and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        and p.name not in processed
    ],
    key=lambda p: p.stat().st_mtime
)

print()
print("======================================")
print("DES MOINES - ADD NEW PHOTOS")
print("Master:", MASTER)
print("Pole locations loaded:", len(poles))
print("Unprocessed Solocator photos:", len(photos))
print("======================================")

if not photos:
    print("No new photos to process.")
    raise SystemExit

matched = 0
review = 0
nogps = 0
processed_now = []

for photo in photos:

    gps = gps_from_photo(photo)

    if not gps:
        print()
        print("NO GPS:", photo.name)
        nogps += 1
        continue

    lat, lon = gps

    nearest = min(
        poles,
        key=lambda p: distance_m(lat, lon, p["lat"], p["lon"])
    )

    dist = distance_m(
        lat, lon,
        nearest["lat"], nearest["lon"]
    )

    print()
    print("--------------------------------------")
    print("PHOTO:", photo.name)
    print("GPS:", f"{lat:.6f}, {lon:.6f}")
    print("NEAREST JU:", nearest["ju"])
    print("ADDRESS:", nearest["address"])
    print("DISTANCE:", f"{dist:.1f} meters")

    if dist <= MAX_DISTANCE_METERS:

        dest = nearest["folder"] / "photos"
        dest.mkdir(exist_ok=True)

        target = dest / photo.name

        if not target.exists():
            shutil.copy2(photo, target)
            print("RESULT: ADDED TO MASTER")
        else:
            print("RESULT: ALREADY IN MASTER")

        matched += 1
        processed_now.append(photo.name)

    else:
        print("RESULT: NEEDS REVIEW - NOT COPIED")
        review += 1

# -----------------------------
# UPDATE LOG ONLY FOR MATCHES
# -----------------------------
if processed_now:
    with LOG.open("a") as f:
        for name in processed_now:
            f.write(name + "\n")

print()
print("======================================")
print("FINISHED")
print("Matched/added:", matched)
print("Needs review:", review)
print("No GPS:", nogps)
print("MASTER WAS NOT REBUILT OR DELETED")
print("======================================")
