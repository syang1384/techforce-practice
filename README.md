# Tech Force Hackathon Practice Kit: Legacy Benefits Modernization

A practice run for a Devin hackathon. `legacy/BENCALC.cbl` is a 1990s COBOL batch job
that calculates monthly nutrition-assistance benefits from fixed-width applicant records.
There's no spec, no tests, and decades of patches. This is a common kind of government
modernization job.

Your job: use Devin to turn it into a modern, tested service **that produces identical output**.

## Layout
| Path | What |
|---|---|
| `legacy/BENCALC.cbl` | The legacy program (source of truth) |
| `legacy/data/applicants.dat` | 16 sample applicant records |
| `legacy/data/holdout.dat` | 200 more records. Don't look at them until the end |
| `legacy/expected/*.txt` | The exact output COBOL produces for each data file |
| `check_parity.sh` | Diffs your new implementation against the expected output |
| `CHALLENGE.md` | The timed brief |
| `PROMPTS.md` | Devin prompts to try, plus tips |

## Run the legacy program (optional)
```bash
sudo apt-get install -y gnucobol   # or: brew install gnucobol
cd legacy && mkdir -p out && cobc -x -o bencalc BENCALC.cbl && ./bencalc && cat out/report.txt
```

## Run the eligibility service
`app.py` serves the same rules as `bencalc.py` (it calls `bencalc.calculate`) for one applicant at a time.

```bash
pip install -r requirements.txt
uvicorn app:app --reload            # http://localhost:8000
```
Or with Docker:
```bash
docker build -t bencalc-api .
docker run --rm -p 8000:8000 bencalc-api
```

- `http://localhost:8000/` opens the caseworker form.
- `http://localhost:8000/docs` lists the API endpoints and lets you try them.

```bash
curl -X POST localhost:8000/eligibility -H 'content-type: application/json' \
  -d '{"household_size": 2, "income": "1795.33", "age": 60, "state": "TX", "disabled": false, "veteran": false}'
# {"status":"ELIGIBLE","benefit":"75.81","reason":null,"reason_description":null}
```
Pass `income` as a string, or as a JSON number with at most 2 decimals. `benefit` is returned as a string so no
precision is lost. Invalid input (household size outside 1–99, more than 2 decimals, a lowercase state, and so on) returns 422.
The batch job would mark those records as R01 or treat them differently. The API returns the full benefit,
even above 9999.99, while the batch report truncates the display (see SPEC.md §5.1).

Every response also has `steps`, the rules that produced the result in the order they applied, and the form shows them
under the result.

`POST /report` runs the whole batch. Send the applicant file as the body and get the report back, byte for byte what
the COBOL job writes:
```bash
curl -X POST localhost:8000/report --data-binary @legacy/data/applicants.dat
```

## How we know it's correct
| Check | Command | What it proves |
|---|---|---|
| Parity | `./check_parity.sh "python3 bencalc.py"` | Identical reports for the 216 supplied records |
| Unit tests | `python -m pytest` | Each rule in SPEC.md, one at a time |
| Differential fuzz | `python3 fuzz_parity.py --files 600` | Identical reports to the **compiled COBOL** for new generated files |
| Mutation check | `python3 mutation_check.py --fuzz` | The checks above notice a bug planted anywhere in `bencalc.py` |

`fuzz_parity.py` compiles `legacy/BENCALC.cbl` (needs `gnucobol`), generates applicant files aimed at the rule
boundaries (one cent either side of every limit) plus damaged fields, wrong lengths and arbitrary bytes, and compares
the two reports byte for byte. A mismatch is shrunk to the fewest input lines that reproduce it. Use `--seed` to
repeat a run and `--port "<command>"` to test another implementation.

Install the test tools with `pip install -r requirements-dev.txt`. CI runs all four checks.
