#!/usr/bin/env python3
"""Python port of legacy/BENCALC.cbl. Behavior is specified in SPEC.md."""
import sys
from decimal import ROUND_DOWN, Decimal

RECORD_LEN = 40
CENT = Decimal("0.01")
DIGITS = set("0123456789")


def trunc(value):
    return value.quantize(CENT, rounding=ROUND_DOWN)


def is_numeric(field):
    return bool(field) and set(field) <= DIGITS


def read_records(data):
    """Split file bytes into records the way GnuCOBOL LINE SEQUENTIAL does (SPEC.md 1).

    Only LF ends a record. Every CR is dropped wherever it appears, and a final
    line without LF counts only if it has at least one other byte.
    """
    lines = data.replace(b"\r", b"").split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    return [ln.decode("latin-1") for ln in lines]


def parse(line):
    rec = line.ljust(RECORD_LEN)[:RECORD_LEN]
    return {
        "id": rec[0:8],
        "state": rec[23:25],
        "hh": rec[25:27],
        "income": rec[27:35],
        "age": rec[35:38],
        "disabled": rec[38] == "Y",
        "veteran": rec[39] == "Y",
    }


def evaluate(rec):
    """Return (status, benefit, reason) for one parsed record."""
    if not (is_numeric(rec["hh"]) and is_numeric(rec["income"]) and is_numeric(rec["age"])) \
            or int(rec["hh"]) == 0:
        return "REJECT", Decimal(0), "R01"

    return calculate(int(rec["hh"]), Decimal(rec["income"]) / 100, int(rec["age"]),
                     rec["state"], rec["disabled"], rec["veteran"])


def calculate(hh, income, age, state, disabled, veteran, trace=None):
    """Eligibility and benefit for already-validated values (SPEC.md 3.2-3.4).

    hh >= 1, income is a Decimal in dollars with at most 2 decimals, state and the
    flags are compared case-sensitively like the COBOL. Returns (status, benefit, reason).
    If trace is a list, each rule that fires appends a (description, amount) pair to it.
    """
    note = (lambda text, amount: trace.append((text, amount))) if trace is not None else (lambda *_: None)

    threshold = Decimal(1580 + 560 * (hh - 1))
    note(f"Income threshold for a household of {hh}", threshold)
    if state == "AK":
        threshold = trunc(threshold * Decimal("1.25"))
        note("Alaska cost-of-living adjustment (x 1.25)", threshold)
    if state == "HI":
        threshold = trunc(threshold * Decimal("1.15"))
        note("Hawaii cost-of-living adjustment (x 1.15)", threshold)
    limit130 = trunc(threshold * Decimal("1.30"))
    limit200 = trunc(threshold * Decimal("2.00"))
    note("Income limit (130% of threshold)", limit130)
    note("Gross monthly income", income)

    reason = ""
    if income > limit130:
        if disabled and income <= limit200:
            reason = "D20"
            note("Over 130%, but within the disability limit (200% of threshold)", limit200)
        else:
            if disabled:
                note("Over the disability limit (200% of threshold)", limit200)
            note("Income is over the limit: denied", Decimal(0))
            return "DENIED", Decimal(0), "I01"

    if hh > 8:
        max_allot = Decimal(290 + 240 * 7 + 200 * (hh - 8))
    else:
        max_allot = Decimal(290 + 240 * (hh - 1))
    net = max(income - 198, Decimal(0))
    contrib = trunc(net * Decimal("0.30"))
    benefit = max_allot - contrib
    note(f"Maximum allotment for a household of {hh}", max_allot)
    note("Net income (gross income minus the 198.00 deduction)", net)
    note("Household contribution (30% of net income, cut to the cent)", -contrib)
    if veteran:
        benefit += 50
        note("Veteran supplement", Decimal(50))
    if age >= 60:
        benefit += 25
        note("Age 60 or over supplement", Decimal(25))
    note("Calculated benefit", benefit)

    if benefit <= 0:
        if hh <= 2:
            benefit, reason = Decimal(23), "M23"
            note("Raised to the minimum benefit (households of 1 or 2)", benefit)
        else:
            note("Zero or less, and households of 3 or more have no minimum: denied", Decimal(0))
            return "DENIED", Decimal(0), "Z00"
    if 0 < benefit < 23 and hh <= 2:
        benefit, reason = Decimal(23), "M23"
        note("Raised to the minimum benefit (households of 1 or 2)", benefit)
    return "ELIGIBLE", benefit, reason


def edited(value, int_digits):
    """COBOL Z...9.99 picture: drops high-order digits that don't fit."""
    value = abs(value) % (10 ** int_digits)
    return f"{value:{int_digits + 3}.2f}"


def run(lines):
    out = []
    counts = {"READ": 0, "ELIGIBLE": 0, "DENIED": 0, "REJECT": 0}
    total = Decimal(0)
    for line in lines:
        rec = parse(line)
        status, benefit, reason = evaluate(rec)
        counts["READ"] = (counts["READ"] + 1) % 100000
        counts[status] = (counts[status] + 1) % 100000
        if status == "ELIGIBLE":
            total = (total + benefit) % 100000000
        detail = f"{rec['id']} {status:<8} {edited(benefit, 4)} {reason:<4}"
        out.append(detail.rstrip())
    for label, value in [
        ("RECORDS READ", counts["READ"]),
        ("ELIGIBLE", counts["ELIGIBLE"]),
        ("DENIED", counts["DENIED"]),
        ("REJECTED", counts["REJECT"]),
        ("TOTAL BENEFITS", total),
    ]:
        out.append(f"{label:<20}{edited(Decimal(value), 8)}".rstrip())
    return out


def main(argv):
    if len(argv) != 2:
        print("usage: bencalc.py <input>", file=sys.stderr)
        return 2
    try:
        with open(argv[1], "rb") as f:
            lines = read_records(f.read())
    except FileNotFoundError:
        print(f"bencalc: file does not exist: {argv[1]}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write("".join(line + "\n" for line in run(lines)).encode("latin-1"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
