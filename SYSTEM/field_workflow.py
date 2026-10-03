import subprocess
import csv
import time
import re
import math
import os
import zipfile
import xml.etree.ElementTree as ET
from job_records import sync_job
from pathlib import Path

PHOTOS = Path("/storage/emulated/0/Pictures/Solocator")

# Multi-job paths are supplied by SYSTEM/field.
JOB = Path(os.environ.get("DEVCO_JOB", "")).expanduser()
JOB_ID = os.environ.get("DEVCO_JOB_ID", JOB.name if str(JOB) else "")
WORK = Path(os.environ.get("DEVCO_JU_ROOT", "")).expanduser()

if not str(WORK) or not WORK.exists():
    raise SystemExit(
        "DEVCO_JU_ROOT is not set to a valid JU folder. "
        "Start this workflow with SYSTEM/field."
    )

# For the new architecture, the selected job's 3_JU_FILES directory is
# the authoritative per-JU working copy. No Des Moines legacy MASTER path
# is touched by this script.
MASTER = WORK

# How close a photo must be to a JU to automatically identify it.
MAX_MATCH_METERS = 120

workflow_dir = JOB / "1_JOB_WORKFLOW"
workflow_dir.mkdir(parents=True, exist_ok=True)
MASTER_LOG = workflow_dir / f"{JOB_ID}_FIELD_PRODUCTION.csv"


# Test billing codes. We'll replace these with the complete list later.
CODES = {
    "1": "WC1F",
    "2": "PM2A",
    "3": "PE1-3G",
    "4": "TRIP CHARGE [CODE PENDING]",

    "5": "BM80",
    "6": "BM80PF",
    "7": "BM82",
    "8": "BM83(A)",
    "9": "BM83(B)",
    "10": "PE1-3",
    "11": "PE1-3G(JO)",
    "12": "PF1-6A(JO)",
    "13": "PM11",
    "14": "PM2",
    "15": "PM2(JO)",
    "16": "PM2AF",
    "17": "PM2C",
    "18": "PM52",
    "19": "PM52(A)",
    "20": "PM54(A)",
    "21": "PM92",
    "22": "R1-5(A)",
    "23": "R1-5(AF)",
    "24": "WC1",
    "25": "WEC1",
    "26": "WEC1F",
    "27": "WPE1",
    "28": "WPE1(JO)",
    "29": "WSEA(A)",
    "30": "XXCOE",
    "31": "XXCW",
    "32": "XXPF",
    "33": "XXPM11",
    "34": "XXPM5",
    "35": "XXSEA(A)",
    "36": "XXSTRAND",
}


def distance_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1)
        * math.cos(p2)
        * math.sin(dl / 2) ** 2
    )

    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def photo_gps(path):
    try:
        r = subprocess.run(
            [
                "exiftool",
                "-n",
                "-s3",
                "-GPSLatitude",
                "-GPSLongitude",
                str(path),
            ],
            capture_output=True,
            text=True,
        )

        vals = [
            x.strip()
            for x in r.stdout.splitlines()
            if x.strip()
        ]

        if len(vals) >= 2:
            return float(vals[0]), float(vals[1])

    except Exception:
        pass

    return None


def load_poles():
    poles = []

    if not WORK.exists():
        return poles

    for info in WORK.rglob("transfer_info.txt"):

        try:
            text = info.read_text(errors="ignore")
        except Exception:
            continue

        ju = re.search(r"JU Record:\s*(\d+)", text)
        lat = re.search(
            r"Latitude:\s*(-?\d+(?:\.\d+)?)",
            text
        )
        lon = re.search(
            r"Longitude:\s*(-?\d+(?:\.\d+)?)",
            text
        )

        # Try to find address if it's in transfer_info.txt
        address = re.search(
            r"Address:\s*(.+)",
            text,
            re.IGNORECASE
        )

        if ju and lat and lon:
            poles.append(
                {
                    "ju": ju.group(1),
                    "lat": float(lat.group(1)),
                    "lon": float(lon.group(1)),
                    "address": (
                        address.group(1).strip()
                        if address
                        else ""
                    ),
                    "folder": info.parent,
                }
            )

    return poles


def nearest_pole(gps, poles):

    if not gps or not poles:
        return None, float("inf")

    lat, lon = gps

    nearest = None
    nearest_dist = float("inf")

    for pole in poles:

        d = distance_m(
            lat,
            lon,
            pole["lat"],
            pole["lon"],
        )

        if d < nearest_dist:
            nearest = pole
            nearest_dist = d

    return nearest, nearest_dist



def save_master_record(pole, photos, selected, note):

    new_file = not MASTER_LOG.exists()

    with MASTER_LOG.open(
        "a",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.writer(f)

        if new_file:
            writer.writerow([
                "JU",
                "Address",
                "Latitude",
                "Longitude",
                "Photo Count",
                "Billing Codes",
                "Notes",
                "Photo Files",
            ])

        billing = "; ".join(
            f"{code} x{qty}"
            for code, qty in selected
        )

        photo_files = "; ".join(
            photo.name
            for photo in photos
        )

        writer.writerow([
            pole["ju"],
            pole["address"],
            pole["lat"],
            pole["lon"],
            len(photos),
            billing,
            note,
            photo_files,
        ])


def route_order():
    route_file = JOB / "2_ROUTE" / f"{JOB_ID}_ROUTE.xlsx"
    if not route_file.exists():
        return []
    try:
        with zipfile.ZipFile(route_file) as z:
            root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows = []
        for row in root.findall(".//x:sheetData/x:row", ns)[1:]:
            vals = {}
            for cell in row.findall("x:c", ns):
                ref = cell.attrib.get("r", "")
                col = re.match(r"[A-Z]+", ref)
                if not col:
                    continue
                if cell.attrib.get("t") == "inlineStr":
                    node = cell.find(".//x:t", ns)
                else:
                    node = cell.find("x:v", ns)
                vals[col.group()] = node.text if node is not None else ""
            if vals.get("B") and vals.get("D") and vals.get("E"):
                rows.append({"ju": vals["B"], "lat": float(vals["D"]), "lon": float(vals["E"]), "address": vals.get("C", "")})
        return rows
    except Exception as exc:
        print(f"Route read failed: {exc}")
        return []


def ju_is_complete(ju):
    for info in WORK.rglob("transfer_info.txt"):
        try:
            text = info.read_text(errors="ignore")
        except Exception:
            continue
        m = re.search(r"JU Record:\s*(\d+)", text)
        if m and m.group(1) == str(ju):
            return (info.parent / "BILLING_AND_NOTES.txt").exists()
    return False


def next_unfinished_after(current_ju):
    route = route_order()
    if not route:
        return None
    start = next((i + 1 for i, item in enumerate(route) if item["ju"] == str(current_ju)), 0)
    for offset in range(len(route)):
        item = route[(start + offset) % len(route)]
        if not ju_is_complete(item["ju"]):
            return item
    return None


def navigate_next(current_ju):
    nxt = next_unfinished_after(current_ju)
    if not nxt:
        print("No unfinished JUs remain in the route.")
        return
    url = f"https://www.google.com/maps/dir/?api=1&destination={nxt['lat']},{nxt['lon']}&travelmode=driving"
    print(f"NEXT JU: {nxt['ju']} - {nxt['address']}")
    try:
        subprocess.Popen(["termux-open-url", url])
        print("Opening Google Maps navigation...")
    except Exception as exc:
        print(f"Could not open navigation: {exc}")


def billing_prompt(pole, photos, input_fn=input):

    print()
    print("=" * 40)
    print("FINISH POLE")
    print("=" * 40)

    print(f"JU: {pole['ju']}")

    if pole["address"]:
        print(pole["address"])

    print(f"Photos captured: {len(photos)}")
    print()

    for number, code in CODES.items():
        print(f"{number}) {code}")

    print()
    print("Enter as many billing codes as needed.")
    print("Press ENTER when finished.")
    print()

    print()
    print("JOB CLOSE CODE")
    print("1) FIBER TRANSFER COMPLETED (2+ photos)")
    print("2) TRANSFER ALREADY COMPLETED (1+ photo)")
    print("3) NO SERVICES ON POLE (1+ photo)")
    print("4) NO IDENTIFIABLE WINDSTREAM LINE ON POLE (1+ photo)")
    print("5) PENDING (trip made; remains incomplete)")
    print()

    close_choices = {
        "1": ("FIBER TRANSFER COMPLETED", 2),
        "2": ("TRANSFER ALREADY COMPLETED", 1),
        "3": ("NO SERVICES ON POLE", 1),
        "4": ("NO IDENTIFIABLE WINDSTREAM LINE ON POLE", 1),
        "5": ("PENDING", 1),
    }
    while True:
        status_choice = input_fn("Close code # [1]: ").strip() or "1"
        if status_choice not in close_choices:
            print("Enter 1 through 5."); continue
        status, required_photos = close_choices[status_choice]
        if len(photos) < required_photos:
            print(f"Cannot close as {status}: requires at least {required_photos} photo(s); currently {len(photos)}.")
            continue
        break

    print()
    print(f"STATUS: {status}")
    print()

    selected = []

    while True:

        choice = input_fn("Billing code #: ").strip()

        if choice == "":
            break

        if choice not in CODES:
            print("Invalid selection.")
            continue

        code = CODES[choice]

        qty = input_fn(
            f"{code} quantity [1]: "
        ).strip()

        if not qty:
            qty = "1"

        selected.append((code, qty))

        print(f"  ADDED: {code} x{qty}")

    print()

    note = input_fn(
        "Notation / notes (optional): "
    ).strip()

    master_matches = []

    for info in MASTER.rglob("transfer_info.txt"):
        try:
            text = info.read_text(errors="ignore")
        except Exception:
            continue

        ju_match = re.search(r"JU Record:\s*(\d+)", text)

        if ju_match and ju_match.group(1) == pole["ju"]:
            master_matches.append(info.parent)

    if len(master_matches) != 1:
        print()
        print("SAFETY STOP")
        print(
            f"JU {pole['ju']} has "
            f"{len(master_matches)} matches in MASTER COPY."
        )
        print("Nothing was written.")
        return

    master_folder = master_matches[0]

    # Copy every photo for this pole into MASTER COPY.
    photos_dir = master_folder / "photos"
    photos_dir.mkdir(exist_ok=True)

    for photo in photos:
        destination = photos_dir / photo.name

        if not destination.exists():
            import shutil
            shutil.copy2(photo, destination)

    # Billing/notes live with this JU in MASTER COPY.
    record = master_folder / "BILLING_AND_NOTES.txt"

    with record.open("a") as f:

        f.write("\n")
        f.write("=" * 50 + "\n")
        f.write(f"JU: {pole['ju']}\n")

        if pole["address"]:
            f.write(
                f"Address: {pole['address']}\n"
            )

        f.write("\nPHOTOS:\n")

        for photo in photos:
            f.write(f"- {photo.name}\n")

        f.write(f"\nSTATUS: {status}\n")
        f.write("\nBILLING:\n")

        if selected:
            for code, qty in selected:
                f.write(f"{code} x{qty}\n")
        else:
            f.write("No billing codes entered\n")

        f.write("\nNOTES:\n")
        f.write(
            (note if note else "None") + "\n"
        )

    save_master_record(pole, photos, selected, note)
    summary=sync_job(JOB)
    print(f"Live sheets updated: {summary['COMPLETE']} complete / {summary['TOTAL']} total; {summary['PENDING']} pending")
    navigate_next(pole["ju"])

    print()
    print("SAVED TO SELECTED JOB")
    print(f"JU {pole['ju']}")
    print(f"{len(photos)} photos")
    print(f"Production log: {MASTER_LOG}")
    print()


def main():

    poles = load_poles()

    print()
    print("======================================")
    print("   DEVCO POLE TRANSFER FIELD MODE")
    print("======================================")
    print()
    print(f"Loaded {len(poles)} JU locations.")

    if not poles:
        print()
        print("No JU locations were found.")
        print("Run your original photo sorter first.")
        return

    print()
    print("Waiting for Solocator photos...", flush=True)
    print("CTRL+C stops Field Mode.", flush=True)
    print()

    current_pole = None
    current_photos = []

    # Prevent duplicate Android write events.
    processed = {}

    process = subprocess.Popen(
        [
            "inotifywait",
            "-m",
            "-e",
            "close_write",
            "-e",
            "moved_to",
            "--format",
            "%f",
            str(PHOTOS),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )

    try:

        for line in process.stdout:

            filename = line.strip()

            if not filename:
                continue

            if filename.startswith(".pending"):
                continue

            if not filename.lower().endswith(
                (".jpg", ".jpeg", ".png")
            ):
                continue

            photo = PHOTOS / filename

            # Debounce duplicate CLOSE_WRITE events.
            now = time.time()

            if filename in processed:
                if now - processed[filename] < 10:
                    continue

            processed[filename] = now

            # Give Solocator time to finish writing EXIF.
            time.sleep(1)

            gps = photo_gps(photo)

            if not gps:
                print()
                print(f"NO GPS: {filename}")
                continue

            pole, dist = nearest_pole(gps, poles)

            if (
                pole is None
                or dist > MAX_MATCH_METERS
            ):
                print()
                print("PHOTO NEEDS REVIEW")
                print(filename)

                if pole:
                    print(
                        f"Nearest JU {pole['ju']} "
                        f"is {dist:.1f} m away."
                    )

                continue

            # First photo starts a pole session.
            if current_pole is None:

                current_pole = pole
                current_photos = [photo]

                print()
                print("------------------------------")
                print("POLE STARTED")
                print(f"JU {pole['ju']}")

                if pole["address"]:
                    print(pole["address"])

                print(f"GPS match: {dist:.1f} m")
                print("Photos: 1")
                print("------------------------------")

                continue

            # Same JU = silently add photo.
            if pole["ju"] == current_pole["ju"]:

                current_photos.append(photo)

                print(
                    f"JU {pole['ju']} "
                    f"+ photo "
                    f"({len(current_photos)} total)"
                )

                continue

            # New JU detected.
            print()
            print("================================")
            print("NEW POLE DETECTED")
            print(
                f"JU {current_pole['ju']} "
                f"has {len(current_photos)} photos."
            )
            print(
                f"Next photo matched JU {pole['ju']} "
                f"({dist:.1f} m)"
            )
            print("================================")

            billing_prompt(
                current_pole,
                current_photos
            )

            current_pole = pole
            current_photos = [photo]

            print()
            print("------------------------------")
            print("NEW POLE STARTED")
            print(f"JU {pole['ju']}")

            if pole["address"]:
                print(pole["address"])

            print("Photos: 1")
            print("------------------------------")

    except KeyboardInterrupt:

        print()
        print()

        if current_pole and current_photos:

            print(
                f"JU {current_pole['ju']} "
                f"still has "
                f"{len(current_photos)} photos."
            )

            answer = input(
                "Finish this pole now? [Y/n]: "
            ).strip().lower()

            if answer != "n":
                billing_prompt(
                    current_pole,
                    current_photos
                )

        print()
        print("Field Mode stopped.")

    finally:

        process.terminate()


if __name__ == "__main__":
    main()
