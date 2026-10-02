import os, re, math, shutil, subprocess, zipfile
from pathlib import Path
from datetime import datetime

ZIP = Path("/storage/emulated/0/Download/Des_Moines_59_Transfer_Files.zip")
PHOTOS = Path("/storage/emulated/0/Pictures/Solocator")
WORK = Path.home() / "des_moines_photo_work"

START = datetime(2026, 9, 26, 0, 0, 0)
END   = datetime(2026, 10, 1, 0, 0, 0)

# Conservative maximum automatic match distance.
MAX_METERS = 120

def distance_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2-lat1)
    dl = math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.atan2(math.sqrt(a), math.sqrt(1-a))

def photo_gps(path):
    r = subprocess.run(
        ["exiftool", "-n", "-s3", "-GPSLatitude", "-GPSLongitude", str(path)],
        capture_output=True, text=True
    )
    vals = [x.strip() for x in r.stdout.splitlines() if x.strip()]
    if len(vals) >= 2:
        try:
            return float(vals[0]), float(vals[1])
        except ValueError:
            pass
    return None

print("Preparing 59-transfer package...")

if WORK.exists():
    shutil.rmtree(WORK)
WORK.mkdir(parents=True)

with zipfile.ZipFile(ZIP, "r") as z:
    z.extractall(WORK)

# Find all transfer_info.txt files and extract their coordinates.
poles = []

for info in WORK.rglob("transfer_info.txt"):
    text = info.read_text(errors="ignore")

    ju = re.search(r"JU Record:\s*(\d+)", text)
    lat = re.search(r"Latitude:\s*(-?\d+(?:\.\d+)?)", text)
    lon = re.search(r"Longitude:\s*(-?\d+(?:\.\d+)?)", text)

    if ju and lat and lon:
        poles.append({
            "ju": ju.group(1),
            "lat": float(lat.group(1)),
            "lon": float(lon.group(1)),
            "folder": info.parent
        })

print(f"Loaded {len(poles)} pole locations.")

matched = []
review = []
no_gps = []

for photo in sorted(PHOTOS.iterdir()):
    if not photo.is_file() or photo.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        continue

    # Use Solocator filename date when available.
    m = re.search(
        r"Solocator-(\d{4})-(\d{2})-(\d{2})[ _](\d{2})-(\d{2})-(\d{2})",
        photo.name
    )

    if m:
        dt = datetime(*map(int, m.groups()))
    else:
        dt = datetime.fromtimestamp(photo.stat().st_mtime)

    if not (START <= dt < END):
        continue

    gps = photo_gps(photo)

    if not gps:
        no_gps.append(photo.name)
        continue

    lat, lon = gps

    nearest = None
    nearest_dist = float("inf")

    for pole in poles:
        d = distance_m(lat, lon, pole["lat"], pole["lon"])
        if d < nearest_dist:
            nearest_dist = d
            nearest = pole

    if nearest and nearest_dist <= MAX_METERS:
        photos_dir = nearest["folder"] / "photos"
        photos_dir.mkdir(exist_ok=True)

        destination = photos_dir / photo.name
        shutil.copy2(photo, destination)

        matched.append(
            f'{photo.name} -> JU {nearest["ju"]} ({nearest_dist:.1f} m)'
        )
    else:
        review.append(
            f'{photo.name} -> nearest JU {nearest["ju"] if nearest else "NONE"} '
            f'({nearest_dist:.1f} m)'
        )

report = WORK / "PHOTO_MATCH_REPORT.txt"

with report.open("w") as f:
    f.write("DES MOINES 59 TRANSFER PHOTO MATCH REPORT\n")
    f.write("Date window: 2026-09-26 through 2026-09-30\n\n")

    f.write(f"AUTOMATICALLY MATCHED: {len(matched)}\n")
    for x in matched:
        f.write(x + "\n")

    f.write(f"\nNEEDS REVIEW: {len(review)}\n")
    for x in review:
        f.write(x + "\n")

    f.write(f"\nNO GPS: {len(no_gps)}\n")
    for x in no_gps:
        f.write(x + "\n")

OUTPUT = Path("/storage/emulated/0/Download/Des_Moines_59_Transfer_Files_WITH_PHOTOS.zip")

if OUTPUT.exists():
    OUTPUT.unlink()

with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as z:
    for file in WORK.rglob("*"):
        if file.is_file():
            z.write(file, file.relative_to(WORK))

print()
print("DONE")
print(f"Matched: {len(matched)}")
print(f"Needs review: {len(review)}")
print(f"No GPS: {len(no_gps)}")
print()
print("Created:")
print(OUTPUT)
print()
print("Original Solocator photos were NOT changed.")
