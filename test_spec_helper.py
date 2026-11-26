"""spec_helper.py must agree with bencalc.py and stay in sync with SPEC.md and BENCALC.cbl."""
from pathlib import Path

import pytest

import bencalc
import spec_helper as sh

ROOT = Path(__file__).resolve().parent
DATA = sorted((ROOT / "legacy" / "data").glob("*.dat"))
PROBES = [
    "A1      X              ak0100050000061yN",          # lowercase state and flag
    "B1      X              TX5000000000030NY",          # benefit overflow
    "C1      X              TX0200278200030NN",          # exactly limit130
    "D1      X              TX0200428000030YN",          # exactly limit200, D20
    "E1      X              TX03 0150000040NN",          # leading space -> R01
    "F1      X              TX01",                       # short line
    "G1      X              TX0100000000030NNEXTRA",     # long line
    "H1      X              TX0300340000060NY",          # add-ons on hh 3
]


def records():
    for path in DATA:
        yield from sh.read_records(path)
    yield from PROBES


@pytest.mark.parametrize("raw", list(records()))
def test_trace_matches_bencalc(raw):
    t = sh.trace(raw)
    status, benefit, reason = bencalc.evaluate(bencalc.parse(raw))
    assert (t.status, t.benefit, t.reason) == (status, benefit, reason)
    assert t.report_line == bencalc.run([raw])[0]


def test_every_mapped_section_exists_in_spec():
    _, sections = sh.spec_sections()
    nums = {s[0] for s in sections}
    assert set(sh.COBOL_MAP) <= nums
    for num in sh.COBOL_MAP:
        assert sh.cobol_ranges(num), num


def test_every_cited_cobol_line_resolves():
    for raw in list(records()):
        for _, line, _ in sh.trace(raw).steps:
            assert line is not None and line > 0


def test_notes_flag_known_traps():
    assert "truncation" in sh.trace("A0000011MARTIN         IL0200179533060NN").tags
    assert "m23-over-d20" in sh.trace("A0000015TAYLOR         PA0200380000035YN").tags
    assert {"lowercase-flag", "lowercase-state"} <= sh.trace(PROBES[0]).tags
    assert "overflow" in sh.trace(PROBES[1]).tags
    assert "at-limit" in sh.trace(PROBES[2]).tags


@pytest.mark.parametrize("argv", [
    ["toc"], ["show", "3.4"], ["cobol", "3.4"], ["cobol", "4"], ["search", "truncat"],
    ["ambiguities"], ["explain", "A0000011"], ["explain", "--hh", "9", "--income", "100"],
    ["explain", PROBES[0]], ["walk"],
])
def test_cli(argv, capsys):
    assert sh.main(argv) == 0
    assert capsys.readouterr().out.strip()


def test_cli_unknown_section(capsys):
    assert sh.main(["show", "9.9"]) == 1


@pytest.mark.parametrize("opts", [
    ["--hh", "100"], ["--hh", "-1"], ["--hh", "2", "--income", "1.234"],
    ["--hh", "2", "--income", "1000000"], ["--hh", "2", "--income", "abc"], ["--hh", "2", "--age", "1000"],
])
def test_explain_rejects_values_that_do_not_fit_the_record(opts, capsys):
    assert sh.main(["explain", *opts]) == 2
    err = capsys.readouterr().err
    assert "does not fit" in err or "not a number" in err


def test_explain_raw_record_counts_bytes_like_data_files(tmp_path, capsys):
    raw = "N0000001MUÑOZ          TX0100000000034NN"
    (tmp_path / "d.dat").write_bytes(raw.encode("utf-8") + b"\n")
    assert sh.main(["explain", raw]) == 0
    from_arg = capsys.readouterr().out
    assert sh.main(["explain", "N0000001", "--file", str(tmp_path / "d.dat")]) == 0
    from_file = capsys.readouterr().out
    result = lambda out: [ln for ln in out.splitlines() if ln.startswith("Result:")]
    assert result(from_arg) == result(from_file)
