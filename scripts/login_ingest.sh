#!/usr/bin/env bash
# Background ingest on login; runs at most once per day.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${ROOT}/.venv/bin/python"
SCRIPT="${ROOT}/scripts/daily_ingest.py"
LOG="${ROOT}/data/login.log"

mkdir -p "${ROOT}/data"
cd "${ROOT}"

if [[ ! -x "${PYTHON}" ]]; then
  echo "Hireability: virtualenv missing at ${PYTHON}" >> "${LOG}"
  exit 1
fi

nohup "${PYTHON}" "${SCRIPT}" --if-due >> "${LOG}" 2>&1 &
