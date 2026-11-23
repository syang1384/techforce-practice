# Devin Prompts to Practice

Push this kit to a GitHub repo, connect it to Devin (app.devin.ai), then try the prompts below.

**1. Spec extraction (Ask Devin or a session)**
> Read legacy/BENCALC.cbl and write SPEC.md documenting the input record layout (byte
> offsets, implied decimals), every eligibility and benefit rule in order, all reason codes,
> rounding/truncation behavior, and the exact report and summary format. Flag anything ambiguous.

**2. Port with a parity gate**
> Using SPEC.md and BENCALC.cbl as the source of truth, implement a Python 3 CLI `bencalc.py
> <input>` that prints the report to stdout. Use Decimal, not float. Done means
> `./check_parity.sh "python3 bencalc.py"` passes. Install gnucobol and run the original if
> you need to confirm behavior. Open a PR.

**3. Tests**
> Add pytest unit tests covering each rule and reason code from SPEC.md, including boundary
> cases (exactly 130%, age 60, household 8 vs 9, income below the 198 deduction). Add a
> GitHub Actions workflow that runs the tests and check_parity.sh.

**4. Ship**
> Add a FastAPI service with POST /eligibility that reuses the same calculation module,
> a minimal HTML form for caseworkers, and a Dockerfile. Include a README section on running it.

## Tips for the day
- Give Devin a **verifiable definition of done** (a parity script or tests). This matters more than anything else.
- Run 2–3 Devin sessions **in parallel** on independent tiers (e.g. tests vs. API) to save time.
- Use **Ask Devin** to understand code quickly before starting a build session.
- Review PRs as they come in. Steer early in chat rather than waiting for the end.
- Save 15 minutes for the demo. A passing parity diff on screen makes a strong demo.
