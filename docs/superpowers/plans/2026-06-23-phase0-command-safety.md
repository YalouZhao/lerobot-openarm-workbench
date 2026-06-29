# Phase 0 Command Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or `executing-plans` to execute this plan task by task. The project owner's stage gates and no-commit rule override any generic workflow defaults.

**Goal:** Make every v2 training action equal to one immutable follower-space command produced after calibrated mapping and all phase-0 safety clamps, while failing closed for missing calibration and persistent driver mismatch.

**Architecture:** First apply a versioned `OpenArmMiniCompatibilityMapper` as teleop normalization, reproducing upstream commit `818892a3` exactly once. Absolute/relative teleop mapping follows, then a separate pure `CommandSafetyProcessor` owns deadband, soft-limit, max-step, and hard-limit processing. The resulting immutable `CommandFrame.effective_command` is copied to the driver and dataset writer, while `send_result` is validation-only. Calibration readiness and contamination are canonical manifest/export gates.

**Tech Stack:** Python 3.12, dataclasses, pytest, LeRobot 0.4 compatibility layer, JSON configuration and manifests.

---

## File map

- Create `src/workbench/command_safety.py`: validated safety configuration, pure mapping/clamp processor, bounded safety events.
- Create `src/workbench/openarm_mini_compat.py`: gripper conversion, joint 6/7 remap, right joint 7 correction, native-mapping detection, and LeRobot revision reporting; no safety clamps.
- Modify `src/workbench/command.py`: construct a frame only from explicit stage outputs; retain immutable mappings.
- Modify `src/workbench/config.py`: parse per-side calibration, joint limits, mismatch tolerance, and persistence threshold.
- Modify `src/workbench/controller.py`: single command path, one effective-command snapshot, mismatch persistence, episode contamination.
- Modify `src/workbench/episode_manifest.py`: contamination fields and fail-closed acceptance.
- Modify `src/workbench/dataset_manifest.py`: canonical contamination/calibration metadata and accepted-list rebuilding.
- Modify `scripts/export_accepted_episodes.py`: reject uncalibrated or contaminated episodes.
- Create `scripts/calibrate_gripper_mapping.py`: read-only endpoint capture and dry-run mapping; sending remains disabled unless a later hardware acceptance step explicitly enables it.
- Create `scripts/quarantine_episodes.py`: metadata-only quarantine for episodes 0 and 1; never rewrite Parquet or MP4.
- Create `tests/test_command_safety.py`: pure safety-order and validation tests.
- Modify `tests/test_command_semantics.py`: shared command snapshot provenance tests.
- Modify `tests/test_controller_episode_finalize.py`: mismatch contamination and acceptance tests.
- Modify `tests/test_export_schema_gate.py`: calibration/contamination export gates.
- Create `tests/test_quarantine_episodes.py`: metadata-only quarantine tests.

## Task 0: Restore versioned OpenArm Mini compatibility normalization

- [x] Add failing tests for gripper endpoints, joint 6/7 remap, right joint 7 correction, driver/dataset effective-command provenance, metadata, and double-application rejection.
- [x] Implement `openarm_mini_818892a3` mapping before the default teleop/robot processor chain.
- [x] Add explicit `apply_openarm_mini_compat_mapping`, `compat_mapping_version`, and `compat_mapping_verified` configuration.
- [x] Record LeRobot revision and compatibility metadata in dataset/episode manifests.
- [x] Mark unverified trial episodes contaminated and reject acceptance/export.
- [x] Verify `85 passed` and compileall. Ruff remains unavailable in the `lerobot04` environment.
- [ ] Complete owner hardware acceptance before any commit.

## Task 1: Freeze calibration and safety configuration

- [ ] Add failing tests proving v2 production recording rejects absent per-side gripper calibration.
- [ ] Add failing tests for equal/non-finite master endpoints, non-finite follower endpoints, inverted soft bounds, non-positive max step, and missing hard limits.
- [ ] Verify RED:

```bash
pytest -q tests/test_config_semantics.py tests/test_command_safety.py
```

Expected: failures because command-safety configuration does not yet exist.

- [ ] Add immutable configuration types equivalent to:

```python
@dataclass(frozen=True)
class GripperMapping:
    master_min: float
    master_max: float
    follower_open: float
    follower_close: float
    reversed: bool
    deadband: float
    soft_min: float
    soft_max: float
    max_step: float

@dataclass(frozen=True)
class CommandSafetySettings:
    grippers: Mapping[str, GripperMapping]
    hard_limits: Mapping[str, tuple[float, float]]
    mismatch_atol: float
    mismatch_persistence_frames: int
```

- [ ] Parse values from machine-local JSON only. Example configuration may use explicit `null` endpoint values and must therefore remain non-production-ready.
- [ ] Verify GREEN with the focused tests and the full suite.
- [ ] Stop and report; do not commit without owner acceptance.

## Task 2: Implement the pure command safety processor

- [ ] Write failing table-driven tests for left/right endpoint mapping, reversed direction, midpoint interpolation, endpoint clamp, deadband, soft-limit, max-step relative to follower qpos, hard clamp, complete key set, and finite output.
- [ ] Include a test proving processing order with inputs for which changing the order yields a different result.
- [ ] Verify RED:

```bash
pytest -q tests/test_command_safety.py
```

- [ ] Implement a hardware-independent API equivalent to:

```python
class CommandSafetyProcessor:
    def process(
        self,
        *,
        master_action_raw: Mapping[str, float],
        master_action_processed: Mapping[str, float],
        follower_qpos: Mapping[str, float],
    ) -> CommandFrame:
        ...
```

- [ ] Apply exactly: master/follower key mapping, gripper endpoint mapping, deadband, soft-limit clamp, max-step clamp from follower qpos, hard-limit clamp, immutable `effective_command`.
- [ ] Emit bounded structured events containing stage, joint, input, output, and reason. Reject NaN/Inf and incomplete action keys instead of guessing.
- [ ] Verify GREEN and run:

```bash
python -m compileall -q src scripts tests
pytest -q
```

- [ ] Stop and report; do not connect hardware or commit.

## Task 3: Integrate one immutable effective-command path

- [ ] Write a failing controller test with a fake robot and fake dataset proving the driver argument, dataset action, and mismatch expected value all equal the same frozen effective-command snapshot and differ from master input.
- [ ] Write a failing test proving mutation of master dictionaries after frame creation cannot change the driver/dataset values.
- [ ] Verify RED with `pytest -q tests/test_command_semantics.py tests/test_controller_episode_finalize.py`.
- [ ] Replace `CommandFrame.absolute_passthrough(...)` construction in `_control_step()` with `CommandSafetyProcessor.process(...)`.
- [ ] Pass `dict(command.effective_command)` to `robot.send_action()` and `command.training_action(...)` to the dataset writer. Do not derive either path from `act` or `act_processed_teleop`.
- [ ] Keep driver-side clamp enabled as defense in depth; compare its return value against the effective command.
- [ ] Verify GREEN, full pytest, compileall, and Ruff using the repository's current exclusions.
- [ ] Stop and report; no hardware and no commit.

## Task 4: Persistent mismatch contamination and accepted gates

- [ ] Write failing tests proving a transient mismatch logs a warning but a mismatch lasting the configured number of consecutive frames contaminates the current episode.
- [ ] Write failing tests proving contamination is sticky, `label=success` cannot set `accepted=true`, and accepted export rejects the episode.
- [ ] Define episode metadata fields:

```json
{
  "contaminated": true,
  "contamination_reasons": ["persistent_driver_command_mismatch"],
  "command_validation": {
    "mismatch_frames": 4,
    "max_abs_error": 63.0,
    "affected_joints": ["left_gripper.pos"]
  }
}
```

- [ ] Reset mismatch streak only when all command keys are within tolerance. Missing or extra driver-return keys count as mismatch.
- [ ] Rebuild `accepted_episodes.json` from canonical records using `label == success`, `contaminated == false`, valid v2 semantics, and complete calibration.
- [ ] Verify focused tests, full suite, compileall, and an export dry run under `tmp_path`.
- [ ] Stop and report; do not commit.

## Task 5: Quarantine episodes 0 and 1 without touching media/data

- [ ] Write a failing fixture test containing two accepted records plus sentinel Parquet/MP4 hashes.
- [ ] Implement metadata-only quarantine that atomically updates canonical/session episode records, sets contamination reason `pre_safety_effective_command`, and rebuilds the accepted list.
- [ ] Require explicit dataset root and episode indices; print a dry-run diff by default and require `--apply` for metadata writes.
- [ ] Verify file hashes and mtimes for `data/` and `videos/` are unchanged.
- [ ] Run dry-run against `/tmp/lerobot-phase0-hardware/dataset` and show the owner the proposed changes before applying them.
- [ ] Apply only after explicit owner confirmation, then verify episodes 0 and 1 remain loadable but absent from accepted export.
- [ ] Stop and report; do not commit.

## Task 6: Read-only calibration capture and dry-run

- [ ] Write tests with fake master/follower readers proving capture output includes per-side `master_min`, `master_max`, `follower_open`, `follower_close`, derived direction, deadband, soft bounds, and max-step, without calling any send method.
- [ ] Implement interactive endpoint capture that only reads positions after operator confirmation and writes a separate candidate JSON report.
- [ ] Implement dry-run output for endpoint and midpoint mapping plus simulated deadband/soft/max-step behavior.
- [ ] Keep real command sending unavailable in this task. Low-speed verification is a separate owner-approved hardware acceptance operation after candidate values are reviewed.
- [ ] Verify fake-device tests, compileall, and CLI `--help`.
- [ ] Stop and report; do not commit.

## Final phase-0 acceptance gate

Automated acceptance requires all tests, compileall, and available lint checks to pass. Hardware acceptance remains blocked until the owner supplies and reviews calibration output. Unverified trial recording is allowed but every such episode is contaminated; accepted status and accepted export fail closed. No Git commit or push occurs until the owner completes practical acceptance and explicitly authorizes it.
