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
