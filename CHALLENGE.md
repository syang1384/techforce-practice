# Challenge: Modernize BENCALC (2-hour timebox)

**Scenario:** An agency is retiring its mainframe. BENCALC has to move to a modern stack
before the contract ends. Auditors require a **byte-for-byte identical report** for every
input. Nobody who wrote it still works there.

## Tiers (go as far as you can)
1. **Understand (15 min):** Get Devin to produce `SPEC.md`. Include the record layout, every
   eligibility and benefit rule, reason codes, and edge cases.
2. **Port (45 min):** Rewrite in Python or TypeScript. The CLI takes an input file and prints
   the report to stdout. `./check_parity.sh "<your command>"` must pass on `applicants.dat`.
3. **Prove it (20 min):** Add unit tests for each rule. Then run the holdout check, which also
   diffs against `holdout.dat`.
4. **Ship it (30 min):** Wrap it in a REST API (`POST /eligibility`, JSON in and out). Add a
   small web form for caseworkers, CI, and a Dockerfile.
5. **Demo (10 min):** Give a 2-minute pitch covering what you built, how you know it's
   correct, and what Devin did vs. what you did.

## Traps to find (don't read until you're done)
<details><summary>Spoilers</summary>

- The 30% contribution is **truncated** to the cent, not rounded (audit finding 2008-17).
- AK and HI multipliers apply before the 130%/200% limits.
- Households over 8 get +200 per extra person, not +240.
- The $23 minimum applies only to households of 1–2. Larger households drop to DENIED/Z00.
- Disabled applicants between 130% and 200% are eligible (D20). But if they hit the minimum,
  the reason code becomes M23.
- A blank or non-numeric field, or household size 0, gives REJECT/R01.
- Summary counts print with `.00` (same picture clause as the total), and padding is exact.
- Age 60 and over gets +25. Veterans get +50, added before the minimum check.
</details>

## Judging checklist (like a typical hackathon)
- Correctness: parity passes on both files
- Devin used meaningfully: spec, code, tests, PRs
- Completeness: tiers reached
- Demo clarity
