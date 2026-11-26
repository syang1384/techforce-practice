#!/usr/bin/env python3
"""Differential fuzzer: the Python port against the compiled legacy COBOL program.

Generates input files, runs both programs and compares the reports byte for byte.
A mismatch is shrunk to the fewest input lines that still reproduce it. It also checks
that legacy/expected/*.txt is what the COBOL program produces today.

    python3 fuzz_parity.py --files 200 --seed 1        # needs `cobc` (gnucobol)

Exit code 0 means every file matched, 1 means a divergence was found.
"""
import argparse
import collections
import os
import random
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

HH = [0, 1, 2, 3, 4, 7, 8, 9, 10, 47, 48, 49, 50, 98, 99]
AGES = [0, 1, 18, 59, 60, 61, 100, 999]
STATES = [b"AK", b"HI", b"TX", b"CA", b"ak", b"hi", b"Ak", b"  ", b"A ", b"KA"]
FLAGS = [b"Y", b"N", b"y", b" ", b"X"]
JUNK = [b" ", b"-", b"+", b".", b"A", b"\t", b"\0", b"\r", b"\x0c", b"\x1a", b"\xe9", b"\xff"]


def thresholds(hh, state):
    """Income values (in cents) where the legacy rules change outcome."""
    base = (1580 + 560 * (hh - 1)) * 100
    if state == b"AK":
        base = base * 125 // 100
    if state == b"HI":
        base = base * 115 // 100
    allot = 290 + 240 * (hh - 1) if hh <= 8 else 1970 + 200 * (hh - 8)
    points = [0, 19800, base * 130 // 100, base * 2]
    for extra in (0, 25, 50, 75):
        # income at which the benefit crosses 0 and the $23 minimum
        points.append(19800 + (allot + extra) * 1000 // 3)
        points.append(19800 + (allot + extra - 23) * 1000 // 3)
    return points


def valid_record(rng, n):
    hh = rng.choice(HH) if rng.random() < 0.7 else rng.randint(0, 99)
    state = rng.choice(STATES)
    if rng.random() < 0.75:
        income = rng.choice(thresholds(max(hh, 1), state)) + rng.randint(-4, 4)
    else:
        income = rng.randint(0, 99999999)
    income = min(max(income, 0), 99999999)
    age = rng.choice(AGES) if rng.random() < 0.8 else rng.randint(0, 999)
    return b"%c%07d%-15s%s%02d%08d%03d%s%s" % (
        rng.choice(b"ABZ"), n % 10000000, rng.choice([b"SMITH", b"O'NEIL", b"", b"DE LA CRUZ-VEGA"]),
        state, hh, income, age, rng.choice(FLAGS), rng.choice(FLAGS))


def corrupt_field(rng, rec):
    """Damage one byte inside a numeric field, the state or a flag."""
    rec = bytearray(rec)
    pos = rng.randint(23, 39)
    rec[pos:pos + 1] = rng.choice(JUNK)
    return bytes(rec)


def mangle(rng, rec):
    """Structural damage: wrong length, stray bytes anywhere, random bytes."""
    kind = rng.randrange(6)
    if kind == 0:
        return rec[:rng.randint(0, 40)]
    if kind == 1:
        return rec + bytes(rng.choice(b"X 9Y\r\t") for _ in range(rng.randint(1, 80)))
    if kind == 2:
        pos = rng.randint(0, len(rec))
        return rec[:pos] + rng.choice(JUNK) + rec[pos:]
    if kind == 3:
        pos = rng.randint(0, len(rec) - 1)
        return rec[:pos] + rec[pos + 1:]
    if kind == 4:
        return bytes(rng.choice([c for c in range(256) if c != 10]) for _ in range(rng.randint(0, 60)))
    return b""


def make_file(rng, profile, records):
    lines = []
    for n in range(rng.randint(0, records)):
        rec = valid_record(rng, n)
        roll = rng.random()
        if profile != "valid" and roll < 0.15:
            rec = corrupt_field(rng, rec)
        elif profile == "bytes" and roll < 0.40:
            rec = mangle(rng, rec)
        lines.append(rec)
    eol = b"\r\n" if profile == "bytes" and rng.random() < 0.2 else b"\n"
    return lines, eol, not (profile == "bytes" and rng.random() < 0.2)


def join(lines, eol, final_eol):
    data = eol.join(lines)
    return data + eol if lines and final_eol else data


def overflow_cases():
    """Enough records to wrap the 9(5) counters and the 9(8)V99 total (SPEC.md 6.1)."""
    eligible = b"A0000001SMITH          TX0100000000034NN\n"
    denied = b"A0000002SMITH          TX0199999999034NN\n"
    big = b"A0000003SMITH          TX4700000000034NN\n"  # benefit 9770.00
    yield "counters past 99,999", eligible * 100001 + denied * 100005 + b"\n" * 100002
    yield "total past 99,999,999.99", big * 10300


class Oracle:
    """The legacy program, compiled once. Its input and output paths are hard-coded."""

    def __init__(self, port_cmd):
        self.port_cmd = shlex.split(port_cmd)
        if not shutil.which("cobc"):
            sys.exit("fuzz_parity: cobc not found. Install gnucobol first.")
        self.dir = tempfile.mkdtemp(prefix="bencalc-oracle-")
        os.makedirs(os.path.join(self.dir, "data"))
        os.makedirs(os.path.join(self.dir, "out"))
        subprocess.run(["cobc", "-x", "-o", os.path.join(self.dir, "bencalc"),
                        str(ROOT / "legacy" / "BENCALC.cbl")], check=True)

    def run(self, data):
        inp = os.path.join(self.dir, "data", "applicants.dat")
        out = os.path.join(self.dir, "out", "report.txt")
        with open(inp, "wb") as f:
            f.write(data)
        if os.path.exists(out):
            os.unlink(out)
        proc = subprocess.run([os.path.join(self.dir, "bencalc")], cwd=self.dir, capture_output=True)
        if proc.returncode != 0:
            return b"<legacy exit %d: %s>" % (proc.returncode, proc.stderr.strip())
        with open(out, "rb") as f:
            return f.read()

    def port(self, data):
        inp = os.path.join(self.dir, "port-input.dat")
        with open(inp, "wb") as f:
            f.write(data)
        proc = subprocess.run(self.port_cmd + [inp], capture_output=True, cwd=ROOT)
        if proc.returncode != 0:
            return b"<port exit %d: %s>" % (proc.returncode, proc.stderr.strip()[-300:])
        return proc.stdout

    def differs(self, data):
        return self.run(data) != self.port(data)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def shrink(oracle, lines, eol, final_eol):
    """Delta debugging over lines: drop chunks while the mismatch survives."""
    chunk = max(len(lines) // 2, 1)
    while chunk >= 1:
        i = 0
        while i < len(lines):
            trial = lines[:i] + lines[i + chunk:]
            if oracle.differs(join(trial, eol, final_eol)):
                lines = trial
            else:
                i += chunk
        chunk //= 2
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--files", type=int, default=200, help="input files to generate (default 200)")
    ap.add_argument("--records", type=int, default=400, help="max records per file (default 400)")
    ap.add_argument("--seed", type=int, default=None, help="random seed (default: random, printed)")
    ap.add_argument("--profile", choices=["valid", "fields", "bytes", "all"], default="all",
                    help="valid: well-formed records at rule boundaries; fields: plus damaged "
                         "fields; bytes: plus arbitrary bytes, bad lengths and CRLF")
    ap.add_argument("--port", default=f"{shlex.quote(sys.executable)} bencalc.py",
                    help="command for the implementation under test, run from the repo root "
                         "as: <command> <input-file> (default: python3 bencalc.py)")
    args = ap.parse_args()
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2 ** 32)
    rng = random.Random(seed)
    profiles = ["valid", "fields", "bytes"] if args.profile == "all" else [args.profile]

    oracle = Oracle(args.port)
    records = 0
    outcomes = collections.Counter()
    try:
        for data_name, report_name in (("applicants", "report"), ("holdout", "holdout_report")):
            data = (ROOT / "legacy" / "data" / f"{data_name}.dat").read_bytes()
            if oracle.run(data) != (ROOT / "legacy" / "expected" / f"{report_name}.txt").read_bytes():
                print(f"STALE  legacy/expected/{report_name}.txt is not what the COBOL program produces")
                return 1
        for name, data in overflow_cases():
            if oracle.differs(data):
                print(f"DIVERGENCE  fixed case: {name}")
                print(f"  legacy summary: {oracle.run(data)[-160:]!r}")
                print(f"  port summary:   {oracle.port(data)[-160:]!r}")
                return 1
        for n in range(args.files):
            profile = profiles[n % len(profiles)]
            lines, eol, final_eol = make_file(rng, profile, args.records)
            records += len(lines)
            legacy = oracle.run(join(lines, eol, final_eol))
            for detail in legacy.split(b"\n")[:-6]:
                outcomes[detail[9:17].strip().decode() + "/" + (detail[26:30].decode() or "-")] += 1
            if legacy == oracle.port(join(lines, eol, final_eol)):
                continue
            lines = shrink(oracle, lines, eol, final_eol)
            data = join(lines, eol, final_eol)
            print(f"DIVERGENCE  seed={seed} file={n} profile={profile}")
            print(f"  input  ({len(lines)} line(s)): {data!r}")
            print(f"  legacy: {oracle.run(data)!r}")
            print(f"  port:   {oracle.port(data)!r}")
            return 1
        print(f"PASS  {args.files} files, {records} records, seed={seed}: port output is byte-identical to COBOL")
        print("      legacy/expected/*.txt regenerated from COBOL and unchanged")
        print("      counter and total overflow cases also match")
        print("      legacy outcomes exercised: " + ", ".join(f"{k} {v}" for k, v in sorted(outcomes.items())))
        return 0
    finally:
        oracle.close()


if __name__ == "__main__":
    sys.exit(main())
