"""FastAPI service exposing the BENCALC rules (see SPEC.md) for one applicant at a time."""
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import bencalc

REASONS = {
    "D20": "Eligible through the disability exception (130% < income <= 200%)",
    "M23": "Benefit raised to the $23 minimum",
    "I01": "Income over the eligibility limit",
    "Z00": "Calculated benefit is zero or less",
}
FORM = Path(__file__).resolve().parent / "web" / "index.html"

app = FastAPI(title="BENCALC eligibility service")


class Applicant(BaseModel):
    """Field ranges mirror the fixed-width record in SPEC.md section 2."""
    household_size: int = Field(ge=1, le=99)
    income: Annotated[Decimal, Field(ge=0, le=Decimal("999999.99"), decimal_places=2)] = Field(
        description="Monthly gross income in dollars")
    age: int = Field(ge=0, le=999)
    state: str = Field(pattern=r"^[A-Z]{2}$", description="Two-letter uppercase state code")
    disabled: bool = False
    veteran: bool = False


class Determination(BaseModel):
    status: Literal["ELIGIBLE", "DENIED"]
    benefit: Decimal
    reason: Optional[str]
    reason_description: Optional[str]


@app.post("/eligibility", response_model=Determination)
def eligibility(a: Applicant) -> Determination:
    status, benefit, reason = bencalc.calculate(
        a.household_size, a.income, a.age, a.state, a.disabled, a.veteran)
    return Determination(status=status, benefit=benefit.quantize(bencalc.CENT),
                         reason=reason or None, reason_description=REASONS.get(reason))


@app.get("/", include_in_schema=False)
def form() -> FileResponse:
    return FileResponse(FORM)
