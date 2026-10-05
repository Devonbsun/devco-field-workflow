"""Invoice from current saved JU records using established production rates."""
from decimal import Decimal
from job_records import _parse_record, CLOSE_RULES

RATES = {'BM80': 34.84, 'BM80PF': 32.17, 'BM82': 34.78, 'BM83(A)': 28.6, 'BM83(B)': 28.6, 'PE1-3': 41.96, 'PE1-3G': 46.76, 'PE1-3G(O)': 46.76, 'PF1-6A(O)': 59.5, 'PM11': 22.92, 'PM2': 38.24, 'PM2(O)': 38.24, 'PM2A': 31.93, 'PM2AF': 29.5, 'PM2C': 27.51, 'PM52': 24.31, 'PM52(A)': 24.31, 'PM54(A)': 27.08, 'PM92': 30.47, 'R1-5(A)': 3.91, 'R1-5(AF)': 3.91, 'WC1': 39.18, 'WC1F': 39.18, 'WEC1': 0.4, 'WEC1F': 0.4, 'WPE1': 44.49, 'WPE1(O)': 44.49, 'WSEA(A)': 37.42, 'XXCOE': 0.26, 'XXCW': 0.28, 'XXPF': 52.56, 'XXPM11': 21.54, 'XXPM5': 29.36, 'XXSEA(A)': 37.42, 'XXSTRAND': 0.26, 'TRIP CHARGE': 40.0}
TRIP_STATUSES = {"TRANSFER ALREADY COMPLETED", "NO SERVICES ON POLE", "NO IDENTIFIABLE WINDSTREAM LINE ON POLE", "ADSS"}

def invoice_summary(job_dir):
    work = Decimal("0")
    trip = Decimal("0")
    unknown = {}
    billed = 0
    trip_qty = 0
    with __import__('record_editor').RECORD_LOCK:
        for info in (job_dir / "3_JU_FILES").glob("*/transfer_info.txt"):
            folder = info.parent
            rec = _parse_record(folder / "BILLING_AND_NOTES.txt")
            need, state = CLOSE_RULES.get(rec['status'], (None, "NOT COMPLETED"))
            photos = sum(p.is_file() for p in (folder / 'photos').glob('*'))
            if state != "COMPLETE" or photos < need:
                continue
            codes = list(rec['billing'])
            # Old survey records may have a close status but no billing line.
            # Count one $40 trip without duplicating an already recorded charge.
            if rec['status'] in TRIP_STATUSES and not any(c.strip() == 'TRIP CHARGE' for c,q in codes):
                codes.append(('TRIP CHARGE', '1'))
            if not codes:
                unknown['MISSING BILLING CODE'] = unknown.get('MISSING BILLING CODE', 0) + 1
                continue
            billed += 1
            for code, qty in codes:
                code = code.strip()
                qty = int(qty)
                rate = RATES.get(code)
                if rate is None:
                    unknown[code] = unknown.get(code, 0) + qty
                    continue
                amount = Decimal(str(rate)) * qty
                if code == 'TRIP CHARGE':
                    trip += amount
                    trip_qty += qty
                else:
                    work += amount
    return {'job': job_dir.name, 'total': str(work + trip), 'work': str(work), 'trip': str(trip), 'trip_quantity': trip_qty, 'billed_jus': billed, 'unpriced': unknown}
