#!/usr/bin/env bash
set -euo pipefail
cd /home/log/lerobot_workbench
export PYTHONPATH=src
exec /home/log/miniforge3/envs/lerobot/bin/python scripts/start_workbench.py \
  --config config/workbench_config.xlerobot_so101.json \
  --host 0.0.0.0 \
  --port 8093
