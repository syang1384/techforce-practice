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

    hh = int(rec["hh"])
    income = Decimal(rec["income"]) / 100
    age = int(rec["age"])

    threshold = Decimal(1580 + 560 * (hh - 1))
    if rec["state"] == "AK":
        threshold = trunc(threshold * Decimal("1.25"))
    if rec["state"] == "HI":
        threshold = trunc(threshold * Decimal("1.15"))
    limit130 = trunc(threshold * Decimal("1.30"))
    limit200 = trunc(threshold * Decimal("2.00"))

    reason = ""
    if income > limit130:
        if rec["disabled"] and income <= limit200:
            reason = "D20"
        else:
            return "DENIED", Decimal(0), "I01"

    if hh > 8:
        max_allot = Decimal(290 + 240 * 7 + 200 * (hh - 8))
    else:
        max_allot = Decimal(290 + 240 * (hh - 1))
    net = max(income - 198, Decimal(0))
    benefit = max_allot - trunc(net * Decimal("0.30"))
    if rec["veteran"]:
        benefit += 50
    if age >= 60:
        benefit += 25

    if benefit <= 0:
        if hh <= 2:
            benefit, reason = Decimal(23), "M23"
        else:
            return "DENIED", Decimal(0), "Z00"
    if 0 < benefit < 23 and hh <= 2:
        benefit, reason = Decimal(23), "M23"
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
        with open(argv[1], encoding="latin-1", newline="") as f:
            lines = [ln.rstrip("\r\n") for ln in f]
    except FileNotFoundError:
        print(f"bencalc: file does not exist: {argv[1]}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write("".join(line + "\n" for line in run(lines)).encode("latin-1"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
