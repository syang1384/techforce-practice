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

## Study the spec
`spec_helper.py` helps you read `SPEC.md` alongside `legacy/BENCALC.cbl` (standard library only).

```bash
python3 spec_helper.py toc                 # SPEC sections and the COBOL lines behind each
python3 spec_helper.py show 3.4            # print a section
python3 spec_helper.py cobol 3.4           # print the COBOL for that section
python3 spec_helper.py search truncat      # find a term in both files
python3 spec_helper.py ambiguities         # every item SPEC.md flags as ambiguous
python3 spec_helper.py explain A0000011    # trace one record through every rule
python3 spec_helper.py explain --hh 2 --income 1795.33 --age 60 --disabled
python3 spec_helper.py walk                # every record, plus which rules and traps the file exercises
```
`explain` and `walk` take `--file` to read another data file. Each trace step cites the SPEC section and
COBOL line, and ends with notes on traps the record hits (truncation, M23 overwriting D20, overflow, and so on).
The trace is written separately from `bencalc.py`, and `test_spec_helper.py` checks that the two agree.

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

Tests: `pip install -r requirements-dev.txt && python -m pytest`
