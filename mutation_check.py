#!/usr/bin/env python3
"""Mutation check: plant one small bug at a time in bencalc.py and see who notices.

For each mutant it runs the unit tests and, with --fuzz, the differential fuzzer.
The fuzzer only runs on mutants the unit tests missed. A mutant nothing catches is a
gap in the safety net, unless it is listed in EQUIVALENT with the reason it is harmless.

    python3 mutation_check.py            # unit tests only
    python3 mutation_check.py --fuzz     # also fuzz against COBOL (needs cobc)
"""
import argparse
import ast
import copy
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SWAPS = {ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Lt: ast.LtE, ast.LtE: ast.Lt,
         ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Add: ast.Sub, ast.Sub: ast.Add,
         ast.Mult: ast.Add, ast.And: ast.Or, ast.Or: ast.And}


# Mutants that cannot change any output, with the reason. Everything else must be caught.
EQUIVALENT = {
    "RECORD_LEN = 40  [40 -> 41]": "bytes past 40 are never read",
    "CENT = Decimal(\"0.01\")  ['0.01' -> '0.02']": "quantize only uses the exponent",
    "return bool(field) and set(field) <= DIGITS  [comparison 1: LtE -> Lt]":
        "a field has at most 8 characters, so it can never hold all 10 digits",
    "if hh > 8:  [comparison 1: Gt -> GtE]": "both formulas give 1970 at hh = 8",
    "if 0 < benefit < 23 and hh <= 2:  [comparison 1: Lt -> LtE]":
        "benefit <= 0 was already handled above",
    "total = (total + benefit) % 100000000  [Add -> Sub]":
        "the total is printed as an absolute value and the modulo keeps the magnitude",
}


def mutants(tree, lines):
    """Yield (description, mutated tree) for every single-point mutation."""
    for index, node in enumerate(ast.walk(tree)):
        def emit(change, what):
            clone = copy.deepcopy(tree)
            change(list(ast.walk(clone))[index])
            return f"{lines[node.lineno - 1].strip()}  [{what}]", clone

        if isinstance(node, ast.Compare):
            for pos, op in enumerate(node.ops):
                if type(op) in SWAPS:
                    new = SWAPS[type(op)]
                    yield emit(lambda n, pos=pos, new=new: n.ops.__setitem__(pos, new()),
                               f"comparison {pos + 1}: {type(op).__name__} -> {new.__name__}")
        elif isinstance(node, (ast.BinOp, ast.AugAssign, ast.BoolOp)) and type(node.op) in SWAPS:
            new = SWAPS[type(node.op)]
            yield emit(lambda n: setattr(n, "op", new()), f"{type(node.op).__name__} -> {new.__name__}")
        elif isinstance(node, ast.Constant) and type(node.value) is int:
            yield emit(lambda n: setattr(n, "value", n.value + 1), f"{node.value} -> {node.value + 1}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                bumped = str(Decimal(node.value) + Decimal("0.01"))
            except InvalidOperation:
                continue
            yield emit(lambda n: setattr(n, "value", bumped), f"'{node.value}' -> '{bumped}'")
        elif isinstance(node, ast.Name) and node.id == "ROUND_DOWN" and isinstance(node.ctx, ast.Load):
            yield emit(lambda n: setattr(n, "id", "ROUND_HALF_UP"), "ROUND_DOWN -> ROUND_HALF_UP")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fuzz", action="store_true", help="also run fuzz_parity.py on each mutant")
    ap.add_argument("--list", action="store_true", help="print the mutants and exit")
    args = ap.parse_args()
    source = (ROOT / "bencalc.py").read_text()
    source = source.replace("from decimal import ROUND_DOWN, Decimal",
                            "from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal")
    work = Path(tempfile.mkdtemp(prefix="bencalc-mutants-"))
    for name in ("app.py", "test_bencalc.py", "test_app.py", "web", "legacy"):
        src = ROOT / name
        (shutil.copytree if src.is_dir() else shutil.copy)(src, work / name)

    if args.list:
        for what, _ in mutants(ast.parse(source), source.splitlines()):
            print(what)
        return 0
    total = by_tests = by_fuzz = equivalent = 0
    survivors = []
    # A cached .pyc from the previous mutant can be reused when two mutants have the same
    # size and are written in the same second, so never write bytecode.
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    unused = set(EQUIVALENT)
    try:
        for what, tree in mutants(ast.parse(source), source.splitlines()):
            total += 1
            (work / "bencalc.py").write_text(ast.unparse(tree))
            tests = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"],
                                   cwd=work, capture_output=True, env=env)
            if tests.returncode != 0:
                by_tests += 1
                continue
            if what in EQUIVALENT:
                equivalent += 1
                unused.discard(what)
                continue
            if args.fuzz:
                port = f"{shlex.quote(sys.executable)} {shlex.quote(str(work / 'bencalc.py'))}"
                fuzz = subprocess.run([sys.executable, str(ROOT / "fuzz_parity.py"), "--files", "60",
                                       "--seed", "1", "--port", port], capture_output=True, env=env)
                if fuzz.returncode != 0:
                    by_fuzz += 1
                    print(f"  only the fuzzer caught  {what}")
                    continue
            survivors.append(what)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print(f"{total} mutants: unit tests caught {by_tests}"
          + (f", fuzzer caught {by_fuzz} more" if args.fuzz else "")
          + f", {equivalent} known equivalent, {len(survivors)} survived")
    for what in survivors:
        print(f"  SURVIVED  {what}")
    for what in sorted(unused):
        print(f"  STALE EQUIVALENT ENTRY (the tests now catch it, or the line changed)  {what}")
    return 1 if survivors or unused else 0


if __name__ == "__main__":
    sys.exit(main())
