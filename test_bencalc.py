"""Unit tests for bencalc.py, one group per SPEC.md section."""
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

import bencalc

ROOT = Path(__file__).resolve().parent


def line(hh=1, income="0", age=30, state="TX", disabled="N", veteran="N", id_="T0000001",
         hh_raw=None, income_raw=None, age_raw=None):
    hh_f = hh_raw if hh_raw is not None else f"{hh:02d}"
    inc_f = income_raw if income_raw is not None else f"{int(Decimal(income) * 100):08d}"
    age_f = age_raw if age_raw is not None else f"{age:03d}"
    rec = f"{id_:<8}{'DOE':<15}{state:<2}{hh_f}{inc_f}{age_f}{disabled}{veteran}"
    assert len(rec) == 40
    return rec


def ev(**kw):
    status, benefit, reason = bencalc.evaluate(bencalc.parse(line(**kw)))
    return status, benefit, reason


def elig(benefit, reason=""):
    return ("ELIGIBLE", Decimal(benefit), reason)


DENIED_I01 = ("DENIED", Decimal(0), "I01")
DENIED_Z00 = ("DENIED", Decimal(0), "Z00")
REJECT_R01 = ("REJECT", Decimal(0), "R01")


# --- 3.1 Validation (R01) ---------------------------------------------------

@pytest.mark.parametrize("field", [
    {"hh_raw": "0A"}, {"hh_raw": " 1"}, {"hh_raw": "00"},
    {"income_raw": "0000 100"}, {"income_raw": "+0001000"}, {"income_raw": "        "},
    {"age_raw": " 60"}, {"age_raw": "-01"}, {"age_raw": "abc"},
    {"income_raw": "0001.000"}, {"income_raw": "1000,000"}, {"hh_raw": "\x001"},
])
def test_invalid_fields_reject_r01(field):
    assert ev(**field) == REJECT_R01


def test_short_line_rejects_r01():
    assert bencalc.evaluate(bencalc.parse("T0000001DOE            TX01")) == REJECT_R01


@pytest.mark.parametrize("age", [0, 999])
def test_age_not_range_checked(age):
    assert ev(age=age)[0] == "ELIGIBLE"


# --- 3.2 / 3.3 Thresholds and eligibility -----------------------------------

@pytest.mark.parametrize("state,hh,limit130", [
    ("TX", 1, "2054.00"),   # 1580 * 1.30
    ("TX", 4, "4238.00"),   # 3260 * 1.30
    ("AK", 1, "2567.50"),   # 1580 * 1.25 * 1.30
    ("HI", 1, "2362.10"),   # 1580 * 1.15 * 1.30
])
def test_exactly_130_percent_is_eligible_one_cent_over_is_i01(state, hh, limit130):
    assert ev(state=state, hh=hh, income=limit130)[2] != "I01"
    over = str(Decimal(limit130) + Decimal("0.01"))
    assert ev(state=state, hh=hh, income=over) == DENIED_I01


def test_exactly_130_percent_hh4_reaches_benefit_calc_and_gets_z00():
    assert ev(hh=4, income="4238.00") == DENIED_Z00


def test_state_codes_are_case_sensitive():
    assert ev(state="AK", income="2054.01")[2] != "I01"
    assert ev(state="ak", income="2054.01") == DENIED_I01


def test_disabled_within_130_percent_keeps_blank_reason():
    assert ev(hh=4, income="0", disabled="Y") == elig("1010.00")


def test_disabled_above_200_percent_is_i01():
    assert ev(hh=1, income="3160.00", disabled="Y")[2] != "I01"   # limit200 = 3160.00
    assert ev(hh=1, income="3160.01", disabled="Y") == DENIED_I01


def test_lowercase_disabled_flag_is_not_disabled():
    assert ev(hh=1, income="2054.01", disabled="y") == DENIED_I01


def test_d20_is_overwritten_by_m23_for_small_households():
    assert ev(hh=1, income="2054.01", disabled="Y") == elig("23.00", "M23")


def test_d20_path_for_large_household_ends_in_z00():
    assert ev(hh=4, income="4238.01", disabled="Y") == DENIED_Z00


def test_d20_band_never_yields_positive_benefit():
    """SPEC 3.4: past 130% the contribution always exceeds the allotment, so D20 is never printed."""
    for hh in range(1, 100):
        for state in ("TX", "AK", "HI"):
            mult = {"TX": 1, "AK": Decimal("1.25"), "HI": Decimal("1.15")}[state]
            limit130 = (1580 + 560 * (hh - 1)) * mult * Decimal("1.30")
            income = str(limit130 + Decimal("0.01"))
            status, _, reason = ev(hh=hh, state=state, income=income, disabled="Y",
                                   veteran="Y", age=60)
            assert reason != "D20" and status in ("ELIGIBLE", "DENIED")


# --- 3.4 Benefit calculation --------------------------------------------------

@pytest.mark.parametrize("hh,allot", [
    (1, "290.00"), (2, "530.00"), (3, "770.00"), (7, "1730.00"),
    (8, "1970.00"),   # last +240 step
    (9, "2170.00"),   # first +200 step
    (10, "2370.00"),
])
def test_max_allotment_steps(hh, allot):
    assert ev(hh=hh, income="0") == elig(allot)


@pytest.mark.parametrize("income,benefit", [
    ("0", "290.00"),
    ("197.99", "290.00"),   # below the 198 deduction: net clamps to 0
    ("198.00", "290.00"),
    ("198.03", "290.00"),   # 0.009 truncates to 0.00
    ("198.04", "289.99"),   # 0.012 truncates to 0.01
])
def test_standard_deduction_boundary(income, benefit):
    assert ev(hh=1, income=income) == elig(benefit)


def test_contribution_truncated_not_rounded():
    # SPEC example A0000011: net 1597.33 * 0.30 = 479.199 -> 479.19; 530 - 479.19 + 25
    assert ev(hh=2, income="1795.33", age=60) == elig("75.81")


@pytest.mark.parametrize("age,veteran,benefit", [
    (59, "N", "1010.00"),
    (60, "N", "1035.00"),
    (59, "Y", "1060.00"),
    (60, "Y", "1085.00"),
    (60, "y", "1035.00"),   # lowercase flag ignored
])
def test_veteran_and_age_60_add_ons(age, veteran, benefit):
    assert ev(hh=4, income="0", age=age, veteran=veteran) == elig(benefit)


# --- 3.4 Minimum-benefit rules (M23 / Z00) ----------------------------------

@pytest.mark.parametrize("hh,income,expected", [
    (1, "1131.33", elig("23.00", "M23")),   # benefit 10.01 -> raised to 23
    (1, "1088.00", elig("23.00")),          # benefit exactly 23.00, no M23
    (1, "1164.67", elig("23.00", "M23")),   # benefit exactly 0.00
    (1, "2000.00", elig("23.00", "M23")),   # negative benefit
    (3, "2764.64", elig("0.01")),           # hh >= 3 has no minimum
    (3, "2764.67", DENIED_Z00),             # benefit exactly 0.00
    (3, "3000.00", DENIED_Z00),
    (1, "1164.64", elig("23.00", "M23")),   # benefit 0.01 -> raised to 23
    (2, "1931.34", elig("23.00", "M23")),   # hh 2, benefit 10.00 -> raised to 23
    (2, "1888.00", elig("23.00")),          # hh 2, benefit exactly 23.00, no M23
    (2, "2782.00", elig("23.00", "M23")),   # hh 2, negative benefit
])
def test_minimum_benefit_rules(hh, income, expected):
    assert ev(hh=hh, income=income) == expected


def test_add_ons_apply_before_minimum_checks():
    assert ev(hh=3, income="2764.67", veteran="Y") == elig("50.00")
    assert ev(hh=1, income="1164.67", veteran="Y") == elig("50.00")
    assert ev(hh=1, income="1164.67", age=60) == elig("25.00")


# --- 5. Report format ---------------------------------------------------------

FORMAT_INPUT = [
    line(id_="A1", hh=1, income="0"),
    line(id_="A2", hh=1, income="2000.00"),
    line(id_="A3", hh_raw="00"),
    line(id_="A4", hh=4, income="9999.99"),
]


def test_detail_lines_and_trailing_space_stripping():
    # Expected lines captured from the compiled legacy/BENCALC.cbl.
    assert bencalc.run(FORMAT_INPUT)[:4] == [
        "A1       ELIGIBLE  290.00",
        "A2       ELIGIBLE   23.00 M23",
        "A3       REJECT      0.00 R01",
        "A4       DENIED      0.00 I01",
    ]


def test_summary_counts_print_with_cents():
    assert bencalc.run(FORMAT_INPUT)[4:] == [
        "RECORDS READ               4.00",
        "ELIGIBLE                   2.00",
        "DENIED                     1.00",
        "REJECTED                   1.00",
        "TOTAL BENEFITS           313.00",
    ]


def test_benefit_display_overflow_keeps_full_total():
    out = bencalc.run([line(hh=50), line(hh=48, veteran="Y")])
    assert out[0] == "T0000001 ELIGIBLE  370.00"   # true benefit 10370.00
    assert out[1] == "T0000001 ELIGIBLE   20.00"   # true benefit 10020.00
    assert out[-1] == "TOTAL BENEFITS         20390.00"


def test_long_lines_ignore_bytes_past_40():
    assert bencalc.run([line() + "GARBAGE"])[0] == "T0000001 ELIGIBLE  290.00"


def test_cli_preserves_non_ascii_bytes(tmp_path):
    data = tmp_path / "in.dat"
    data.write_bytes(line(id_="A\xe9000001").encode("latin-1") + b"\n")
    out = subprocess.run([sys.executable, str(ROOT / "bencalc.py"), str(data)],
                         capture_output=True, check=True).stdout
    assert out.splitlines()[0] == b"A\xe9000001 ELIGIBLE  290.00"


def test_cli_missing_file_exits_1(tmp_path):
    missing = tmp_path / "nope"
    proc = subprocess.run([sys.executable, str(ROOT / "bencalc.py"), str(missing)],
                          capture_output=True, text=True)
    assert proc.returncode == 1 and proc.stdout == ""
    assert proc.stderr == f"bencalc: file does not exist: {missing}\n"


def test_cli_without_input_file_exits_2():
    proc = subprocess.run([sys.executable, str(ROOT / "bencalc.py")], capture_output=True, text=True)
    assert proc.returncode == 2 and proc.stderr.startswith("usage:")


# --- 1 Record splitting (LINE SEQUENTIAL) -----------------------------------
# Expected values captured from the compiled legacy/BENCALC.cbl.

REC = line().encode()


@pytest.mark.parametrize("data,expected", [
    (b"", []),
    (REC + b"\n", [REC]),
    (REC, [REC]),                                    # last line without LF still counts
    (REC + b"\r\n", [REC]),                          # CRLF
    (REC[:30] + b"\r" + REC[30:] + b"\n", [REC]),    # CR inside a record is dropped, not a line break
    (REC + b"\r\r\n", [REC]),
    (b"\n\n", [b"", b""]),                           # blank lines are records (rejected later)
    (b"\r", []),                                     # a lone CR is not a record
    (REC + b"\n\r", [REC]),
    (b"\r\n", [b""]),
])
def test_read_records_matches_cobol_line_sequential(data, expected):
    assert bencalc.read_records(data) == [e.decode() for e in expected]


def test_cli_stray_carriage_return_does_not_split_the_record(tmp_path):
    # Found by fuzz_parity.py: the port used to report two REJECT lines here.
    data = tmp_path / "in.dat"
    data.write_bytes(REC[:30] + b"\r" + REC[30:] + b"\n")
    out = subprocess.run([sys.executable, str(ROOT / "bencalc.py"), str(data)],
                         capture_output=True, check=True).stdout
    assert out.splitlines()[:2] == [b"T0000001 ELIGIBLE  290.00", b"RECORDS READ               1.00"]


# --- 6.1 Counter and total overflow -----------------------------------------
# Expected values captured from the compiled legacy/BENCALC.cbl.

def test_counters_wrap_at_100000_records():
    out = bencalc.run([line()] * 100001 + [line(income="99999.99")] * 100005 + [""] * 100002)
    assert out[-5:] == [
        "RECORDS READ               8.00",
        "ELIGIBLE                   1.00",
        "DENIED                     5.00",
        "REJECTED                   2.00",
        "TOTAL BENEFITS      29000290.00",
    ]


def test_total_wraps_at_100_million():
    out = bencalc.run([line(hh=47)] * 10300)    # 10300 x 9770.00 = 100,631,000.00
    assert out[-1] == "TOTAL BENEFITS        631000.00"
