# Implementation Schedule

This schedule breaks the data-closed-loop workbench into small releases. Each release must be implemented, tested by Codex, manually tested by the operator, and only then pushed to GitHub.

## Release Rules

For every release:

1. Create a local feature branch from `main`.
2. Implement only the release scope below.
3. Run automated tests locally.
4. Run a local smoke test when the change touches the HTTP API or UI.
5. Stop and hand the build to the operator for manual testing on the collection host.
6. Push to GitHub only after manual acceptance.
7. Tag important stable points as `v0.x.y`.

Recommended branch format:

```bash
git checkout main
git pull --ff-only
git checkout -b feature/p0-<short-name>
```

Recommended pre-push gate:

```bash
python -m pytest -q
git status --short
```

Manual acceptance is required before:

```bash
git push origin feature/p0-<short-name>
```

## P0-A: Canonical Manifest Core

Goal: make dataset-root metadata the canonical source of training labels, while keeping the existing session manifest as a mirror.

Scope:

- Add dataset-root files:
  - `dataset_manifest.json`
  - `episodes.jsonl`
  - `accepted_episodes.json`
  - `manifest_transactions.jsonl`
  - `export_reports/`
- Add atomic JSON/JSONL write helpers using temp file, fsync, and `os.replace`.
- Add `.manifest.lock` locking around manifest updates.
- Add label rules:
  - `success -> accepted=true`
  - `failure -> accepted=false`
  - `discard -> accepted=false`
  - `unlabeled -> accepted=false`
- Keep existing recording behavior: after `Stop Episode`, LeRobot data is already saved; discard after stop only marks manifest state and does not physically delete data.

Likely files:

- `src/workbench/dataset_manifest.py`
- `src/workbench/episode_manifest.py`
- `src/workbench/controller.py`
- `tests/test_dataset_manifest.py`
- `tests/test_controller_episode_finalize.py`

Codex automated tests:

```bash
python -m pytest -q
```

Extra required tests:

- Appending an unlabeled episode writes dataset root `episodes.jsonl`.
- Updating success/failure/discard rewrites dataset root manifest and session mirror.
- `accepted_episodes.json` is regenerated from dataset root `episodes.jsonl`.
- Atomic write failure does not leave an empty manifest file.

Operator manual test:

1. Start the existing workbench on the robot host.
2. Create or select a test dataset.
3. Record one short episode.
4. Stop it.
5. Mark it success.
6. Confirm these files exist under the dataset root:
   - `dataset_manifest.json`
   - `episodes.jsonl`
   - `accepted_episodes.json`
   - `manifest_transactions.jsonl`
7. Confirm the session `episodes.jsonl` mirrors the same label.

GitHub action after acceptance:

```bash
git push origin feature/p0-canonical-manifest
```

## P0-B: Dataset Creation, Task Text, Read-Only Switch

Goal: prevent task-text drift and accidental appending to old datasets.

Scope:

- Dataset creation requires:
  - base dataset name
  - dataset-level task text
- Dataset directory name becomes:
  - `<base_name>__<YYYYMMDD_HHMMSS>`
- Task text is locked once the dataset has episodes.
- Switching to an existing dataset defaults to read-only.
- User must explicitly unlock to continue collection.
- Unlock state persists across page refresh and backend restart for the currently active dataset.
- Switching to another dataset locks again.

Likely files:

- `scripts/new_collection_dataset.py`
- `src/workbench/config.py`
- `src/workbench/controller.py`
- `src/workbench/server.py`
- `src/workbench/web_assets.py`
- `tests/test_new_collection_dataset.py`
- `tests/test_dataset_locking.py`

Codex automated tests:

```bash
python -m pytest -q
```

Extra required tests:

- Empty task text is rejected.
- Dataset name gets timestamp suffix.
- Existing dataset starts read-only.
- Unlock survives controller reload.
- Dataset with existing episodes cannot edit task text in place.

Operator manual test:

1. Create a new dataset from the web UI with task text.
2. Refresh browser and confirm task text remains.
3. Record and stop one episode.
4. Confirm task text can no longer be edited in place.
5. Switch to the same dataset and confirm it is read-only.
6. Click unlock and confirm Start Episode becomes available.
7. Restart backend and confirm the unlocked state is preserved.

GitHub action after acceptance:

```bash
git push origin feature/p0-dataset-task-lock
```

## P0-C: Label-Before-Next-Start Enforcement

Goal: prevent unlabeled episodes from silently entering the dataset.

Scope:

- After `Stop Episode`, state becomes `unlabeled`.
- Start Episode is disabled until the last saved episode is marked success, failure, or discard.
- API rejects start requests if the last saved episode is unlabeled.
- UI makes the required label action obvious.
- Recording-time discard remains available for unsaved buffers.
- Stop-time discard becomes "mark last episode as discard".

Likely files:

- `src/workbench/controller.py`
- `src/workbench/server.py`
- `src/workbench/web_assets.py`
- `tests/test_label_gate.py`

Codex automated tests:

```bash
python -m pytest -q
```

Extra required tests:

- Start after stop without label raises a clear error.
- Start after success is allowed.
- Start after failure is allowed.
- Start after discard is allowed.
- Recording-time discard does not create a dataset-root episode record.

Operator manual test:

1. Start and stop an episode.
2. Confirm Start Episode is disabled.
3. Try Start through UI and confirm it is blocked.
4. Mark failure.
5. Confirm Start Episode is enabled again.
6. Repeat once with stop-time discard.

GitHub action after acceptance:

```bash
git push origin feature/p0-label-gate
```

## P0-D: Export Precheck

Goal: block bad training packages before copying or packaging data.

Scope:

- Add full precheck command and API.
- Fatal errors block export.
- Warnings are recorded but do not block export.
- Precheck uses dataset-root manifest as canonical.
- Precheck validates:
  - required manifest files
  - no unlabeled episodes
  - at least one accepted success episode
  - accepted file matches `episodes.jsonl`
  - LeRobot dataset can load
  - required camera keys exist
  - accepted success episodes map to LeRobot episodes
  - expected videos exist
  - export target is not already occupied
  - sufficient disk space

Likely files:

- `src/workbench/export_precheck.py`
- `src/workbench/server.py`
- `src/workbench/web_assets.py`
- `tests/test_export_precheck.py`

Codex automated tests:

```bash
python -m pytest -q
```

Extra required tests:

- Missing manifest is fatal.
- Unlabeled episode is fatal.
- Zero success episodes is fatal.
- Failure/discard episodes are warnings.
- Stale `accepted_episodes.json` is fatal.

Operator manual test:

1. Run precheck on a dataset with one success episode.
2. Confirm it passes.
3. Add or leave an unlabeled episode.
4. Confirm export is blocked with a clear fatal message.
5. Mark it failure.
6. Confirm failure becomes warning, not fatal.

GitHub action after acceptance:

```bash
git push origin feature/p0-export-precheck
```

## P0-E: Success-Only Train Package Export

Goal: produce a training-ready package that contains only accepted success episodes and carries its own manifest/report/checksum.

Scope:

- Add export operation:
  - source dataset root
  - output tar.gz under `/home/robot/data/exports/`
  - failed partials under `/home/robot/data/exports/failed/`
- Rebuild a success-only LeRobot v3 dataset through LeRobot APIs where available.
- Generate package files:
  - `data/`
  - `meta/`
  - `videos/`
  - `dataset_manifest.json`
  - `episodes.jsonl`
  - `accepted_episodes.json`
  - `export_reports/export_<timestamp>.json`
  - `CHECKSUMS.txt`
- Record source-to-export episode index mapping.

Likely files:

- `scripts/export_success_train_package.py`
- `src/workbench/export_package.py`
- `src/workbench/server.py`
- `src/workbench/web_assets.py`
- `tests/test_export_package.py`

Codex automated tests:

```bash
python -m pytest -q
```

Extra required tests:

- Only success and accepted episodes are exported.
- Failure/discard episodes are excluded.
- Exported `episodes.jsonl` uses remapped episode indexes.
- Export report records source counts and mapping.
- Failed export preserves partial output under `exports/failed/`.

Operator manual test:

1. Collect three episodes: success, failure, discard.
2. Export success training package.
3. Extract tar.gz to a temporary path.
4. Confirm only one episode is present.
5. Confirm report maps source episode index to export episode index.
6. Confirm the package can be copied to the training machine and loaded.

GitHub action after acceptance:

```bash
git push origin feature/p0-success-export
```

## P1-A: Dataset Health, Recheck, Resync

Goal: expose manifest health and controlled repair operations in the web UI.

Scope:

- Add health state:
  - healthy
  - warning
  - unsafe
  - exporting
- Add Recheck Dataset.
- Add Resync Manifest.
- Show diff before repair.
- Repair direction is explicit:
  - dataset root canonical -> session mirror
- Unsafe state disables collection and export.

Likely files:

- `src/workbench/manifest_health.py`
- `src/workbench/server.py`
- `src/workbench/web_assets.py`
- `tests/test_manifest_health.py`

Codex automated tests:

```bash
python -m pytest -q
```

Operator manual test:

1. Manually remove or corrupt the session mirror in a test dataset.
2. Run Recheck Dataset.
3. Confirm UI shows the diff.
4. Run Resync Manifest.
5. Confirm session mirror is repaired from dataset root.

GitHub action after acceptance:

```bash
git push origin feature/p1-health-resync
```

## P1-B: Hardware and Schema Manifest Details

Goal: make every dataset self-describing enough to move to another computer and diagnose hardware changes.

Scope:

- Record robot setup:
  - OpenArm dual-arm follower
  - OpenArm mini teleop
- Record required schema:
  - `observation.images.main`
  - `observation.images.wrist_left`
  - `observation.images.wrist_right`
  - `observation.state`
  - `action`
- Record configured camera paths, size, fps, fourcc.
- Record non-fatal resolved hardware details when available:
  - `/dev/videoX`
  - `/dev/v4l/by-path`
  - `/dev/v4l/by-id`
  - vendor/product
  - serial
  - measured fps
- Add `/api/version` and `/api/health`.

Likely files:

- `src/workbench/device_probe.py`
- `src/workbench/dataset_manifest.py`
- `src/workbench/server.py`
- `tests/test_hardware_manifest.py`

Codex automated tests:

```bash
python -m pytest -q
```

Operator manual test:

1. Start the workbench with all cameras connected.
2. Create a dataset.
3. Confirm `dataset_manifest.json` contains configured and resolved camera info.
4. Move one camera to a different `/dev/videoX`.
5. Confirm this is warning-level unless the required camera role is missing.

GitHub action after acceptance:

```bash
git push origin feature/p1-hardware-schema
```

## P1-C: Deployment and Migration Hardening

Goal: make the workbench reproducible on another collection computer.

Scope:

- Add deployment SOP:
  - clone repo
  - create Python environment
  - install LeRobot/OpenArm dependencies
  - copy example config
  - set camera paths and CAN ports
  - run device probe
  - run dry-run collection smoke test
- Add optional systemd service template.
- Add backup/restore instructions for dataset roots and session mirrors.
- Add "machine-bound values" checklist.

Likely files:

- `docs/SOP_MIGRATE_MACHINE.md`
- `docs/SOP_DEPLOY_COLLECTION_HOST.md`
- `deploy/lerobot-openarm-workbench.service`
- `scripts/probe_devices.py`

Codex automated tests:

```bash
python -m pytest -q
```

Operator manual test:

1. Follow the deployment SOP on a non-production path.
2. Run device probe.
3. Start the web server.
4. Confirm web UI loads and reports hardware readiness.

GitHub action after acceptance:

```bash
git push origin feature/p1-deploy-migration
```

## P2: Later Iterations

These are intentionally deferred until the P0/P1 loop is stable:

- Independent quality-control `accepted` toggle.
- Failure/discard reason taxonomy.
- Raw archive export.
- Index-only export.
- Legacy dataset migration wizard.
- Full event audit log.

## Recommended Calendar

The calendar assumes one implementation session plus one operator manual-test window per release.

| Order | Release | Estimated build time | Manual test time | Merge target |
| --- | --- | ---: | ---: | --- |
| 1 | P0-A Canonical Manifest Core | 0.5-1 day | 30-60 min | `main` |
| 2 | P0-B Dataset Creation and Task Lock | 0.5-1 day | 30-60 min | `main` |
| 3 | P0-C Label Gate | 0.5 day | 20-40 min | `main` |
| 4 | P0-D Export Precheck | 0.5-1 day | 30-60 min | `main` |
| 5 | P0-E Success Export | 1-1.5 days | 60-90 min | `main` |
| 6 | P1-A Health and Resync | 1 day | 45-75 min | `main` |
| 7 | P1-B Hardware and Schema Manifest | 0.5-1 day | 30-60 min | `main` |
| 8 | P1-C Deployment and Migration | 0.5 day | 30-60 min | `main` |

## Release Tagging

Suggested tags:

- `v0.2.0`: after P0-A through P0-C.
- `v0.3.0`: after P0-D and P0-E.
- `v0.4.0`: after P1-A through P1-C.

## Current Machine-Binding Answer

The current workbench is partially machine-bound. The source code is portable, but the deployed runtime depends on host-specific values:

- Python/LeRobot/OpenArm environment.
- CAN interfaces, usually `can0` and `can1`.
- Teleop serial ports, usually `/dev/ttyACM*`.
- Camera device paths under `/dev/v4l/by-path` or `/dev/v4l/by-id`.
- Dataset root, session root, and workspace root.
- Local permissions for video, dialout, plugdev, and CAN access.
- Any service files or shell wrappers used to start the workbench.

To migrate to another collection computer, prepare:

1. Clone this repository.
2. Install the same LeRobot/OpenArm-capable environment.
3. Copy `config/workbench_config.example.json` to a local ignored config file.
4. Run `scripts/probe_devices.py`.
5. Update camera, CAN, teleop, dataset, session, and workspace paths.
6. Start the workbench in a dry-run or non-recording smoke mode first.
7. Record one short test episode into a throwaway dataset.
8. Export a success package and confirm it loads on the training machine.

