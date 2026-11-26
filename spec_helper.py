#!/usr/bin/env python3
"""Study aid for SPEC.md: browse sections, map them to BENCALC.cbl lines, and trace
how a record moves through every rule.

  python3 spec_helper.py toc                     list SPEC.md sections
  python3 spec_helper.py show 3.4                print a section (and its subsections)
  python3 spec_helper.py cobol 3.4               print the COBOL that implements it
  python3 spec_helper.py search truncat          find a term in SPEC.md and BENCALC.cbl
  python3 spec_helper.py ambiguities             every item SPEC.md flags with a warning
  python3 spec_helper.py explain A0000011        trace one record step by step
  python3 spec_helper.py explain --hh 2 --income 1795.33 --age 60
  python3 spec_helper.py walk                    one line per record + rule coverage

The trace is written separately from bencalc.py, straight from SPEC.md, so it doubles
as a second reading of the spec (test_spec_helper.py checks that both agree).
"""
import argparse
import re
import sys
from collections import Counter
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "SPEC.md"
COBOL = ROOT / "legacy" / "BENCALC.cbl"
DEFAULT_DATA = ROOT / "legacy" / "data" / "applicants.dat"
CENT = Decimal("0.01")
WARN = "\u26a0"

FIELDS = [  # (start, end) 1-based inclusive, name, PIC
    (1, 8, "AP-ID", "X(8)"),
    (9, 23, "AP-LAST-NAME", "X(15)"),
    (24, 25, "AP-STATE", "X(2)"),
    (26, 27, "AP-HH-SIZE", "9(2)"),
    (28, 35, "AP-INCOME", "9(6)V99"),
    (36, 38, "AP-AGE", "9(3)"),
    (39, 39, "AP-DISABLED", "X"),
    (40, 40, "AP-VETERAN", "X"),
]

# SPEC section -> COBOL line ranges, as (first line prefix, prefix of the line after the range).
COBOL_MAP = {
    "1": [("FILE-CONTROL.", "DATA DIVISION.")],
    "2": [("01  APPLICANT-REC.", "FD  REPORT-FILE.")],
    "3": [("PROCESS-APPLICANT.", "WRITE-DETAIL.")],
    "3.1": [("PROCESS-APPLICANT.", "COMPUTE-THRESHOLD.")],
    "3.2": [("COMPUTE-THRESHOLD.", "DETERMINE-ELIGIBILITY.")],
    "3.3": [("DETERMINE-ELIGIBILITY.", "COMPUTE-BENEFIT.")],
    "3.4": [("COMPUTE-BENEFIT.", "WRITE-DETAIL.")],
    "4": "TO WS-REASON",
    "5": [("01  WS-OUT.", "PROCEDURE DIVISION."), ("WRITE-DETAIL.", None)],
    "5.1": [("01  WS-OUT.", "01  WS-SUM-LINE."), ("WRITE-DETAIL.", "WRITE-SUMMARY.")],
    "5.2": [("01  WS-SUM-LINE.", "PROCEDURE DIVISION."), ("WRITE-SUMMARY.", None)],
    "6": [("01  WS-STATUS", "01  WS-OUT.")],
}


# ---------- documents ----------

def spec_sections():
    """[(number, level, title, start_idx, end_idx)] over SPEC.md lines."""
    lines = SPEC.read_text(encoding="utf-8").splitlines()
    heads = []
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{2,3}) (\d+(?:\.\d+)*)\.? (.*)$", ln)
        if m:
            heads.append((m.group(2), len(m.group(1)), m.group(3), i))
    out = []
    for k, (num, level, title, start) in enumerate(heads):
        end = len(lines)
        for num2, level2, _, start2 in heads[k + 1:]:
            if level2 <= level:
                end = start2
                break
        out.append((num, level, title, start, end))
    return lines, out


def section_of(line_idx, sections):
    best = None
    for num, _, title, start, end in sections:
        if start <= line_idx < end:
            best = (num, title)
    return best


def cobol_lines():
    return COBOL.read_text(encoding="latin-1").splitlines()


def cobol_line(prefix, lines=None):
    """1-based number of the first COBOL line whose code starts with prefix."""
    lines = lines or cobol_lines()
    for i, ln in enumerate(lines, 1):
        if ln[7:].strip().startswith(prefix):
            return i
    raise KeyError(f"BENCALC.cbl has no line starting with {prefix!r}")


def cobol_ranges(section, lines=None):
    """[(first, last)] 1-based inclusive line ranges for a SPEC section."""
    lines = lines or cobol_lines()
    spec = COBOL_MAP.get(section)
    if spec is None:
        return []
    if isinstance(spec, str):
        return [(i, i) for i, ln in enumerate(lines, 1) if spec in ln]
    out = []
    for start, stop in spec:
        a = cobol_line(start, lines)
        b = cobol_line(stop, lines) - 1 if stop else len(lines)
        while b > a and not lines[b - 1].strip():
            b -= 1
        out.append((a, b))
    return out


# ---------- trace ----------

def money(d):
    return f"{d:.2f}"


def trunc(d):
    return d.quantize(CENT, rounding=ROUND_DOWN)


def numeric(s):
    return s != "" and all(c in "0123456789" for c in s)


def zzz9(value, int_digits):
    value = abs(value) % (10 ** int_digits)
    return f"{value:{int_digits + 3}.2f}"


class Trace:
    def __init__(self, raw):
        self.raw = raw
        self.steps = []   # (spec section, cobol line or None, text)
        self.notes = []   # things worth knowing about this record
        self.tags = set()  # rule/trap coverage keys
        self.status = self.reason = None
        self.benefit = Decimal(0)

    def step(self, section, anchor, text):
        self.steps.append((section, cobol_line(anchor) if anchor else None, text))

    def note(self, tag, text):
        self.tags.add(tag)
        self.notes.append(text)

    @property
    def report_line(self):
        return f"{self.rec[0:8]} {self.status:<8} {zzz9(self.benefit, 4)} {self.reason:<4}".rstrip()


def trace(raw):
    t = Trace(raw)
    rec = raw.ljust(40)[:40]
    t.rec = rec
    f = {name: rec[a - 1:b] for a, b, name, _ in FIELDS}
    t.fields = f
    if len(raw) < 40:
        t.note("short-line", f"Line is {len(raw)} bytes; padded with spaces to 40 (SPEC §2).")
    if len(raw) > 40:
        t.note("long-line", f"Line is {len(raw)} bytes; bytes after 40 are ignored (SPEC §2).")

    # 3.1 validation
    bad = [n for n in ("AP-HH-SIZE", "AP-INCOME", "AP-AGE") if not numeric(f[n])]
    if bad or f["AP-HH-SIZE"] == "00":
        why = ", ".join(f"{n}={f[n]!r} is not all digits" for n in bad) or "AP-HH-SIZE = 0"
        t.step("3.1", "IF AP-HH-SIZE IS NOT NUMERIC", f"Validation fails: {why} -> REJECT / R01")
        t.status, t.reason = "REJECT", "R01"
        t.tags.add("R01")
        t.note("R01", "Rejected records print benefit 0.00 and still count in RECORDS READ.")
        return t
    t.step("3.1", "IF AP-HH-SIZE IS NOT NUMERIC", "Validation passes: hh, income, age are all digits and hh > 0")

    hh, age = int(f["AP-HH-SIZE"]), int(f["AP-AGE"])
    income = Decimal(f["AP-INCOME"]) / 100
    state, dis, vet = f["AP-STATE"], f["AP-DISABLED"], f["AP-VETERAN"]
    disabled, veteran = dis == "Y", vet == "Y"
    for name, val in (("AP-DISABLED", dis), ("AP-VETERAN", vet)):
        if val.upper() == "Y" and val != "Y":
            t.note("lowercase-flag", f"{name} = {val!r}: only uppercase 'Y' counts, so this is treated as no (SPEC §2).")
    if state.upper() in ("AK", "HI") and state not in ("AK", "HI"):
        t.note("lowercase-state", f"AP-STATE = {state!r}: lowercase gets no cost-of-living multiplier (SPEC §2, §6.3).")
    if age > 120:
        t.note("odd-age", f"Age {age} is accepted; age is never range-checked (SPEC §6.4).")

    # 3.2 thresholds
    threshold = Decimal(1580 + 560 * (hh - 1))
    t.step("3.2", "COMPUTE WS-THRESHOLD = 1580", f"threshold = 1580 + 560 x ({hh} - 1) = {money(threshold)}")
    if state == "AK":
        threshold = trunc(threshold * Decimal("1.25"))
        t.step("3.2", 'IF AP-STATE = "AK"', f"AK: threshold x 1.25 = {money(threshold)}")
        t.tags.add("AK")
    elif state == "HI":
        threshold = trunc(threshold * Decimal("1.15"))
        t.step("3.2", 'IF AP-STATE = "HI"', f"HI: threshold x 1.15 = {money(threshold)}")
        t.tags.add("HI")
    else:
        t.step("3.2", 'IF AP-STATE = "AK"', f"State {state!r} is not AK/HI: no multiplier")
    if state in ("AK", "HI"):
        t.note("ak-hi", "The AK/HI multiplier is applied before the 130%/200% limits (SPEC §3.2).")
    limit130 = trunc(threshold * Decimal("1.30"))
    limit200 = trunc(threshold * Decimal("2.00"))
    t.step("3.2", "COMPUTE WS-LIMIT-130", f"limit130 = {money(threshold)} x 1.30 = {money(limit130)}")
    t.step("3.2", "COMPUTE WS-LIMIT-200", f"limit200 = {money(threshold)} x 2.00 = {money(limit200)}")

    # 3.3 eligibility
    reason = ""
    if income <= limit130:
        t.step("3.3", "IF AP-INCOME > WS-LIMIT-130", f"income {money(income)} <= limit130 {money(limit130)}: income-eligible")
        if income == limit130:
            t.note("at-limit", "Income is exactly limit130; the comparison is inclusive, so it passes (SPEC §3.3).")
        if disabled:
            t.note("disabled-under-130", "Disabled, but under 130%, so no D20 code (SPEC §3.3).")
    elif disabled and income <= limit200:
        reason = "D20"
        t.step("3.3", 'IF AP-DISABLED = "Y"',
               f"income {money(income)} > limit130 {money(limit130)}, disabled and <= limit200 {money(limit200)}: reason D20")
        t.tags.add("D20")
        if income == limit200:
            t.note("at-limit", "Income is exactly limit200; the comparison is inclusive, so it passes (SPEC §3.3).")
    else:
        why = (f"disabled but income > limit200 {money(limit200)}" if disabled
               else f"income {money(income)} > limit130 {money(limit130)} and not disabled")
        t.step("3.3", 'MOVE "I01"', f"{why} -> DENIED / I01")
        t.status, t.reason = "DENIED", "I01"
        t.tags.add("I01")
        if dis == "y":
            t.note("lowercase-flag-mattered", "A lowercase 'y' disabled flag is ignored; with 'Y' this might have been D20.")
        return t

    # 3.4 benefit
    if hh > 8:
        max_allot = Decimal(290 + 240 * 7 + 200 * (hh - 8))
        t.step("3.4", "IF AP-HH-SIZE > 8", f"hh {hh} > 8: max_allot = 1970 + 200 x ({hh} - 8) = {money(max_allot)}")
        t.note("hh-over-8", "Each person past 8 adds 200, not 240 (SPEC §3.4).")
    else:
        max_allot = Decimal(290 + 240 * (hh - 1))
        t.step("3.4", "COMPUTE WS-MAX-ALLOT = 290 + 240 * (AP", f"max_allot = 290 + 240 x ({hh} - 1) = {money(max_allot)}")
    net = income - 198
    if net < 0:
        t.step("3.4", "COMPUTE WS-NET-INCOME", f"net = {money(income)} - 198 = {money(net)} < 0, so net = 0.00")
        net = Decimal(0)
        t.tags.add("net-floor")
    else:
        t.step("3.4", "COMPUTE WS-NET-INCOME", f"net = {money(income)} - 198 = {money(net)}")
    exact = net * Decimal("0.30")
    contrib = trunc(exact)
    t.step("3.4", "COMPUTE WS-CONTRIB", f"contrib = TRUNC({money(net)} x 0.30 = {exact.normalize():f}) = {money(contrib)}")
    rounded = exact.quantize(CENT, rounding=ROUND_HALF_UP)
    if rounded != contrib:
        t.note("truncation", f"Truncation matters here: rounding would give contrib {money(rounded)}, "
                             f"not {money(contrib)} (SPEC §3.4, audit finding 2008-17).")
    benefit = max_allot - contrib
    t.step("3.4", "COMPUTE WS-BENEFIT", f"benefit = {money(max_allot)} - {money(contrib)} = {money(benefit)}")
    before_addons = benefit
    if veteran:
        benefit += 50
        t.step("3.4", 'IF AP-VETERAN = "Y"', f"veteran: +50 = {money(benefit)}")
        t.tags.add("veteran")
    if age >= 60:
        benefit += 25
        t.step("3.4", "IF AP-AGE NOT < 60", f"age {age} >= 60: +25 = {money(benefit)}")
        t.tags.add("elderly")
        if age == 60:
            t.note("age-60", "Age exactly 60 gets the +25 (the test is NOT < 60).")
    if (veteran or age >= 60) and before_addons <= 0 < benefit:
        t.note("addon-rescue", f"Without add-ons the benefit would be {money(before_addons)}; "
                               "the add-ons are applied before the minimum check (SPEC §3.4).")
    if before_addons > 0 and hh <= 2 and before_addons < 23 <= benefit and (veteran or age >= 60):
        t.note("addon-rescue", f"Without add-ons the benefit would be {money(before_addons)} and hit the $23 minimum.")

    if benefit <= 0:
        if hh <= 2:
            t.step("3.4", "IF WS-BENEFIT NOT > 0", f"benefit {money(benefit)} <= 0 and hh {hh} <= 2: raised to 23.00, reason M23")
            benefit, reason = Decimal(23), _m23(t, reason)
        else:
            t.step("3.4", "IF WS-BENEFIT NOT > 0", f"benefit {money(benefit)} <= 0 and hh {hh} >= 3: DENIED / Z00")
            t.status, t.reason = "DENIED", "Z00"
            t.tags.add("Z00")
            t.note("Z00", "Households of 3+ have no $23 minimum (SPEC §3.4).")
            return t
    elif benefit < 23 and hh <= 2:
        t.step("3.4", "IF WS-BENEFIT > 0 AND AP-HH-SIZE NOT > 2",
               f"0 < benefit {money(benefit)} < 23 and hh {hh} <= 2: raised to 23.00, reason M23")
        benefit, reason = Decimal(23), _m23(t, reason)
    elif benefit < 23:
        t.note("small-benefit", f"hh {hh} >= 3 is paid {money(benefit)} as calculated; no minimum applies.")
    t.step("3.4", 'MOVE "ELIGIBLE" TO WS-STATUS', f"benefit {money(benefit)} > 0: ELIGIBLE, added to TOTAL BENEFITS")
    t.status, t.reason, t.benefit = "ELIGIBLE", reason, benefit
    t.tags.add("ELIGIBLE")
    if benefit > Decimal("9999.99"):
        t.note("overflow", f"Benefit {money(benefit)} does not fit ZZZ9.99: the report shows "
                           f"{zzz9(benefit, 4).strip()}, but the total adds the full amount (SPEC §5.1).")
    return t


def _m23(t, reason):
    t.tags.add("M23")
    if reason == "D20":
        t.note("m23-over-d20", "M23 overwrites D20: the disability-exception code is lost (SPEC §3.4).")
    return "M23"


def print_trace(t, where=""):
    print(f"Record {t.rec[0:8].strip() or '(blank id)'}{where}")
    print(f"  |{t.raw}|")
    print(f"\nFields (SPEC §2, BENCALC.cbl lines {cobol_ranges('2')[0][0]}-{cobol_ranges('2')[0][1]})")
    for a, b, name, pic in FIELDS:
        val = t.fields[name]
        cols = f"{a}-{b}" if a != b else f"{a}"
        print(f"  {cols:<6} {name:<13} {pic:<8} {val!r:<20} {_meaning(name, val)}")
    print("\nSteps")
    for section, line, text in t.steps:
        ref = f"§{section} | cbl {line}" if line else f"§{section}"
        print(f"  [{ref:<14}] {text}")
    print(f"\nResult:      {t.status} {money(t.benefit)} reason {t.reason or '(blank)'}")
    print(f"Report line: {t.report_line!r}  (SPEC §5.1)")
    if t.notes:
        print("\nWorth knowing")
        for n in t.notes:
            print(f"  - {n}")


def _meaning(name, val):
    if name == "AP-LAST-NAME":
        return "never used"
    if name == "AP-ID":
        return "echoed to report"
    if name == "AP-STATE":
        return {"AK": "x1.25 threshold", "HI": "x1.15 threshold"}.get(val, "no adjustment (only AK/HI count)")
    if name in ("AP-DISABLED", "AP-VETERAN"):
        return "yes" if val == "Y" else "no"
    if not numeric(val):
        return "NOT NUMERIC -> R01"
    if name == "AP-INCOME":
        return f"{money(Decimal(val) / 100)} (implied 2 decimals)"
    return str(int(val))


# ---------- commands ----------

def cmd_toc(_):
    _, sections = spec_sections()
    for num, level, title, _, _ in sections:
        pad = "  " * (level - 2)
        cob = ", ".join(f"{a}-{b}" if a != b else str(a) for a, b in cobol_ranges(num))
        print(f"{pad}{num:<5} {title}" + (f"   [cbl {cob}]" if cob else ""))


def cmd_show(args):
    lines, sections = spec_sections()
    for num, _, _, start, end in sections:
        if num == args.section:
            print("\n".join(lines[start:end]).rstrip())
            return 0
    print(f"No section {args.section!r}; try: {' '.join(s[0] for s in sections)}", file=sys.stderr)
    return 1


def cmd_cobol(args):
    lines = cobol_lines()
    ranges = cobol_ranges(args.section, lines)
    if not ranges:
        print(f"No COBOL mapping for section {args.section!r}; mapped: {' '.join(COBOL_MAP)}", file=sys.stderr)
        return 1
    prev = None
    for a, b in ranges:
        if prev is not None and a != prev + 1:
            print("   ...")
        for i in range(a, b + 1):
            print(f"{i:4}  {lines[i - 1][6:]}")
        prev = b
    return 0


def cmd_search(args):
    pat = re.compile(re.escape(args.term), re.IGNORECASE)
    lines, sections = spec_sections()
    hits = 0
    for i, ln in enumerate(lines):
        if pat.search(ln):
            sec = section_of(i, sections)
            print(f"SPEC.md:{i + 1:<4} [§{sec[0] if sec else '-'}] {ln.strip()}")
            hits += 1
    for i, ln in enumerate(cobol_lines(), 1):
        if pat.search(ln):
            print(f"BENCALC.cbl:{i:<4} {ln[6:].strip()}")
            hits += 1
    if not hits:
        print(f"No matches for {args.term!r}")
    return 0 if hits else 1


def cmd_ambiguities(_):
    """Every paragraph or bullet marked with the warning sign, plus every item in §6."""
    lines, sections = spec_sections()
    six = next((st, en) for num, _, _, st, en in sections if num == "6")
    for i, ln in enumerate(lines):
        in_six = six[0] < i < six[1] and re.match(r"^\d+\. ", ln)
        if not in_six and (WARN not in ln or ln.startswith("#") or "Items marked" in ln):
            continue
        text = [ln]
        for nxt in lines[i + 1:]:
            if not nxt.strip() or re.match(r"^(- |\d+\. |#|```|\|)", nxt):
                break
            text.append(nxt)
        sec = section_of(i, sections)
        joined = re.sub(r"\s+", " ", " ".join(text).replace(WARN + "\ufe0f", "").replace(WARN, "")).strip(" -")
        print(f"[§{sec[0] if sec else '-'}] {joined}\n")


def read_records(path):
    with open(path, encoding="latin-1", newline="") as fh:
        return [ln.rstrip("\r\n") for ln in fh]


def build_record(args):
    """Build a 40-byte record from options; returns (record, error)."""
    try:
        inc = Decimal(args.income)
    except ArithmeticError:
        return None, f"--income {args.income!r} is not a number"
    if not 0 <= args.hh <= 99:
        return None, f"--hh {args.hh} does not fit AP-HH-SIZE 9(2) (0-99)"
    if not 0 <= inc <= Decimal("999999.99") or inc != inc.quantize(CENT):
        return None, f"--income {args.income} does not fit AP-INCOME 9(6)V99 (0-999999.99, at most 2 decimals)"
    if not 0 <= args.age <= 999:
        return None, f"--age {args.age} does not fit AP-AGE 9(3) (0-999)"
    rec = (f"{args.id:<8.8}{'TEST':<15}{args.state:<2.2}{args.hh:02d}{int(inc * 100):08d}"
           f"{args.age:03d}{'Y' if args.disabled else 'N'}{'Y' if args.veteran else 'N'}")
    return rec, None


def cmd_explain(args):
    if args.target is None:
        if args.hh is None:
            print("explain needs an applicant ID, a raw 40-byte record, or --hh/--income/--age", file=sys.stderr)
            return 2
        rec, err = build_record(args)
        if err:
            print(err, file=sys.stderr)
            return 2
        print_trace(trace(rec), " (built from options)")
        return 0
    if len(args.target) > 8:
        print_trace(trace(args.target), " (raw record)")
        return 0
    path = Path(args.file)
    for n, raw in enumerate(read_records(path), 1):
        if raw[0:8].strip() == args.target.strip():
            print_trace(trace(raw), f" ({path.name} line {n})")
            return 0
    print(f"{args.target!r} not found in {path}", file=sys.stderr)
    return 1


def cmd_walk(args):
    path = Path(args.file)
    coverage = Counter()
    for raw in read_records(path):
        t = trace(raw)
        coverage.update(t.tags)
        flags = ",".join(sorted(t.tags - {"ELIGIBLE", t.reason}))
        print(f"{t.report_line:<30} {flags}")
    print(f"\nCoverage in {path.name} (records per rule/trap):")
    for tag in ALL_TAGS + sorted(set(coverage) - set(ALL_TAGS)):
        print(f"  {tag:<24} {coverage.get(tag, 0):>4}" + ("   <- never exercised" if not coverage.get(tag) else ""))
    return 0


ALL_TAGS = ["ELIGIBLE", "D20", "M23", "I01", "Z00", "R01", "AK", "HI", "veteran", "elderly", "age-60",
            "ak-hi", "net-floor", "truncation", "at-limit", "hh-over-8", "addon-rescue",
            "m23-over-d20", "disabled-under-130", "small-benefit", "overflow", "short-line", "long-line", "lowercase-flag", "lowercase-state", "odd-age"]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("toc", help="list SPEC.md sections with their COBOL lines").set_defaults(fn=cmd_toc)
    s = sub.add_parser("show", help="print one SPEC.md section")
    s.add_argument("section")
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser("cobol", help="print the COBOL lines for a SPEC.md section")
    s.add_argument("section")
    s.set_defaults(fn=cmd_cobol)
    s = sub.add_parser("search", help="find a term in SPEC.md and BENCALC.cbl")
    s.add_argument("term")
    s.set_defaults(fn=cmd_search)
    sub.add_parser("ambiguities", help="list items SPEC.md flags as ambiguous").set_defaults(fn=cmd_ambiguities)
    s = sub.add_parser("explain", help="trace one record through every rule")
    s.add_argument("target", nargs="?", help="applicant ID (looked up in --file) or a raw record")
    s.add_argument("--file", default=str(DEFAULT_DATA))
    s.add_argument("--hh", type=int)
    s.add_argument("--income", default="0")
    s.add_argument("--age", type=int, default=30)
    s.add_argument("--state", default="TX")
    s.add_argument("--disabled", action="store_true")
    s.add_argument("--veteran", action="store_true")
    s.add_argument("--id", default="X0000001")
    s.set_defaults(fn=cmd_explain)
    s = sub.add_parser("walk", help="trace every record in a file and show rule coverage")
    s.add_argument("--file", default=str(DEFAULT_DATA))
    s.set_defaults(fn=cmd_walk)
    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
