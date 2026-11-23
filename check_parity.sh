#!/usr/bin/env bash
# Usage: ./check_parity.sh "<command>"   e.g. ./check_parity.sh "python3 bencalc.py"
# The command is run as: <command> <input-file>, and must print the report to stdout.
set -u
cd "$(dirname "$0")"
[ $# -ge 1 ] || { echo "usage: $0 \"<command>\""; exit 2; }
fail=0
for pair in "applicants:report" "holdout:holdout_report"; do
  data="legacy/data/${pair%%:*}.dat"; exp="legacy/expected/${pair##*:}.txt"
  if diff <(bash -c "$1 $data") "$exp" > /tmp/parity_diff.txt; then
    echo "PASS  $data"
  else
    echo "FAIL  $data  ($(grep -c '^[<>]' /tmp/parity_diff.txt) differing lines)"; head -20 /tmp/parity_diff.txt; fail=1
  fi
done
exit $fail
