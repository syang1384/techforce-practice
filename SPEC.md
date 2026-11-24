# BENCALC Specification

Reverse-engineered from `legacy/BENCALC.cbl`. All edge-case behavior below was confirmed by
compiling the original with GnuCOBOL 3.1.2 and running probe records. **This document
describes what the program does, not what it should do.** Items marked ⚠️ are ambiguous or
look like bugs. Ask the program owner before "fixing" any of them, because a fix breaks parity.

## 1. I/O

| | Path (relative to working dir) | Organization |
|---|---|---|
| Input | `data/applicants.dat` | Line sequential, one 40-byte record per line |
| Output | `out/report.txt` | Line sequential |

- The paths are hard-coded, and the program takes no arguments.
- An empty input file produces a summary with every value `0.00`.
- ⚠️ If the input file is missing, the program aborts with `libcob: error: file does not exist (status = 35)`, exit code 1, and writes no report. There is no FILE STATUS handling.
- `out/` must already exist.

## 2. Input record layout (40 bytes)

| Bytes (1-based) | Len | Field | PIC | Meaning | Used? |
|---|---|---|---|---|---|
| 1–8 | 8 | `AP-ID` | `X(8)` | Applicant ID | Echoed to report |
| 9–23 | 15 | `AP-LAST-NAME` | `X(15)` | Last name | **Never used** |
| 24–25 | 2 | `AP-STATE` | `X(2)` | State code | Only `AK` and `HI` matter |
| 26–27 | 2 | `AP-HH-SIZE` | `9(2)` | Household size, 00–99 | Yes |
| 28–35 | 8 | `AP-INCOME` | `9(6)V99` | Gross monthly income, **implied decimal**: `00185000` = 1850.00, range 0–999999.99 | Yes |
| 36–38 | 3 | `AP-AGE` | `9(3)` | Age in years | Yes |
| 39 | 1 | `AP-DISABLED` | `X` | `Y` = disabled | Yes |
| 40 | 1 | `AP-VETERAN` | `X` | `Y` = veteran | Yes |

Parsing rules (verified):
- **Short lines** are space-padded to 40 bytes. A missing numeric field becomes non-numeric, so the record is rejected (R01).
- **Long lines:** bytes after position 40 are silently ignored.
- **Numeric fields** must be digits only. A leading space (` 3`), a sign (`-0100000`), or letters (`X3`) all make the field NOT NUMERIC, so the record is rejected (R01).
- **Flags and state are case-sensitive.** Only uppercase `Y`, `AK` and `HI` count. Any other value (`y`, `N`, a space, `ak`) means no or not applicable. ⚠️ These fields are not validated, so `y` is silently treated as `N`.

## 3. Processing rules (evaluated in this order for each record)

Every record starts with `benefit = 0` and `reason = blank`.

### 3.1 Validation
The record is **REJECT / R01** if any of these is true:
- `AP-HH-SIZE`, `AP-INCOME` or `AP-AGE` is not numeric
- `AP-HH-SIZE = 0`

Age is never range-checked, so `000` and `999` are both accepted.

### 3.2 Income thresholds
```
threshold = 1580 + 560 × (hh − 1)
if state = "AK": threshold = threshold × 1.25
if state = "HI": threshold = threshold × 1.15
limit130  = threshold × 1.30
limit200  = threshold × 2.00
```
Each step is truncated to 2 decimals (no `ROUNDED`). In practice the truncation never changes
anything, because the threshold is always a multiple of 20, so every product is exact.

### 3.3 Eligibility
| Condition | Result |
|---|---|
| `income ≤ limit130` | Go to benefit calculation (3.4), reason stays blank (even if disabled) |
| `income > limit130` and `disabled = Y` and `income ≤ limit200` | reason = **D20**, then go to benefit calculation (3.4) |
| otherwise | **DENIED / I01**, benefit 0.00 |

The comparisons are inclusive: income **exactly equal** to the limit passes.

### 3.4 Benefit calculation
```
max_allot = 290 + 240 × (hh − 1)                  if hh ≤ 8
          = 1970 + 200 × (hh − 8)                 if hh > 8
net       = max(income − 198, 0)
contrib   = TRUNCATE(net × 0.30, 2 decimals)      ← truncation, NOT rounding
benefit   = max_allot − contrib
if veteran = Y:  benefit += 50
if age ≥ 60:     benefit += 25
```
Then the minimum-benefit rules apply, in this order:
1. If `benefit ≤ 0`:
   - `hh ≤ 2`: benefit = **23.00**, reason = **M23**
   - `hh ≥ 3`: benefit = 0.00, **DENIED / Z00**
2. If `0 < benefit < 23` and `hh ≤ 2`: benefit = **23.00**, reason = **M23**
3. If `benefit > 0`: **ELIGIBLE**, and the benefit is added to the running total

Notes:
- The veteran and elderly add-ons are applied **before** the minimum check, so they can lift a household out of Z00 or M23.
- ⚠️ **M23 overwrites D20.** A disabled applicant in the 130–200% band who ends up at the $23 minimum is reported as M23, and the D20 information is lost.
- Households of 3 or more have no minimum. Any positive benefit is paid as calculated, even $0.01.
- Benefits are always whole cents, because `contrib` is truncated to cents.

**Truncation example (A0000011):** net = 1597.33. Then 1597.33 × 0.30 = 479.199, truncated to
479.19. The benefit is 530 − 479.19 + 25 = **75.81**. Rounding would give 75.80. The source
comment says *"DO NOT CHANGE ROUNDING – AUDIT FINDING 2008-17"*.

## 4. Reason codes

The code never defines these names. The meanings below are inferred from where each code is set.

| Code | Status | Meaning |
|---|---|---|
| *(blank)* | ELIGIBLE | Standard eligibility (income ≤ 130%) |
| `D20` | ELIGIBLE | Eligible through the disability exception (130% < income ≤ 200%) |
| `M23` | ELIGIBLE | Benefit raised to the $23 minimum (hh ≤ 2) |
| `I01` | DENIED | Income over the limit |
| `Z00` | DENIED | Calculated benefit ≤ 0 and hh ≥ 3 |
| `R01` | REJECT | Invalid record (non-numeric field or hh = 0) |

## 5. Report format

Each line is written from a fixed layout. **Trailing spaces are stripped** (GnuCOBOL line
sequential behavior), and lines end with `\n`.

### 5.1 Detail line (one per input record, in input order)
| Cols | Width | Content | Format |
|---|---|---|---|
| 1–8 | 8 | Applicant ID | As read, unchanged |
| 9 | 1 | Space | |
| 10–17 | 8 | Status | `ELIGIBLE`, `DENIED`, `REJECT`, left-justified and space-padded |
| 18 | 1 | Space | |
| 19–25 | 7 | Benefit | `ZZZ9.99`: leading zeros become spaces, always 2 decimals (`   0.00`, ` 290.00`, `1199.40`) |
| 26 | 1 | Space | |
| 27–30 | 4 | Reason | Code, left-justified. If the reason is blank, the line ends at col 25 |

Example (`.` = space):
```
A0000001.ELIGIBLE..290.00
A0000003.ELIGIBLE...23.00.M23
A0000009.REJECT......0.00.R01
```

⚠️ **Benefit overflow:** The display field holds at most 9999.99. Higher benefits lose their
leading digits, but the running total still uses the full amount. Verified: hh = 50 with
income 0 gives max_allot 10370.00. The detail line prints ` 370.00`, while the total adds
10370.00. This can happen whenever hh ≥ 49.

### 5.2 Summary (5 lines after all details)
| Label (cols 1–20, padded) | Value (cols 21–31, `ZZZZZZZ9.99`) |
|---|---|
| `RECORDS READ` | Count of all records |
| `ELIGIBLE` | Count of ELIGIBLE |
| `DENIED` | Count of DENIED (I01 + Z00) |
| `REJECTED` | Count of REJECT |
| `TOTAL BENEFITS` | Sum of benefits for ELIGIBLE records |

```
RECORDS READ              16.00
TOTAL BENEFITS          3393.22
```
- ⚠️ The counts are printed with `.00` because they share the money picture clause. This is a cosmetic bug, but parity requires it.
- `RECORDS READ = ELIGIBLE + DENIED + REJECTED` always holds.

## 6. Other ambiguities and latent issues ⚠️

1. **Counter overflow:** the counters are `9(5)` with no `ON SIZE ERROR`. Behavior above 99,999 records is untested and undefined for parity purposes. The total is `9(8)V99` and would overflow above 99,999,999.99.
2. **`WS-STATUS` is never reset** between records. Every current path sets it, so no stale value leaks today, but a future edit could expose this.
3. **No state validation:** any 2 characters are accepted, including blanks and lowercase.
4. **Age is not range-checked:** `000` and `999` are accepted, and age ≥ 60 gets the elderly add-on.
5. **Reason code meanings** are inferred only (see §4). There's no data dictionary in the source.
6. **Header comments** say this is a nutrition-assistance program. The constants (1580, 560, 290, 240, 198, 30%, $23) look like SNAP-style values but don't match any real fiscal year. Don't "update" them to current federal values.

## 7. Parity checklist for a reimplementation
- [ ] Use decimal arithmetic, never binary floats
- [ ] Truncate `net × 0.30` to cents, rounding toward zero
- [ ] Use inclusive `≤` comparisons against limit130 and limit200
- [ ] Handle the hh > 8 allotment step (+200, not +240)
- [ ] Apply veteran and elderly add-ons before the minimum logic
- [ ] Let M23 overwrite D20
- [ ] Parse fixed-width fields by byte offset, pad short lines, ignore extra bytes
- [ ] Use strict digit-only numeric validation (spaces and signs are rejected)
- [ ] Match case-sensitive `Y`, `AK`, `HI`
- [ ] Format `ZZZ9.99` with leading-digit truncation above 9999.99
- [ ] Strip trailing spaces, so lines with a blank reason end after the benefit
- [ ] Print summary counts with `.00`
