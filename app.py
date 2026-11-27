"""FastAPI service exposing the BENCALC rules (see SPEC.md) for one applicant at a time."""
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

import bencalc

REASONS = {
    "D20": "Eligible through the disability exception (130% < income <= 200%)",
    "M23": "Benefit raised to the $23 minimum",
    "I01": "Income over the eligibility limit",
    "Z00": "Calculated benefit is zero or less",
}
MAX_REPORT_BYTES = 5_000_000  # about 120,000 records, past the point where the COBOL counters wrap
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


class Step(BaseModel):
    description: str
    amount: Decimal


class Determination(BaseModel):
    status: Literal["ELIGIBLE", "DENIED"]
    benefit: Decimal
    reason: Optional[str]
    reason_description: Optional[str]
    steps: list[Step] = Field(description="The rules that produced this result, in the order they applied")


@app.post("/eligibility", response_model=Determination)
def eligibility(a: Applicant) -> Determination:
    trace = []
    status, benefit, reason = bencalc.calculate(
        a.household_size, a.income, a.age, a.state, a.disabled, a.veteran, trace)
    return Determination(status=status, benefit=benefit.quantize(bencalc.CENT),
                         reason=reason or None, reason_description=REASONS.get(reason),
                         steps=[Step(description=d, amount=v.quantize(bencalc.CENT)) for d, v in trace])


def _report(data: bytes) -> bytes:
    return "".join(line + "\n" for line in bencalc.run(bencalc.read_records(data))).encode("latin-1")


@app.post("/report", response_class=Response,
          responses={200: {"content": {"text/plain": {}}}, 413: {"description": "File too large"}})
async def report(request: Request) -> Response:
    """Run the monthly batch: the body is the fixed-width applicant file, the response is
    the report, byte for byte what the COBOL job writes for the same file."""
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_REPORT_BYTES:
            raise HTTPException(413, f"Applicant file is larger than {MAX_REPORT_BYTES} bytes")
    # Off the event loop, so a large batch does not hold up /eligibility.
    return Response(await run_in_threadpool(_report, bytes(data)),
                    media_type="text/plain; charset=iso-8859-1")


@app.get("/", include_in_schema=False)
def form() -> FileResponse:
    return FileResponse(FORM)
