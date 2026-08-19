#!/usr/bin/env bash
#
# Scenarios 00 through 10, English + Korean, one CSV per scenario.
#
#   --max-dominance 0.7 and --retries 2 throughout
#   granularity varies by scenario, per the PLAN below
#   606 turns in total
#
# Each scenario runs to completion before the next starts, and a scenario
# that fails does not stop the ones after it. Everything is logged per
# scenario under runs/logs/, and --resume makes the whole thing restartable:
# run it again and it skips what already landed.
#
#   bash scripts/run_scn00_10.sh
#
# To run only some of them:
#
#   bash scripts/run_scn00_10.sh 03 04 05
#
set -uo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

# scenario:granularity — edit freely.
#
# Two of the six granularities are deliberately absent:
#
#   word          at English+Korean it passed 0 of 7 turns in the last run.
#                 The one-lexical-word-per-segment rule and the naturalness
#                 reviewer cannot both be satisfied when the two languages
#                 have opposite word order, so it burns the most tokens per
#                 turn of any level and returns nothing.
#   semantic_role needs --roles mapping each role to a language, which is a
#                 design choice rather than a default.
#
# That leaves four levels across eleven scenarios, so they cycle. Scenario
# and granularity are confounded by construction here: a difference between
# two scenarios in this sweep cannot be attributed to either one alone.
PLAN=(
    "04:clause"
    "05:phrase"
    "06:sentence"
    "07:tag"
    "08:clause"
    "09:phrase"
    "10:sentence"
)

# tag granularity needs its own settings. The tag instruction says to write
# the whole request in the matrix language and insert short borrowed tags, so
# English dominates by construction and a 50/50 target with a 0.7 ceiling can
# never pass.
#
# These numbers are measured, not guessed. Across 38 tag mixtures the English
# share ran 91-98%, median 94. A 0.95 ceiling would still reject 32% of them;
# 0.98 clears all 38. Seven turns also failed "too little Korean evidence
# (1 < 2)" because a short turn only has room for one tag, so min_hits drops
# to 1 here.
extra_flags() {
    case "$1" in
        tag) echo "--dominance English=0.93 Korean=0.07 --max-dominance 0.98 --min-hits 1" ;;
        *)   echo "--max-dominance 0.7" ;;
    esac
}

WANTED=("$@")

want() {
    [ ${#WANTED[@]} -eq 0 ] && return 0
    local target="$1" each
    for each in "${WANTED[@]}"; do
        [ "$each" = "$target" ] && return 0
    done
    return 1
}

mkdir -p runs/logs
started=$(date +%s)
declare -a REPORT=()

# Ctrl-C must end the sweep, not just the scenario in front of it. Without
# this, interrupting scenario 03 hands control straight back to the loop, which
# launches 04, and you have to interrupt once per remaining scenario.
interrupted=0
trap 'interrupted=1' INT

for entry in "${PLAN[@]}"; do
    scenario="${entry%%:*}"
    granularity="${entry##*:}"
    want "$scenario" || continue

    log="runs/logs/scn${scenario}-${granularity}.log"

    echo
    echo "================================================================"
    echo "scenario $scenario | $granularity | English+Korean"
    echo "log: $log"
    echo "================================================================"

    # shellcheck disable=SC2046  # word splitting is what carries the flags
    "$PY" scripts/make_codeswitch_csv.py \
        --scenario "$scenario" \
        --languages English Korean \
        --granularity "$granularity" \
        $(extra_flags "$granularity") \
        --retries 2 \
        --resume \
        --log-file "runs/logs/scn${scenario}-${granularity}.debug.log" \
        2>&1 | tee "$log"

    REPORT+=("${scenario}:${granularity}:${PIPESTATUS[0]}")

    if [ "$interrupted" -eq 1 ]; then
        echo
        echo "interrupted — stopping the sweep. Re-run the same command to"
        echo "continue; --resume skips everything already written."
        break
    fi
done

echo
echo "================================================================"
echo "summary"
echo "================================================================"
printf "%-5s %-10s %-7s %7s %9s  %s\n" scn granularity status rows cost file

for line in "${REPORT[@]}"; do
    IFS=: read -r scenario granularity status <<<"$line"
    csv="runs/codeswitch-scn${scenario}-EN-KO-${granularity}.csv"
    # Counted by the CSV reader, not by wc -l. A code-switched prompt can
    # contain newlines, so a quoted field spans several physical lines and
    # wc reports roughly three times the real number.
    read -r rows cost <<<"$("$PY" - "$csv" <<'EOF'
import csv, json, os, sys
path = sys.argv[1]
if not os.path.exists(path):
    print("- -"); raise SystemExit
with open(path, encoding="utf-8", newline="") as handle:
    rows = sum(1 for _ in csv.DictReader(handle))
usage = path.replace(".csv", ".usage.json")
cost = "-"
if os.path.exists(usage):
    cost = "$%.2f" % json.load(open(usage)).get("estimated_cost", 0)
print(rows, cost)
EOF
)"
    printf "%-5s %-10s %-7s %7s %9s  %s\n" \
        "$scenario" "$granularity" "$status" "$rows" "$cost" "$(basename "$csv")"
done

echo
printf "elapsed: %s\n" "$(printf '%dh%02dm' $(( ($(date +%s) - started) / 3600 )) $(( (($(date +%s) - started) % 3600) / 60 )))"
