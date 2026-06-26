# SOP: Collect And Export

## Start Workbench

```bash
cd ~/lerobot_workbench
~/lerobot_workbench/scripts/start_with_can.sh
```

Open:

```text
http://<collection-host-ip>:8090
```

## Create Or Switch Dataset

Current baseline uses:

```bash
python ~/lerobot_workbench/scripts/new_collection_dataset.py \
  --name <dataset_name>
```

Then restart the workbench if it is already running.

## Episode Flow

1. Confirm three camera streams are healthy.
2. Confirm OpenArm follower and OpenArm mini are connected.
3. Click `Start Episode`.
4. Teleoperate the robot.
5. Click `Stop Episode`.
6. Immediately label the episode:
   - `Mark Success`
   - `Mark Failure`
   - `Discard Episode`

Current baseline stores labels in the active session sidecar. Do not upload only `data/`, `meta/`, and `videos/` if labels are needed on another machine.

## Export Training Package

Use the full training-package exporter for data that will enter training:

```bash
python ~/lerobot_workbench/scripts/export_training_package.py \
  --source-root /path/to/collection_dataset \
  --source-repo-id local/source_collection \
  --output-root /path/to/exported_training_dataset \
  --output-repo-id local/exported_training_dataset \
  --config-file ~/lerobot_workbench/config/workbench_config.phase1-hardware-test.json
```

The exporter:

1. never modifies the source collection dataset;
2. exports only `label=success`, `accepted=true`, `dq_status=pass`, and non-contaminated episodes;
3. rewrites exported episode indexes to a contiguous `0..N-1` range;
4. regenerates LeRobot metadata and stats for the exported training root;
5. writes `dataset_action_contract.json`, `export_report.json`, and `export_provenance.json`;
6. validates that the output root can be loaded by `LeRobotDataset`.

Before writing a package, preview the selection:

```bash
python ~/lerobot_workbench/scripts/export_training_package.py \
  --source-root /path/to/collection_dataset \
  --source-repo-id local/source_collection \
  --output-root /path/to/exported_training_dataset \
  --output-repo-id local/exported_training_dataset \
  --dry-run
```

`dataset_action_contract.json` describes only the action semantics of the exported training dataset:

```text
action = follower_effective_command
```

It does not describe any external policy runtime or robot execution chain.

## Export Accepted Episode Index

```bash
python ~/lerobot_workbench/scripts/export_accepted_episodes.py \
  --dataset-root /path/to/collection_dataset
```

This index-only export is retained for diagnostics and quick inspection. Use the full training-package export for training data.
