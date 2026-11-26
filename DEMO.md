# Demo: BENCALC off the mainframe (2 minutes)

## What we built
`bencalc.py` replaces the 1994 COBOL batch job and writes the same report, byte for byte.
`app.py` puts the same rules behind `POST /eligibility` (one applicant, with the calculation
steps a caseworker can read back to the applicant) and `POST /report` (the whole monthly file).
It ships as a Docker image with a web form.

## How we know it's correct
The auditors' rule is an identical report for **every** input, and 216 supplied records can't
show that. So the COBOL program itself is the judge:

| Evidence | Result |
|---|---|
| Supplied files (`check_parity.sh`) | 216 of 216 records identical |
| Differential fuzz against the compiled COBOL (`fuzz_parity.py`) | 2.3 million generated records in 7,800 files, 0 differences |
| Counter and total overflow | Identical wrap at 100,000 records and at 100,000,000.00 |
| Mutation check (`mutation_check.py`) | Every bug planted in `bencalc.py` is caught, except 6 that provably cannot change output |
| `legacy/expected/*.txt` | Regenerated from COBOL in CI, unchanged |

Run it live: `python3 fuzz_parity.py --files 600` takes about 20 seconds.

## What the fuzzer found
1. **A real parity bug in our port that the supplied data and all 74 unit tests missed.** COBOL drops
   every carriage return, wherever it is. The port treated a stray one as a line break, so one
   payable record became two rejected ones. The fuzzer shrank a 400-record file to the one line
   that showed it. Fixed, with regression tests.
2. **The legacy job silently loses count.** At 100,000 records the counters restart from zero,
   and the total does the same at 100 million. Exit code 0, no warning. The port copies this
   because parity requires it, and SPEC.md §6.1 now says so with verified numbers.
3. **Reason code D20 can never be printed.** The disability exception admits applicants up to
   200% of the threshold, but at that income the contribution always exceeds the allotment. They
   get $23 (households of 1–2) or nothing (3+). A test checks every household size and state
   class, and the closest case is still 40.60 short. This is a policy question for the program owner, not something to "fix" in a port.

## What Devin did, and what the human did
- **Devin:** the spec, the port, the tests, the API, the form, CI, the fuzzer, the mutation
  check, and the three findings above. Each tier is its own PR.
- **Human:** set the definition of done (parity, then "prove it beyond the supplied data"),
  decided that the API rejects lowercase state codes instead of copying the COBOL quirk, and
  reviewed the PRs.
