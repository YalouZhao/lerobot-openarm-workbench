# Roadmap

## Baseline

This repository starts from the stable deployed workbench baseline:

- Web camera streams.
- Start / Stop episode recording.
- Success / failure / discard labels.
- Session sidecar `episodes.jsonl`.
- Basic accepted episode export helper.
- OpenArm ready path helper.

## P0: Data Closure

1. Add dataset-root canonical manifest files:
   - `dataset_manifest.json`
   - dataset-root `episodes.jsonl`
   - `accepted_episodes.json`
   - `manifest_transactions.jsonl`
   - `export_reports/`
2. Make dataset task text mandatory at dataset creation.
3. Lock task text once a dataset has episodes.
4. Make existing datasets read-only until explicitly unlocked.
5. Enforce label-before-next-start after `Stop Episode`.
6. Replace direct manifest rewrites with lock + temp file + fsync + `os.replace`.
7. Write labels to dataset-root canonical manifest and mirror them to the session manifest.
8. Keep stop-after-save discard as `label=discard, accepted=false`; do not physically delete LeRobot episodes.
9. Implement export precheck with fatal/warning categories.
10. Export success-only training package by rebuilding a new LeRobot v3 dataset through LeRobot APIs.

## P1: Operations

1. Add dataset health UI.
2. Add recheck and resync manifest operations.
3. Preserve failed exports under `exports/failed/` with failure reports.
4. Add hardware/schema details to `dataset_manifest.json`.
5. Add `/api/version` and `/api/health`.
6. Add deployment notes and optional systemd service.
7. Expand tests for manifest recovery, export mapping, and unsafe states.

## P2: Later

1. Separate task-result label from training `accepted`.
2. Add failure/discard reason taxonomy.
3. Add raw archive export.
4. Add index-only export.
5. Add legacy dataset migration wizard.
6. Add complete event audit log.

