# Data Closed Loop Design

## Baseline State

The current stable workbench records LeRobot v3 episodes to the configured dataset root and writes labels to a session sidecar:

```text
/home/robot/lerobot_workbench/sessions/<session_id>/episodes.jsonl
```

After `Stop Episode`, the episode is already committed through LeRobot `save_episode()`. A later `Discard Episode` marks the session sidecar record as:

```text
label=discard
accepted=false
```

It does not physically delete files from LeRobot `data/`, `meta/`, or `videos/`.

## Target Direction

The dataset root should become the canonical source of training semantics. Session files should become mirrors only.

Each closed-loop dataset root should contain:

```text
data/
meta/
videos/
dataset_manifest.json
episodes.jsonl
accepted_episodes.json
manifest_transactions.jsonl
export_reports/
```

Canonical rules:

- Dataset-root `episodes.jsonl` is authoritative.
- Session `episodes.jsonl` is a mirror.
- `accepted_episodes.json` is derived from dataset-root `episodes.jsonl`.
- Success-only training packages must not depend on session files.
- Stop-time discard after save is a manifest label, not physical deletion.

## Label Rules

```text
label=success   -> accepted=true
label=failure   -> accepted=false
label=discard   -> accepted=false
label=unlabeled -> accepted=false
```

The first production implementation should keep `accepted` derived from `label`. A future quality-control pass may separate task result labels from training acceptance.

## Export Rule

The default training export includes only:

```text
label == "success" AND accepted == true
```

The recommended implementation is to rebuild a new LeRobot v3 dataset through LeRobot APIs rather than manually copying parquet/video chunks. Manual copying risks corrupting episode indexes, task indexes, stats, and video references.

