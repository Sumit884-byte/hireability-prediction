#!/usr/bin/env bash
# Install login-based daily ingest (replaces cron if present).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${ROOT}/.venv/bin/python"
WRAPPER="${ROOT}/scripts/login_ingest.sh"
AUTOSTART_DIR="${HOME}/.config/autostart"
DESKTOP_FILE="${AUTOSTART_DIR}/hireability-ingest.desktop"

if [[ ! -x "${PYTHON}" ]]; then
  echo "Virtualenv not found. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

chmod +x "${ROOT}/scripts/daily_ingest.py" "${WRAPPER}"

# Remove cron entry if install_cron.sh was used earlier.
EXISTING="$(crontab -l 2>/dev/null || true)"
if echo "${EXISTING}" | grep -Fq "scripts/daily_ingest.py"; then
  echo "${EXISTING}" | grep -Fv "scripts/daily_ingest.py" | grep -Fv "# Hireability daily market ingest" | crontab - || true
  echo "Removed previous cron entry."
fi

mkdir -p "${AUTOSTART_DIR}"
cat > "${DESKTOP_FILE}" <<EOF
[Desktop Entry]
Type=Application
Name=Hireability Daily Ingest
Comment=Fetch market data once per day on login
Exec=${WRAPPER}
X-GNOME-Autostart-enabled=true
Hidden=false
NoDisplay=true
EOF

echo "Installed login autostart:"
echo "  ${DESKTOP_FILE}"
echo ""
echo "Runs once per login day (skips if already succeeded today)."
echo "Logs: ${ROOT}/data/login.log and ${ROOT}/data/daily_ingest.log"
echo "Manual run: ${PYTHON} ${ROOT}/scripts/daily_ingest.py"
echo "Dry-run:    ${PYTHON} ${ROOT}/scripts/daily_ingest.py --dry-run"
