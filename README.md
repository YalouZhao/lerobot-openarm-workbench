# LeRobot OpenArm Workbench

Internal data collection workbench for a bimanual OpenArm follower setup using LeRobot v3 datasets and three RGB camera streams.

This repository is the first stable baseline of the collection workbench that has been running on the robot collection host. It intentionally tracks source code, tests, scripts, and configuration templates only. Runtime datasets, sessions, logs, private machine configuration, model weights, and tokens are excluded from git.

## Current Capabilities

- Web UI for live camera viewing.
- Start / Stop episode collection.
- Mark episode as success, failure, or discard.
- Session-level `episodes.jsonl` sidecar manifest.
- Accepted episode export helper.
- OpenArm bimanual follower and OpenArm mini teleoperation configuration.
- Ready pose/path helper for moving to a known safe workspace pose.

## Runtime Layout

Default deployment paths on the collection machine:

```text
/home/robot/lerobot_workbench
/home/robot/lerobot_workbench/config/workbench_config.json
/home/robot/lerobot_workbench/sessions/
/home/robot/data/<dataset_name>/
```

The browser UI is only a remote client. Cameras, CAN, teleop serial devices, LeRobot recording, and dataset writes all happen on the collection host.

## First-Time Deployment

```bash
git clone git@github.com:YalouZhao/lerobot-openarm-workbench.git ~/lerobot_workbench
cd ~/lerobot_workbench
cp config/workbench_config.example.json config/workbench_config.json
```

Edit `config/workbench_config.json` for the local machine:

- `dataset.root`
- `robot.left_arm.port`
- `robot.right_arm.port`
- `teleop.port_left`
- `teleop.port_right`
- camera `index_or_path` entries
- `control.default_task`

Start the workbench:

```bash
~/lerobot_workbench/scripts/start_with_can.sh
```

Then open:

```text
http://<collection-host-ip>:8090
```

## Safety Notes

- `scripts/start_with_can.sh` configures `can0` and `can1`.
- `scripts/move_to_ready.py --execute --yes` sends robot actions. Use `--dry-run` first.
- Do not commit real `config/workbench_config.json`, session files, dataset files, exports, or tokens.

## Data Closure Roadmap

The current baseline stores labels in the session sidecar. The next engineering milestone is dataset-root canonical metadata:

- `dataset_manifest.json`
- dataset-root `episodes.jsonl`
- `accepted_episodes.json`
- `manifest_transactions.jsonl`
- `export_reports/`

See [docs/DATA_CLOSED_LOOP_DESIGN.md](docs/DATA_CLOSED_LOOP_DESIGN.md).

