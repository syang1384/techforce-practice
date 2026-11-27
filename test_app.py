"""API tests: the service must agree with the batch calculation it wraps."""
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bencalc
import app as app_module
from app import app

client = TestClient(app)
ROOT = Path(__file__).resolve().parent


def post(**overrides):
    body = {"household_size": 1, "income": "0", "age": 30, "state": "TX",
            "disabled": False, "veteran": False, **overrides}
    return client.post("/eligibility", json=body)


@pytest.mark.parametrize("body,expected", [
    ({}, ("ELIGIBLE", "290.00", None)),
    ({"household_size": 2, "income": "1795.33", "age": 60}, ("ELIGIBLE", "75.81", None)),
    ({"income": "2000.00"}, ("ELIGIBLE", "23.00", "M23")),
    ({"income": "2054.01"}, ("DENIED", "0.00", "I01")),
    ({"household_size": 4, "income": "4238.00"}, ("DENIED", "0.00", "Z00")),
    ({"household_size": 50}, ("ELIGIBLE", "10370.00", None)),   # full value, no display overflow
])
def test_determinations(body, expected):
    r = post(**body)
    assert r.status_code == 200
    d = r.json()
    assert (d["status"], d["benefit"], d["reason"]) == expected
    assert (d["reason_description"] is None) == (d["reason"] is None)


def test_json_number_income_is_exact():
    assert post(household_size=2, income=1795.33, age=60).json()["benefit"] == "75.81"


@pytest.mark.parametrize("body", [
    {"household_size": 0}, {"household_size": 100}, {"income": "-1"}, {"income": "1.001"},
    {"income": "1000000.00"}, {"age": -1}, {"age": 1000}, {"state": "tx"}, {"state": "TEX"},
])
def test_invalid_input_is_422(body):
    assert post(**body).status_code == 422


def test_matches_batch_results_on_sample_and_holdout_data():
    for name in ("applicants.dat", "holdout.dat"):
        for line in (ROOT / "legacy" / "data" / name).read_text("latin-1").splitlines():
            rec = bencalc.parse(line)
            status, benefit, reason = bencalc.evaluate(rec)
            if status == "REJECT" or not rec["state"].isupper() or not rec["state"].isalpha():
                continue
            d = post(household_size=int(rec["hh"]), income=str(Decimal(rec["income"]) / 100),
                     age=int(rec["age"]), state=rec["state"], disabled=rec["disabled"],
                     veteran=rec["veteran"]).json()
            assert (d["status"], Decimal(d["benefit"]), d["reason"] or "") == \
                (status, benefit, reason), line


def test_steps_explain_the_result():
    d = post(household_size=2, income="1795.33", age=60, state="AK", veteran=True).json()
    assert [(s["description"], s["amount"]) for s in d["steps"]] == [
        ("Income threshold for a household of 2", "2140.00"),
        ("Alaska cost-of-living adjustment (x 1.25)", "2675.00"),
        ("Income limit (130% of threshold)", "3477.50"),
        ("Gross monthly income", "1795.33"),
        ("Maximum allotment for a household of 2", "530.00"),
        ("Net income (gross income minus the 198.00 deduction)", "1597.33"),
        ("Household contribution (30% of net income, cut to the cent)", "-479.19"),
        ("Veteran supplement", "50.00"),
        ("Age 60 or over supplement", "25.00"),
        ("Calculated benefit", "125.81"),
    ]
    assert d["benefit"] == "125.81"


@pytest.mark.parametrize("body,last_step", [
    ({"income": "2000.00"}, "Raised to the minimum benefit (households of 1 or 2)"),
    ({"income": "2054.01"}, "Income is over the limit: denied"),
    ({"income": "3160.01", "disabled": True}, "Income is over the limit: denied"),
    ({"income": "3160.00", "disabled": True}, "Raised to the minimum benefit (households of 1 or 2)"),
    ({"household_size": 4, "income": "4238.00"},
     "Zero or less, and households of 3 or more have no minimum: denied"),
])
def test_last_step_states_the_deciding_rule(body, last_step):
    d = post(**body).json()
    assert d["steps"][-1] == {"description": last_step, "amount": d["benefit"]}


@pytest.mark.parametrize("data,expected", [("applicants.dat", "report.txt"), ("holdout.dat", "holdout_report.txt")])
def test_report_endpoint_is_byte_identical_to_cobol(data, expected):
    r = client.post("/report", content=(ROOT / "legacy" / "data" / data).read_bytes())
    assert r.status_code == 200
    assert r.content == (ROOT / "legacy" / "expected" / expected).read_bytes()


def test_form_is_served():
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert 'fetch("/eligibility"' in r.text


def test_report_endpoint_rejects_oversized_file():
    assert client.post("/report", content=b"x" * app_module.MAX_REPORT_BYTES).status_code == 200
    assert client.post("/report", content=b"x" * (app_module.MAX_REPORT_BYTES + 1)).status_code == 413
