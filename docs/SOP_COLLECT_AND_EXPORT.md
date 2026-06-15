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

## Export Accepted Episode Index

```bash
python ~/lerobot_workbench/scripts/export_accepted_episodes.py \
  --session-dir ~/lerobot_workbench/sessions/<session_id>
```

The data-closed-loop implementation will replace this with a success-only LeRobot v3 training package export.

