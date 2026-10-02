from pathlib import Path
import shutil, re, zipfile

MASTER = Path.home() / "des_moines_photo_work" / "Des_Moines_59_Transfer_Files"
BOSS   = Path.home() / "des_moines_photo_work" / "Des_Moines_59_BOSS_COPY"
OUTPUT = Path("/storage/emulated/0/Download/Des_Moines_59_Transfer_Files_BOSS_COPY.zip")

# Fresh boss copy
if BOSS.exists():
    shutil.rmtree(BOSS)
BOSS.mkdir(parents=True)

kept = 0

for src in sorted(MASTER.iterdir()):
    if not src.is_dir():
        continue

    notes_file = src / "notes and billing codes.txt"
    photos_dir = src / "photos"

    photos = []
    if photos_dir.exists():
        photos = [
            p for p in photos_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        ]

    # Boss only gets poles that have notes/billing or matched photos
    if not notes_file.exists() and not photos:
        continue

    dst = BOSS / src.name
    dst.mkdir()

    # Preserve original transfer information
    info_src = src / "transfer_info.txt"
    info_text = ""

    if info_src.exists():
        info_text = info_src.read_text(errors="ignore")
        shutil.copy2(info_src, dst / "transfer_info.txt")

    # Extract JU/address from source information/folder
    ju_match = re.search(r"(?im)^JU(?: Record)?:\s*(.+)$", info_text)
    ad_match = re.search(r"(?im)^Address:\s*(.+)$", info_text)

    ju = ju_match.group(1).strip() if ju_match else src.name.split()[0]
    address = ad_match.group(1).strip() if ad_match else "GPS-based pole location"

    # Read our working notes
    original = ""
    if notes_file.exists():
        original = notes_file.read_text(errors="ignore").strip()

        # Prefer field address when we explicitly recorded one
        field = re.search(r"(?im)^Field address:\s*(.+)$", original)
        if field:
            address = field.group(1).strip()

    # Separate Notes and Billing sections
    notes_text = ""
    billing_text = ""

    if original:
        nm = re.search(
            r"(?is)Notes:\s*(.*?)(?=\n\s*Billing codes:|\n\s*Billing:|\Z)",
            original
        )
        bm = re.search(
            r"(?is)(?:Billing codes:|Billing:)\s*(.*?)(?=\n\s*(?:Additional field note:|Additional billing:|Reconciliation:|Reference:)|\Z)",
            original
        )

        if nm:
            notes_text = nm.group(1).strip()
        if bm:
            billing_text = bm.group(1).strip()

        # Preserve additional field notes
        am = re.search(
            r"(?is)Additional field note:\s*(.*?)(?=\n\s*Additional billing:|\n\s*Reconciliation:|\Z)",
            original
        )
        if am:
            extra = am.group(1).strip()
            notes_text = (notes_text + "\n" + extra).strip()

        # Preserve additional billing
        ab = re.search(
            r"(?is)Additional billing:\s*(.*?)(?=\n\s*Reconciliation:|\Z)",
            original
        )
        if ab:
            billing_text = (billing_text + "\n" + ab.group(1).strip()).strip()

    # Parse billing lines
    billing = []
    for line in billing_text.splitlines():
        line = line.strip()
        if line:
            billing.append(line)

    # Count explicit trip charges from notes.
    # "2 trip charges" => 2; otherwise each singular Trip charge => 1.
    trip_qty = 0

    for m in re.finditer(r"(?i)\b(\d+)\s+trip charges?\b", notes_text):
        trip_qty += int(m.group(1))

    # Remove plural matches before counting standalone singular mentions
    temp_notes = re.sub(r"(?i)\b\d+\s+trip charges?\b", "", notes_text)
    trip_qty += len(re.findall(r"(?i)\btrip charge\b", temp_notes))

    # Convert only enough WC1F quantity to account for documented trip charges.
    new_billing = []
    remaining_trip = trip_qty

    for line in billing:
        m = re.fullmatch(r"(?i)WC1F\s+x(\d+)", line)

        if m and remaining_trip > 0:
            qty = int(m.group(1))
            converted = min(qty, remaining_trip)
            fiber_remaining = qty - converted

            if fiber_remaining:
                new_billing.append(f"WC1F x{fiber_remaining}")

            new_billing.append(f"Trip Charge x{converted}")
            remaining_trip -= converted
        else:
            new_billing.append(line)

    # If notes say Trip Charge but billing somehow lacked WC1F,
    # show it for boss review rather than silently losing it.
    if remaining_trip > 0:
        new_billing.append(f"Trip Charge x{remaining_trip}")

    # Consolidate duplicate identical billing labels
    totals = {}
    order = []

    for line in new_billing:
        m = re.fullmatch(r"(.+?)\s+x(\d+)", line)
        if m:
            code = m.group(1).strip()
            qty = int(m.group(2))
            if code not in totals:
                totals[code] = 0
                order.append(code)
            totals[code] += qty
        else:
            if line not in order:
                order.append(line)
                totals[line] = None

    clean_billing = []
    for code in order:
        qty = totals[code]
        clean_billing.append(code if qty is None else f"{code} x{qty}")

    if not clean_billing:
        clean_billing = ["No billing code entered"]

    if not notes_text:
        notes_text = "No additional field notes."

    boss_text = f"""DES MOINES POLE TRANSFER

JU NUMBER: {ju}
ADDRESS: {address}

BILLING
--------------------------------
{chr(10).join(clean_billing)}

WORK / FIELD NOTES
--------------------------------
{notes_text}

"""

    (dst / "BILLING_AND_NOTES.txt").write_text(boss_text, encoding="utf-8")

    # Copy matched photos
    if photos:
        out_photos = dst / "photos"
        out_photos.mkdir()
        for photo in photos:
            shutil.copy2(photo, out_photos / photo.name)

    kept += 1

# Build ZIP
if OUTPUT.exists():
    OUTPUT.unlink()

with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as z:
    for p in BOSS.rglob("*"):
        if p.is_file():
            z.write(p, p.relative_to(BOSS.parent))

print("\n======================================")
print("BOSS COPY CREATED")
print("Included pole folders:", kept)
print("Master files: UNCHANGED")
print("ZIP:", OUTPUT)
print("======================================")
