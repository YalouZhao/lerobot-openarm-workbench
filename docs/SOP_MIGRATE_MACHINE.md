# SOP: Migrate Workbench To Another Machine

The workbench is not just a web app. It is bound to the local collection host because cameras, CAN interfaces, teleop serial ports, LeRobot recording, and dataset writes all happen locally.

## What Must Be Prepared

- Ubuntu/Linux host with the same OpenArm and LeRobot-compatible environment.
- Working CAN interfaces, normally `can0` and `can1`.
- OpenArm mini serial devices, normally `/dev/ttyACM0` and `/dev/ttyACM1`.
- Three camera paths under `/dev/v4l/by-path/` or `/dev/v4l/by-id/`.
- Writable dataset root, usually `/home/robot/data`.
- A local `config/workbench_config.json` copied from `config/workbench_config.example.json`.

## Checks

```bash
ip -details link show can0
ip -details link show can1
ls -l /dev/ttyACM*
ls -l /dev/v4l/by-path/
ls -l /dev/v4l/by-id/
```

Probe devices:

```bash
python ~/lerobot_workbench/scripts/probe_devices.py
```

Run tests:

```bash
cd ~/lerobot_workbench
pytest -q
```

## Migration Steps

1. Clone the repository.
2. Copy `config/workbench_config.example.json` to `config/workbench_config.json`.
3. Update dataset root, CAN ports, teleop serial ports, and camera paths.
4. Copy any required local ready path to `config/ready_path.json`.
5. Start with `scripts/start_with_can.sh`.
6. Verify camera streams in browser.
7. Run a short episode only after hardware safety is confirmed.

Do not migrate runtime `sessions/`, `logs/`, or `data/` through git. Use `rsync` or a dedicated dataset export package.

