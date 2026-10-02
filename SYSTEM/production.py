from pathlib import Path
import re

MASTER = Path.home() / "des_moines_photo_work/Des_Moines_59_MASTER_COPY"

RATES = {
    "BM80": 34.84,
    "BM80PF": 32.17,
    "BM82": 34.78,
    "BM83(A)": 28.60,
    "BM83(B)": 28.60,
    "PE1-3": 41.96,
    "PE1-3G": 46.76,
    "PE1-3G(O)": 46.76,
    "PF1-6A(O)": 59.50,
    "PM11": 22.92,
    "PM2": 38.24,
    "PM2(O)": 38.24,
    "PM2A": 31.93,
    "PM2AF": 29.50,
    "PM2C": 27.51,
    "PM52": 24.31,
    "PM52(A)": 24.31,
    "PM54(A)": 27.08,
    "PM92": 30.47,
    "R1-5(A)": 3.91,
    "R1-5(AF)": 3.91,
    "WC1": 39.18,
    "WC1F": 39.18,
    "WEC1": 0.40,
    "WEC1F": 0.40,
    "WPE1": 44.49,
    "WPE1(O)": 44.49,
    "WSEA(A)": 37.42,
    "XXCOE": 0.26,
    "XXCW": 0.28,
    "XXPF": 52.56,
    "XXPM11": 21.54,
    "XXPM5": 29.36,
    "XXSEA(A)": 37.42,
    "XXSTRAND": 0.26,
    "TRIP CHARGE": 40.00,
}

totals = {}
unknown = {}

for f in MASTER.glob("*/BILLING_AND_NOTES.txt"):
    text = f.read_text(errors="ignore")

    for line in text.splitlines():
        m = re.fullmatch(
            r"\s*(.+?)\s+x\s*(\d+)\s*",
            line,
            re.I
        )

        if not m:
            continue

        code = m.group(1).strip().upper()
        qty = int(m.group(2))

        if code in RATES:
            totals[code] = totals.get(code, 0) + qty
        else:
            unknown[code] = unknown.get(code, 0) + qty

grand = 0
trip_value = 0
work_value = 0

print()
print("==============================================")
print("          DEVCO PRODUCTION REPORT")
print("==============================================")

for code in sorted(totals):
    qty = totals[code]
    rate = RATES[code]
    value = qty * rate
    grand += value

    if code == "TRIP CHARGE":
        trip_value += value
    else:
        work_value += value

    print(
        f"{code:<14} {qty:>4} x "
        f"${rate:>6.2f} = ${value:>9,.2f}"
    )

print("----------------------------------------------")
print(f"WORK CODES                     ${work_value:>10,.2f}")
print(f"TRIP CHARGES                   ${trip_value:>10,.2f}")
print("----------------------------------------------")
print(f"TOTAL PRODUCTION               ${grand:>10,.2f}")
print("==============================================")

if unknown:
    print()
    print("WARNING - UNPRICED CODES:")
    for code, qty in sorted(unknown.items()):
        print(f"  {code} x{qty}")
    print("These are NOT included in TOTAL PRODUCTION.")

print()
