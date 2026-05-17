#!/usr/bin/env bash
# DQT pipeline quality gate — minimal CI/shell example.
#
# Usage:
#   ./run_gate.sh [threshold]
#
# threshold: float 0.0–1.0 (default: 0.9)
# Exit 2 if the dataset scores below the threshold.
# Exit 0 if the dataset meets the threshold.

set -euo pipefail

THRESHOLD="${1:-0.9}"
CSV="sample_pipeline_output.csv"

echo "DQT quality gate: ${CSV} | threshold: ${THRESHOLD}"

set +e
dqt assess "${CSV}" --fail-under "${THRESHOLD}"
GATE_EXIT=$?
set -e

if [ "${GATE_EXIT}" -eq 2 ]; then
    echo "GATE FAILED: quality score below ${THRESHOLD}. Halting pipeline."
    exit 2
elif [ "${GATE_EXIT}" -ne 0 ]; then
    echo "ERROR: dqt assess returned unexpected exit code ${GATE_EXIT}."
    exit "${GATE_EXIT}"
fi

echo "GATE PASSED: dataset meets quality threshold ${THRESHOLD}."
