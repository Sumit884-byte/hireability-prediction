#!/usr/bin/env bash
# Install a daily cron job for hireability data ingest.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${ROOT}/.venv/bin/python"
SCRIPT="${ROOT}/scripts/daily_ingest.py"
LOG="${ROOT}/data/cron.log"
CRON_LINE="30 6 * * * cd ${ROOT} && ${PYTHON} ${SCRIPT} >> ${LOG} 2>&1"

if [[ ! -x "${PYTHON}" ]]; then
  echo "Virtualenv not found. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

chmod +x "${SCRIPT}"

EXISTING="$(crontab -l 2>/dev/null || true)"
if echo "${EXISTING}" | grep -Fq "${SCRIPT}"; then
  echo "Cron entry already installed:"
  echo "${EXISTING}" | grep -F "${SCRIPT}"
  exit 0
fi

{
  echo "${EXISTING}"
  echo "# Hireability daily market ingest (06:30 UTC)"
  echo "${CRON_LINE}"
} | crontab -

echo "Installed daily cron:"
echo "  ${CRON_LINE}"
echo ""
echo "Logs: ${LOG} and ${ROOT}/data/daily_ingest.log"
echo "Dry-run check: ${PYTHON} ${SCRIPT} --dry-run"
