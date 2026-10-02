from pathlib import Path

ROOT = Path.home() / "des_moines_photo_work" / "Des_Moines_59_Transfer_Files"

jobs = {
"2516149": """Address: 4034 E University Ave
Notes:
1 bond and transfer; needs fiber tag.
Surveyed — no way to identify fiber.
Trip charge.

Billing codes:
PM2A x1
WC1F x1
""",

"2549851": """Address: Across from 2609 Maple St
Field reference: 2604 Maple St
Notes:
1 bond and transfer; needs fiber tag.
Surveyed twice — no way to identify fiber; once with Brett, once with Kinetic.
2 trip charges.

Billing codes:
PM2A x1
WC1F x2
""",

"2521532": """Address: 2014 Maple St
Notes:
Needs a double dead end.
Surveyed — no way to identify fiber.
Trip charge.

Billing codes:
WC1F x2
""",

"1964684": """Address: 2701 Delaware Ave
Notes:
No way to identify service or attachment.
There are 2 poles — which one?

Billing codes:
""",

"2283323": """Address: In front of 2425 Delaware Ave
Notes:
Trip charge. Not sure what service; no new pole.
Possible drop transfer?

Billing codes:
WC1F x1
""",

"2579221": """Address: 1200 E Euclid Ave
Notes:
WCF1/PM2A.
Need to come back.

Billing codes:
WC1F x1
PM2A x1

Additional field note:
1200 Euclid — one pole west; transfer already completed.
Trip charge.

Additional billing:
WC1F x1
""",

"2122834": """Address: 914 E Euclid Ave
Notes:
Already complete.

Billing codes:
""",

"2183603": """Address: 400 Euclid Ave
Notes:
Transfer already completed.
Trip charge.

Billing codes:
WC1F x1
""",

"2183724": """Address: 412 Euclid Ave
Notes:
Transfer already completed.
Trip charge.

Billing codes:
WC1F x1
""",

"1981253": """Address: 702 Euclid Ave
Notes:
Transfer is completed.
Trip charge.

Billing codes:
WC1F x1
""",

"2233288": """Address: 2831 Douglas Ave
Notes:
WCF1, PM2A.

Billing codes:
WC1F x1
PM2A x1
""",

"2434151": """Address: 3800 Lindlavista Way
Notes:
There is a new pole and we can frame on it, but it cannot be brought underground yet.
Trip charge.

Billing codes:
WC1F x1
"""
}

written = []
missing = []

for ju, text in jobs.items():
    matches = [p for p in ROOT.iterdir() if p.is_dir() and p.name.startswith(ju + " ")]
    if not matches:
        missing.append(ju)
        continue

    folder = matches[0]
    outfile = folder / "notes and billing codes.txt"
    outfile.write_text(text.strip() + "\n", encoding="utf-8")
    written.append((ju, folder.name))

print()
print("DONE")
print("Created notes and billing codes.txt in", len(written), "folders.")
for ju, name in written:
    print(" OK:", ju, "-", name)

if missing:
    print("\nFOLDERS NOT FOUND:")
    for ju in missing:
        print(" ", ju)

print("\nIntentionally NOT auto-matched yet:")
print(" - 816 Euclid")
print(" - 210 Euclid")
print(" - 515 Euclid")
print(" - 801 E 23rd St")
print(" - 2121 Delaware")
print(" - 3120 Delaware")
print(" - 3618 6th/6*")
