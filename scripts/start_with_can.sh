#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-0.0.0.0}"
PORT="${2:-8090}"
RESTART="${RESTART:-0}"

existing_pids="$(
  ps -eo pid=,cmd= | awk -v port="$PORT" '
    /start_workbench.py/ && $0 ~ ("--port " port) && $0 !~ /awk/ {print $1}
  '
)"

if [[ -n "$existing_pids" ]]; then
  if [[ "$RESTART" == "1" ]]; then
    echo "Existing LeRobot workbench found on port ${PORT}: ${existing_pids}"
    echo "RESTART=1 set; stopping existing workbench first."
    kill -TERM $existing_pids 2>/dev/null || true
    sleep 3
    for pid in $existing_pids; do
      if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null || true
      fi
    done
  else
    echo "LeRobot workbench is already running on port ${PORT}: ${existing_pids}"
    echo "Open: http://$(hostname -I | awk '{print $1}'):${PORT}"
    echo "To restart it from this script, run:"
    echo "  RESTART=1 $0 ${HOST} ${PORT}"
    exit 0
  fi
fi

source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate lerobot

echo "[1/3] Setting up CAN interfaces can0,can1"
echo "      This may ask for the robot account sudo password."
lerobot-setup-can --mode=setup --interfaces=can0,can1

echo "[2/3] Checking CAN state"
ip -details link show can0 | sed -n '1,8p'
ip -details link show can1 | sed -n '1,8p'

echo "[3/3] Starting LeRobot workbench on ${HOST}:${PORT}"
python "$HOME/lerobot_workbench/scripts/start_workbench.py" --host "$HOST" --port "$PORT"
