#!/bin/bash
# Daily Briefing Dashboard Refresh
# Collects data and generates HTML dashboard
set -euo pipefail
cd "$(dirname "$0")"

echo "[Daily Briefing] Starting refresh at $(date)"
python3 collect_briefing.py
python3 generate_briefing.py
echo "[Daily Briefing] Refresh complete. Dashboard at ~/.hermes/daily-briefing/index.html"
