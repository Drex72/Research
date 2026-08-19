#!/usr/bin/env bash
#
# Scenario 13, clause granularity, English + Korean, whole dataset.
#
#   24 cases / 42 turns, no limit
#   --max-dominance 0.7, --retries 2
#
# Safe to re-run: --resume reads the .index.jsonl sidecar and skips turns
# already written, so an interrupted run picks up where it stopped.
#
#   bash scripts/run_scn13.sh
#
set -uo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

mkdir -p runs/logs
LOG="runs/logs/scn13-clause.log"

echo "scenario 13 | clause | English+Korean | 42 turns"
echo "log: $LOG"
echo

"$PY" scripts/make_codeswitch_csv.py \
    --scenario 13 \
    --languages English Korean \
    --granularity clause \
    --max-dominance 0.7 \
    --retries 2 \
    --resume \
    --log-file "runs/logs/scn13-clause.debug.log" \
    2>&1 | tee "$LOG"

status=${PIPESTATUS[0]}
echo
echo "exit status: $status"
exit "$status"
