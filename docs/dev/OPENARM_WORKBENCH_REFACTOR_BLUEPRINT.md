# OpenArm Workbench Refactor Blueprint

## 1. Document status

- Project: `lerobot-openarm-workbench`
- Development host: 4090, `/home/sh/lerobot_workbench`
- Runtime baseline: LeRobot `0.4.4`, Conda environment `lerobot04`
- Confirmed development model: replace the copied deployment tree with an independent Git clone on 4090 before phase-0 feature work
- Document purpose: freeze the engineering scope and staged acceptance gates before feature development
- Functional code changed in this step: none
- Git commit/push allowed in this step: no

This blueprint implements the approved PRD and subsequent confirmed constraints. It does not replace the PRD. If this document and the PRD disagree, development stops and the conflict is reported to the project owner.

## 2. Current problem restatement

The workbench can currently connect an OpenArm bimanual follower, an OpenArm mini teleoperator, and three RGB cameras; preview camera streams; collect and label LeRobot v3 episodes; maintain canonical and session manifests; and execute a separate `move_to_ready.py` waypoint script.

The present control and recording path is:

```text
teleop.get_action()
    -> teleop_action_processor
    -> robot_action_processor
    -> robot.send_action(robot_action_to_send)

dataset action <- act_processed_teleop
```

Therefore the action written to the dataset is not explicitly the post-offset, post-safety, post-clamp follower-space command passed to the robot driver. This becomes incorrect as soon as relative mapping or workbench-side safety transforms are introduced.

Other confirmed limitations are:

1. Teleoperation and recording are coupled by the current `recording` state and `teleop_when_idle` flag.
2. Controller states are free-form strings rather than enforced transitions.
3. `move_to_ready.py` opens its own robot connection and cannot safely run concurrently with the workbench controller.
4. Ready motion uses linear interpolation and reports completion without closed-loop pose verification.
5. Ready and teleop sync validity are not represented or invalidated.
6. There is no workbench-owned safety pipeline with verified OpenArm limits.
7. `label=success` currently directly implies `accepted=true`; task outcome and data quality are not independent.
8. The controller records aggregate frame rate but not control-step timing or per-camera software timing.
9. The current manifest contains `schema_version: 1` for the manifest itself, but does not contain the required action-semantics `dataset_schema_version`.

## 3. Development objectives

The required target command path is fixed as:

```text
master_action_raw
    -> openarm_mini_compatibility_mapping
    -> master_action_processed
    -> relative mapping / sync offset
    -> relative_target
    -> safety layer
    -> safe_command
    -> effective_command
    -> robot driver
```

The following invariant is mandatory for every newly collected v2/production dataset that can be used for VLA post-training:

```text
LeRobot dataset action = effective_command
```

`effective_command` means the follower-space command after workbench offset, safety, clamp, and limit processing and immediately before it is passed to the robot driver. The driver return value is retained only for validation and logging and is never the sole training-action source.

`openarm_mini_compatibility_mapping` is teleop normalization, not a safety clamp. Version `openarm_mini_818892a3` reproduces the upstream LeRobot mapping introduced by commit `818892a3`: gripper `0..100 -> 0..-65 degrees`, leader joint 6/7 remap, and right leader joint 7 direction correction. It runs exactly once before absolute/relative teleop mapping. Runtime detection must reject a configuration that enables workbench mapping when the installed LeRobot teleoperator already exposes the native mapping constants.

Legacy absolute master-action datasets are read-only compatibility inputs for old-data inspection, fallback debugging, or migration comparison. They are not v2 training data, cannot share a dataset root with v2 episodes, and cannot be exported as v2-qualified data by `export_accepted_episodes`.

The user-facing collection sequence must become:

```text
IDLE
  -> Move to Ready
MOVING_TO_READY
  -> closed-loop verification passes
READY_VERIFIED
  -> Sync Master
TELEOP_ARMED
  -> Enable Teleop
TELEOP_ACTIVE_NOT_RECORDING
  -> Start Recording
RECORDING
  -> Stop Recording
SAVING
  -> save completes
UNLABELED
  -> Success / Failure / Discard
```

## 4. Baseline facts verified from the current project

### 4.1 Runtime and repository

- The deployed runtime reports LeRobot `0.4.4`.
- The existing automated suite passes: `34 passed`.
- The 4090 project directory is not currently a valid Git worktree. Its `.git` file points to a Mac-only worktree path:

  ```text
  /Users/log/Documents/wmdoc/lerobot-openarm-workbench/.git/worktrees/migrate-4090
  ```

  The owner has confirmed that 4090 will use a fresh independent clone from `git@github.com:YalouZhao/lerobot-openarm-workbench.git`. No feature development begins until the current deployment/config/data bindings are inventoried, the independent clone is prepared, and the source baseline is verified. Replacing the invalid tree is an environment-preparation operation, not a feature commit.

### 4.2 LeRobot driver behavior

The installed OpenArm follower `send_action()`:

1. filters position keys;
2. applies driver joint-limit clipping;
3. optionally applies `max_relative_target` clipping;
4. sends the resulting target to the motor bus;
5. returns the target actually sent.

The current LeRobot `0.4.4` return value is suitable for validation against `effective_command`, but the PRD explicitly prohibits using it as the only training-action source.

### 4.3 Existing compatibility boundary

`src/workbench/lerobot_compat.py` currently supports both older and newer LeRobot import/configuration layouts, distributes cameras for the `0.4.4` bimanual configuration, restores canonical camera keys, and normalizes position features. New command semantics must preserve this compatibility layer and canonical right/left position-key ordering.

### 4.4 Existing manifest behavior

- Dataset-root `episodes.jsonl` is canonical.
- Session `episodes.jsonl` is a mirror.
- Writes use file locking and atomic temp-file replacement.
- A saved episode is initially `unlabeled` and `accepted=false`.
- Current labeling derives acceptance directly from label.
- Discard during recording clears the unsaved episode buffer.
- Discard after save marks the canonical record as discarded; it does not physically delete LeRobot data.

## 5. Cross-stage engineering rules

1. Development proceeds in stages 0 through 4. Each stage stops at its acceptance gate.
2. No Git commit occurs until operator acceptance and explicit permission.
3. No Git push occurs until separate explicit permission.
4. Each functional change is test-first where practical: failing unit test, minimal implementation, passing test.
5. Hardware motion is never triggered by automated tests.
6. Dry-run tests use fake robot, teleop, camera, dataset, and monotonic clock objects under `tmp_path` or `/tmp`.
7. Production collection remains disabled whenever mandatory safety values for the active phase are unconfirmed.
8. Existing LeRobot v3 training fields remain unchanged except for the corrected semantic source of `action` in v2/production datasets.
9. Debug data remains sidecar data and does not silently enter the training feature schema.
10. Existing datasets are never rewritten or assigned a new action schema without an explicit migration decision. Legacy absolute master-action data remains read-only compatibility data.
11. Every controller transition and safety invalidation must be testable without hardware.
12. The controller remains the only owner of the active robot connection and command send path.

## 6. Phase 0: Freeze data semantics

### 6.1 Goal

Introduce an explicit command record, perform the minimum production-safe master-to-follower mapping and command safety processing before the driver call, make the training action equal to the final `effective_command`, record the action-semantics schema, and prevent old and new semantics from being appended into the same dataset. Phase 0 is blocked until calibrated gripper parameters are present; no default endpoint values may be inferred from nominal hardware limits.

### 6.2 Planned files

Create:

- `src/workbench/command.py`: immutable command-stage data object containing `master_action_raw`, `master_action_processed`, `relative_target`, `safe_command`, `effective_command`, `send_result`, and `safety_events`.
- `src/workbench/openarm_mini_compat.py`: versioned OpenArm Mini master-to-follower compatibility mapping and native-mapping detection; this module does not implement safety clamps.
- `src/workbench/command_safety.py`: pure, hardware-independent master/follower mapping and safety processor that applies configured joint mapping, gripper mapping, deadband, soft limits, maximum step, and hard limits and returns the immutable command stages plus bounded safety events.
- `tests/test_command_semantics.py`: command provenance, dataset action source, and driver-return mismatch tests.
- `tests/test_command_safety.py`: per-side gripper endpoint mapping, direction reversal, deadband, soft-limit, maximum-step, hard-clamp, missing-calibration, and non-finite-input tests.
- `tests/test_dataset_schema_gate.py`: new/resumed dataset schema compatibility tests.

Modify:

- `src/workbench/controller.py`: run the command-safety processor in the control loop, pass the resulting immutable `effective_command` to the driver and dataset writer, retain `send_result` for validation/logging, and contaminate the active episode after persistent mismatch.
- `src/workbench/config.py`: parse the explicitly selected teleop/action schema mode plus calibrated per-side gripper mapping and phase-0 command-safety configuration; reject production-ready operation when required calibration is absent.
- `src/workbench/dataset_manifest.py`: persist `dataset_schema_version` and reject incompatible resume/append operations.
- `src/workbench/episode_manifest.py`: carry the episode action schema, contamination state/reasons, and command-validation summary; contamination permanently forces `accepted=false`.
- `src/workbench/lerobot_compat.py`: preserve canonical position-key ordering and expose only compatibility helpers needed to validate action keys.
- `config/workbench_config.example.json`: document explicit legacy/new schema selection.
- `config/workbench_config.json`: update only after the operator confirms the intended local mode.
- `scripts/export_accepted_episodes.py`: reject legacy, unknown, mixed, mismatched, uncalibrated, or contaminated episodes when asked to produce a v2-qualified accepted export.
- `tests/test_controller_episode_finalize.py`: assert the saved action frame comes from `effective_command`.
- `tests/test_dataset_manifest.py`: assert schema persistence and mismatch rejection.
- `tests/test_export_schema_gate.py`: assert that only a compatible v2 follower-effective-command dataset can be exported as v2 accepted data.

### 6.3 Required behavior

1. The controller creates one command record for each control step.
2. The versioned OpenArm Mini compatibility mapping runs before absolute/relative teleop mapping and before every safety transform. It reproduces the complete `818892a3` semantics, not only gripper conversion.
3. Workbench mapping and native LeRobot mapping are mutually exclusive. Explicit `apply_openarm_mini_compat_mapping` and `compat_mapping_version` configuration plus runtime native-mapping detection fail closed on double application.
4. Safety processing order for phase 0 is fixed as deadband, soft-limit clamp, maximum-step clamp relative to current follower qpos, then hard joint-limit clamp. Every changed value produces a bounded safety event.
5. `effective_command` is complete, finite, immutable, and in follower action-feature space after all workbench-side limits and clamps.
6. `robot.send_action()` receives values copied only from that `CommandFrame.effective_command`.
7. The dataset frame is built only from that same `CommandFrame.effective_command`; it is never reconstructed from master or processed-master action.
8. Safety/mismatch logs identify the same command-frame values and do not maintain a second mutable command source.
9. Unverified compatibility mapping may be used only for throwaway trial collection; each episode is contaminated and cannot become `accepted=true` or enter accepted export.
10. `send_result` is compared with `effective_command` using configured absolute tolerance and persistence count. A persistent mismatch contaminates the active episode, records affected joints and maximum error, and permanently forces `accepted=false`.
11. A mismatch does not silently rewrite the dataset action to the driver return value.
12. Dataset creation preserves the manifest-format field and records the four approved semantic/control fields:

   ```text
   schema_version: <existing integer manifest format version>
   dataset_schema_version: openarm_workbench_v1_legacy | openarm_workbench_v2
   action_semantics: master_absolute_legacy | follower_effective_command
   teleop_mode: absolute_legacy | absolute_passthrough | relative_joint_offset
   command_frame_version: 1
   ```

13. Existing integer `schema_version` retains its current manifest-format meaning and is not repurposed.
14. Dataset resume is blocked before frame collection if `dataset_schema_version` or `action_semantics` differs from the configured runtime semantics.
15. v1 and v2 episodes cannot be written to the same dataset root.
16. New v2 collection records `effective_command` even when its control mode is `absolute_passthrough`.
17. `absolute_legacy` is restricted to reading, fallback debugging, or migration comparison and is never treated as v2-qualified production collection.
18. `export_accepted_episodes` fails closed when the dataset is legacy, mixed, unknown, uncalibrated, contaminated, or its `action_semantics` is not `follower_effective_command`.
19. Existing roots lacking the new semantic fields are never silently upgraded; their exact classification remains owner-blocked in section 13.1.
20. Debug command stages are not added to LeRobot training features in this phase.
21. Existing throwaway episodes 0 and 1 remain physically untouched but receive canonical contamination metadata and are removed from `accepted_episodes.json`; accepted export must exclude them.

### 6.4 Automated acceptance

- Gripper endpoint tests cover normal and reversed master ranges independently for left and right arms without hardware.
- Mapping configuration with missing endpoints, equal master endpoints, non-finite values, inverted soft bounds, or non-positive maximum step fails closed.
- Synthetic commands prove the documented mapping/deadband/soft-limit/max-step/hard-clamp order.
- Raw master and final effective command intentionally differ; the exact values passed to the fake driver, dataset writer, and safety log are equal to the same command-frame snapshot.
- A one-frame driver mismatch is logged but does not contaminate before the configured persistence count.
- A persistent driver mismatch contaminates the episode and makes both label-success and accepted export fail closed; dataset action remains effective command.
- Unverified mapping permits preview, diagnostics, and throwaway recording, but contaminates every episode and blocks acceptance and accepted export.
- Existing episodes 0 and 1 can be quarantined without modifying their Parquet or MP4 files.
- Command keys match the canonical bimanual action feature order and set.
- New schema cannot append to legacy or unknown schema roots.
- Legacy mode cannot append to the new follower-command schema.
- A new v2 dataset manifest contains `dataset_schema_version=openarm_workbench_v2`, `action_semantics=follower_effective_command`, its selected v2 `teleop_mode`, and `command_frame_version=1`, while preserving integer `schema_version`.
- `absolute_passthrough` v2 collection records effective follower commands, not master raw action.
- v1/legacy and action-semantic mismatches fail v2 accepted export.
- Full unit suite passes.
- `python -m compileall -q src scripts tests` passes.
- A no-hardware dry-run creates a temporary LeRobot-compatible frame with follower-command action semantics.

### 6.5 Operator acceptance

1. Inspect the operator-captured master open/closed and follower open/closed endpoint report before placing values in machine-local configuration.
2. Run gripper mapping in dry-run mode and verify endpoint, midpoint, direction, deadband, soft-limit, and max-step calculations without sending CAN commands.
3. Create a throwaway dataset only after calibration validation passes.
4. Perform separately approved low-speed, small-step tests for one gripper at a time; stop after each side for operator inspection.
5. Compare immutable effective command, fake/real driver return, and saved dataset action for several frames.
6. Force a harmless configured mismatch in a throwaway recording and confirm contamination prevents acceptance/export.
7. Confirm episodes 0 and 1 remain on disk but are absent from `accepted_episodes.json` and accepted export.
8. Confirm a schema mismatch or missing calibration blocks recording before frame collection.
9. Confirm the existing production dataset media and Parquet files are untouched.

### 6.6 Rollback

- Stop the workbench.
- Restore the pre-phase source/config tree from the accepted independent-clone Git baseline.
- Remove only the throwaway phase-0 dataset.
- Do not remove or rewrite existing production roots.
- If the new dataset was created but not accepted, preserve it as a quarantined test artifact rather than relabeling its schema.

## 7. Phase 1: State machine and Move to Ready

### 7.1 Goal

Separate teleoperation from recording, move ready-path execution under controller ownership, use smoothstep interpolation, verify actual follower position, and block recording until ready and sync prerequisites are satisfied.

Phase 1 may represent sync state and enforce the gate, but it does not implement the final relative mapping algorithm; that belongs to phase 2.

### 7.2 Planned files

Create:

- `src/workbench/state_machine.py`: allowed states, transitions, and prerequisite/invalidation rules.
- `src/workbench/ready_controller.py`: ready-path loading, smoothstep trajectory generation, execution coordination, and closed-loop verification.
- `tests/test_state_machine.py`: allowed/forbidden transition tests.
- `tests/test_ready_controller.py`: smoothstep, key validation, tolerance, and failure tests with a fake robot.
- `tests/test_ready_invalidation.py`: all mandatory invalidation-event tests.

Modify:

- `src/workbench/controller.py`: own ready execution, serialize command senders, expose ready/sync validity, and enforce recording prerequisites.
- `src/workbench/config.py`: parse ready path, settle time, and per-joint tolerance configuration.
- `src/workbench/server.py`: add Move to Ready, Verify Ready, Sync Master, Enable Teleop, Abort, and Emergency Freeze API routes required by the PRD flow.
- `src/workbench/web_assets.py`: render the required state and buttons and enforce server-backed button availability.
- `src/workbench/episode_manifest.py`: carry ready operation/result references needed by later episode records.
- `src/workbench/dataset_manifest.py`: preserve the ready metadata carried by episode records.
- `scripts/move_to_ready.py`: reuse the extracted ready module for CLI behavior without opening a second controller-owned connection.
- `config/workbench_config.example.json`: add ready configuration shape without guessed production values.
- `tests/test_move_to_ready_waypoints.py`: preserve current waypoint/copy/mirror behavior while testing the extracted module.
- `tests/test_controller_episode_finalize.py`: verify the ready/sync start gate.

### 7.3 Required behavior

1. The controller is the sole sender while the workbench is running.
2. Ready motion and teleop command forwarding are mutually exclusive.
3. Interpolation uses `s(t) = 3t^2 - 2t^3` or an exactly equivalent approved smoothstep.
4. After the final waypoint and settle interval, follower qpos is read and compared per joint with the configured target/tolerance.
5. Verification failure never enters `READY_VERIFIED`.
6. `Start Recording` is rejected unless ready is verified and sync is valid.
7. The server independently enforces transition rules; disabled UI buttons are not the safety boundary.
8. Ready and sync automatically become invalid after:
   - CAN reconnect;
   - teleop reconnect;
   - control-thread restart;
   - Emergency Freeze;
   - another Move to Ready request;
   - detected manual follower movement;
   - follower deviation beyond ready tolerance;
   - controller error recovery.
9. Ready execution records path id, target qpos, actual qpos, per-joint error, result, and timestamp in session events; a later episode references the latest valid ready result.

### 7.4 Automated acceptance

- Every allowed transition succeeds and every unapproved transition fails with a stable reason.
- Start Recording fails when ready is unverified.
- Start Recording fails when sync is incomplete.
- Smoothstep starts and ends at the exact endpoint and has zero endpoint slope by formula.
- Ready verification passes/fails at the configured per-joint boundary.
- Each listed invalidation event clears both ready and sync validity.
- A fake concurrent ready/teleop send attempt cannot reach the robot sender simultaneously.
- Full unit suite and compileall pass.
- Dry-run executes a multi-waypoint path against a fake robot with no hardware access.

### 7.5 Operator acceptance

1. With motors disabled or robot power withheld, verify the UI transition and error paths without motion where possible.
2. Review the configured ready path and tolerances before enabling hardware motion.
3. Run one supervised slow ready move with an emergency stop available.
4. Verify actual/target/errors shown in logs.
5. Deliberately use a stricter test tolerance and confirm recording remains blocked.
6. Confirm teleop commands are not forwarded during Move to Ready.

### 7.6 Rollback

- Stop the workbench before reverting.
- Return to the phase-0 accepted source/config baseline.
- Keep the standalone waypoint JSON files unchanged.
- Do not execute the old standalone ready script while the workbench owns the robot connection.
- Quarantine session logs produced during failed ready tests; no production episodes should be created before the ready gate passes.

## 8. Phase 2: Relative Teleop, Sync, and Safety

### 8.1 Goal

Build independent bimanual sync and relative joint control on top of the phase-0 workbench-owned command safety processor, add velocity/staleness policies, and implement Emergency Freeze exactly as specified. Phase 2 must not introduce a second clamp path or change the phase-0 effective-command provenance invariant.

### 8.2 Planned files

Create:

- `src/workbench/teleop_relative.py`: multi-frame sync snapshots, per-arm offsets, relative mapping, gain, deadband, and configured gripper mapping.
- `src/workbench/command_safety.py`: extend the phase-0 processor with relative-mode velocity and stale-command handling while preserving one final effective-command path.
- `tests/test_teleop_relative.py`: no-jump sync, per-arm sync, gain, deadband, and gripper-mode tests.
- `tests/test_safety.py`: clamp/limit/violation and event tests.
- `tests/test_emergency_freeze.py`: hold-target, recording contamination, and state invalidation tests.

Modify:

- `src/workbench/command.py`: populate all command stages and safety events.
- `src/workbench/controller.py`: integrate relative control and safety into the single send path and implement freeze/hold behavior.
- `src/workbench/config.py`: parse and validate relative teleop, gripper, and safety configuration.
- `src/workbench/server.py`: activate independent left/right sync and Emergency Freeze commands.
- `src/workbench/web_assets.py`: display sync status, safety readiness, clamp events, and freeze state.
- `src/workbench/episode_manifest.py`: record contamination and safety summaries.
- `src/workbench/dataset_manifest.py`: preserve contamination and safety summaries in canonical records.
- `config/workbench_config.example.json`: document complete relative/safety configuration fields without production guesses.
- `config/workbench_config.json`: update only after owner-approved hardware values are supplied.
- `tests/test_controller_episode_finalize.py`: assert contaminated episodes cannot become accepted.

### 8.3 Required behavior

For each arm:

```text
q_follower_cmd = q_follower_start + K * (q_master_now - q_master_start)
```

The implementation must satisfy:

1. Sync uses the owner-approved number of samples and a per-joint median.
2. Left and right arms can be synchronized independently.
3. The first command after sync equals the current follower start pose within floating-point tolerance.
4. Relative mapping operates on normalized/canonical master keys, not raw serial values.
5. Gain and deadband are configurable per joint.
6. Relative-mode gripper behavior reuses the calibrated phase-0 mapping and is never inferred or duplicated.
7. The phase-2 safety order extends the phase-0 contract with gain and velocity handling; the final documented order is mapping, deadband, gain, soft-limit clamp, max-step clamp, velocity clamp, hard-limit clamp, then driver send.
8. All clamps and violations produce bounded safety events.
9. Missing production safety values block production collection mode.
10. Recording-time clutch, re-zero, sync, freeze, or equivalent control discontinuity marks the episode contaminated and permanently ineligible for acceptance.
11. Emergency Freeze performs exactly:

```text
read current follower qpos
use current qpos as hold target
stop accepting master increments
stop recording
mark current episode abnormal and contaminated
invalidate Ready and Sync
prohibit accepted
```

12. Emergency Freeze does not disable motor torque unless separately approved.
13. If current follower qpos cannot be read during freeze, the controller enters `ERROR`, records the failure, and does not guess a hold target.

### 8.4 Automated acceptance

- Sync with an arbitrarily offset master produces no follower jump.
- Independent left/right sync does not alter the other arm's snapshot.
- Gain/deadband/gripper modes produce expected follower-space targets.
- Step, velocity, and soft-limit constraints operate in the documented order.
- Dataset action remains exactly the final effective command after every clamp.
- Driver-return differences are logged but do not replace dataset action.
- Freeze sends a current-qpos hold target, rejects further master deltas, stops recording, contaminates the episode, and clears ready/sync.
- A contaminated episode cannot be marked accepted through controller or manifest APIs.
- Full unit suite and compileall pass.
- Dry-run replays synthetic master/follower traces without importing live hardware.

### 8.5 Operator acceptance

Hardware testing is split and stopped after each item:

1. Production mode remains disabled; inspect parsed safety configuration.
2. Dry-run one joint at a time and inspect computed commands without sending.
3. Enable one arm with a conservative approved gain and verify sync causes no motion.
4. Test small positive/negative motion for each joint.
5. Repeat for the second arm.
6. Test gripper mapping separately.
7. Verify max-step, velocity, and soft-limit behavior using thresholds chosen to trigger safely at small movement.
8. Test Emergency Freeze while not recording.
9. Test Emergency Freeze during a throwaway recording and confirm contamination prevents acceptance.
10. Only after explicit acceptance may production collection mode be enabled.

### 8.6 Rollback

- Trigger the approved hold/freeze procedure if the robot is active, then stop the workbench.
- Restore the phase-1 accepted source/config baseline.
- Keep production mode disabled.
- Preserve all safety and freeze logs.
- Delete no episodes; mark throwaway affected episodes contaminated/discarded in their test dataset.

## 9. Phase 3: Data Quality Gate

### 9.1 Goal

Decouple task-result labeling, data-quality status, and training acceptance; enforce hard gates; expose reasons in the UI and canonical/session manifests.

### 9.2 Planned files

Create:

- `src/workbench/data_quality.py`: deterministic versioned DQ evaluation and reason codes.
- `tests/test_data_quality.py`: every hard gate, threshold boundary, and acceptance derivation.
- `tests/test_label_dq_acceptance.py`: controller/API/manifest acceptance invariants.

Modify:

- `src/workbench/episode_manifest.py`: add `dq_status`, `dq_reasons`, `dq_policy_version`, contamination, and required metadata fields.
- `src/workbench/dataset_manifest.py`: derive acceptance as `label == success and dq_status == pass`; rebuild accepted list using the new rule.
- `src/workbench/controller.py`: collect episode evidence and run DQ after stop/save before final acceptance decisions.
- `src/workbench/server.py`: return DQ results and reject illegal acceptance transitions.
- `src/workbench/web_assets.py`: show pass/warning/fail and exact reasons before labeling/acceptance.
- `src/workbench/config.py`: parse DQ thresholds and policy version.
- `config/workbench_config.example.json`: document DQ configuration without guessed thresholds.
- `config/workbench_config.json`: update only after threshold approval.
- `scripts/export_accepted_episodes.py`: use canonical `accepted_episodes.json` under the new rule.
- `tests/test_dataset_manifest.py`: update old label-only expectations to the new approved rule.
- `tests/test_controller_episode_finalize.py`: verify Stop, DQ, label, and acceptance sequencing.

### 9.3 Required behavior

```text
label: success | failure | discard | unlabeled
dq_status: pass | warning | fail
accepted: label == success AND dq_status == pass
```

Hard gates must cover:

- ready not verified;
- sync incomplete;
- any required camera missing;
- episode below minimum length;
- control FPS severely abnormal;
- action spike;
- NaN/non-finite state or action;
- Emergency Freeze or any contamination event;
- incomplete metadata or save failure.

The DQ policy must:

1. use stable machine-readable reason codes plus human-readable details;
2. record the policy version and evaluated thresholds;
3. never allow UI-provided `accepted=true` to override a non-pass DQ result;
4. recompute `accepted_episodes.json` atomically from canonical records;
5. mirror canonical records to the session manifest after canonical success;
6. preserve saved failure/discard/DQ-fail episodes in the raw dataset.

### 9.4 Automated acceptance

- Each hard gate independently produces `dq_status=fail` and the expected reason.
- Warning-only evidence produces `warning` and is not accepted under the confirmed strict rule.
- Only success plus pass is accepted.
- Success plus warning/fail is not accepted.
- Failure/discard/unlabeled plus pass is not accepted.
- NaN and missing required metadata cannot be serialized as a passing record.
- Canonical, session mirror, and accepted list remain consistent after each transition.
- Full unit suite and compileall pass.
- Dry-run evaluates synthetic good/bad episodes under `/tmp`.

### 9.5 Operator acceptance

1. Record one valid short throwaway episode and verify pass behavior using approved minimum duration.
2. Record or simulate one too-short episode and verify failure reason.
3. Disconnect one non-production test camera before an episode and verify recording is blocked or the episode fails DQ according to the approved flow.
4. Trigger a safe test clamp/spike condition and verify the reason.
5. Mark pass/fail episodes success and confirm only pass appears in `accepted_episodes.json`.
6. Confirm UI cannot override acceptance.

### 9.6 Rollback

- Stop collection before reverting.
- Restore the phase-2 accepted source/config baseline.
- Do not rewrite phase-3 episode records into label-only acceptance.
- Quarantine phase-3 test datasets if their DQ fields are not supported by the restored software.

## 10. Phase 4: Timing records

### 10.1 Goal

Capture monotonic control-step timing in memory, write a post-stop sidecar, and store only timing summaries in manifests.

### 10.2 Planned files

Create:

- `src/workbench/timing.py`: monotonic timing sample model, bounded episode buffer, statistics, and sidecar writer.
- `tests/test_timing.py`: monotonic intervals, statistics, dropped/stale frames, and atomic sidecar tests.

Modify:

- `src/workbench/controller.py`: capture required timestamps around observation, camera receipt, master read, command send, and control-step completion.
- `src/workbench/episode_manifest.py`: add timing sidecar reference and summary.
- `src/workbench/dataset_manifest.py`: retain timing summary and sidecar reference in canonical records.
- `src/workbench/config.py`: parse timing buffer/format configuration.
- `config/workbench_config.example.json`: document timing settings.
- `src/workbench/web_assets.py`: show episode timing summary without loading per-frame sidecar data.
- `tests/test_controller_episode_finalize.py`: verify timing buffer flush and manifest linkage.

### 10.3 Required behavior

1. Durations use `time.monotonic_ns()` or an equivalent monotonic clock.
2. The control loop performs memory appends only; it does not write per-frame JSONL.
3. Stop/finalize writes one approved sidecar format under the dataset/session debug area.
4. The sidecar contains control-step timestamps required by the PRD, using workbench frame-receipt time when the camera API exposes no acquisition timestamp.
5. Manifest summary contains mean FPS, p95 latency, max latency, camera staleness, max camera delta, dropped-frame count, and action-send latency.
6. Sidecar write failure prevents DQ pass/acceptance because required metadata is incomplete.
7. Timing buffer size is bounded and overflow is recorded rather than silently discarded.

### 10.4 Automated acceptance

- Synthetic timestamps produce exact expected mean/p95/max values.
- Non-monotonic sample input is rejected or marked invalid.
- No per-frame disk write occurs during control steps.
- Stop writes the sidecar atomically and links it to the correct episode.
- Missing camera timestamps produce explicit staleness/missing counters.
- Full unit suite and compileall pass.
- A no-hardware 30 Hz synthetic dry-run verifies bounded buffer behavior.

### 10.5 Operator acceptance

1. Record three throwaway episodes of different lengths.
2. Confirm Stop writes one sidecar per saved episode.
3. Compare manifest frame count, video metadata, and timing sample count.
4. Verify displayed mean FPS and latency statistics.
5. Introduce a safe artificial delay in a test-only configuration and verify p95/max increase and DQ response.
6. Confirm recording remains responsive and Stop latency remains acceptable.

### 10.6 Rollback

- Restore the phase-3 accepted source/config baseline.
- Preserve timing sidecars as debug artifacts; restored software may ignore but must not delete them.
- Do not append to a dataset if the restored software fails its action-schema or metadata compatibility gate.

## 11. Stage report and Git gates

At the end of every stage, development stops and reports:

```text
阶段：
完成内容：
修改文件：
测试命令：
测试结果：
未测试内容：
风险：
需要我验收的项目：
是否需要 PRD 变更：
```

Before any requested commit, the report additionally includes:

- diff summary;
- exact test commands and results;
- remaining risk;
- proposed commit message.

Only an explicit `通过，可以提交` authorizes `git commit`. Only a later explicit `可以推送` authorizes `git push`.

## 12. Rollback and data protection strategy

1. Each phase starts from the previously operator-accepted Git point.
2. No phase modifies existing production dataset data/video/parquet files in place.
3. Schema gates run before collecting the first frame into a resumed root.
4. All phase hardware acceptance uses a new throwaway dataset root.
5. Failed or interrupted test datasets are quarantined, not silently resumed under a different schema.
6. Config changes are reviewed separately from source changes because they contain machine-bound safety and device values.
7. Rollback means source/config rollback plus selection of a schema-compatible dataset; it never means relabeling dataset semantics.
8. Emergency or contaminated episodes remain auditable and cannot be made accepted by rollback.

## 13. Blocking uncertainties requiring owner confirmation

No implementation may guess the following values or semantics.

### 13.1 Confirmed phase-0 decisions and one remaining blocker

Confirmed:

1. 4090 will use an independent clone from `git@github.com:YalouZhao/lerobot-openarm-workbench.git`; the invalid copied worktree metadata will not be repaired or used for development.
2. The effective-command invariant applies to every new v2/production dataset that is eligible for VLA post-training.
3. Legacy master-action schema is read-only compatibility data for old-data reading, fallback debugging, and migration comparison. It cannot mix with v2 data and cannot be exported as v2-qualified accepted data.
4. New v2 collection records `effective_command` even when control uses absolute passthrough.
5. Existing integer `schema_version` remains the manifest format version.
6. `dataset_schema_version` identifies training semantics:
   - `openarm_workbench_v1_legacy`
   - `openarm_workbench_v2`
7. `action_semantics` identifies action meaning:
   - `master_absolute_legacy`
   - `follower_effective_command`
8. `teleop_mode` is one of:
   - `absolute_legacy`
   - `absolute_passthrough`
   - `relative_joint_offset`
9. `command_frame_version` starts at integer `1`.
10. Semantic mismatch is a fatal export error.
11. Phase 0 now owns the minimum command safety processor required to make `effective_command` truthful: master/follower mapping, calibrated gripper mapping, deadband, soft limit, maximum step, and hard clamp all run before the driver call.
12. The same immutable `CommandFrame.effective_command` is the sole source for driver input, v2 dataset action, and safety/mismatch comparison.
13. Missing gripper calibration blocks production recording, acceptance, and accepted export.
14. Persistent driver mismatch contaminates the active episode and permanently prevents acceptance.
15. Existing throwaway episodes 0 and 1 remain physically intact, are marked contaminated, and are excluded from accepted export.
16. Gripper calibration uses operator-positioned endpoints, dry-run inspection, and separately approved low-speed small-step verification; the software must not automatically sweep to mechanical endpoints.

Remaining phase-0 hardware inputs:

1. Per-side `master_min` and `master_max` captured from OpenArm mini.
2. Per-side `follower_open` and `follower_close` captured from OpenArm follower.
3. Per-side direction/reversal confirmation.
4. Per-side deadband, soft bounds, and maximum single-step change.
5. Driver mismatch absolute tolerance and persistence-frame threshold.

Confirmed handling for unversioned roots:

1. Existing dataset roots with none of the new semantic fields are classified as `legacy_unknown`.
2. `legacy_unknown` roots are blocked from append and accepted/v2 export.
3. They remain blocked until a separate, explicit audit or migration operation assigns semantics.
4. No automatic v1 classification or in-place metadata backfill is allowed.

### 13.2 Before phase 1 hardware acceptance

1. Ready pose per-joint tolerance values.
2. Ready settle time.
3. Manual-movement/deviation detection threshold and persistence window.
4. Whether every waypoint or only the final ready waypoint requires closed-loop verification. The PRD explicitly requires final ready verification; intermediate verification is not specified.

### 13.3 Before phase 2 implementation/acceptance

1. Phase-0 calibrated left/right joint and gripper limits must already be accepted.
2. Relative-mode per-joint gains and any deadband overrides.
3. Per-joint velocity limits and any relative-mode maximum-step overrides.
4. Relative gripper gain/mode behavior using the existing calibrated endpoint mapping.
5. Number and duration of sync samples.
6. Emergency hold command frequency and maximum hold duration.
7. Whether a non-dangerous clamp continues the episode or immediately freezes; all events will still be recorded.
8. Recording-time clutch remains prohibited by the confirmed PRD; any future allowance requires a PRD change.

### 13.4 Before phase 3 implementation

1. Minimum and maximum episode length.
2. Severe FPS failure threshold and evaluation window.
3. Action-spike threshold and whether it is evaluated before or after safety clamp; both can be recorded, but the failure rule must be approved.
4. Camera stale/missing thresholds.
5. First/last stationary-time thresholds.
6. Whether `dq_status=warning` is intentionally not accepted. The confirmed formula currently requires exactly `dq_status=pass`.

### 13.5 Before phase 4 implementation

1. Timing sidecar format: NPZ, Parquet, or MsgPack.
2. Timing sidecar directory and retention policy.
3. Maximum in-memory timing samples or maximum episode duration.
4. Whether camera API modification is allowed to expose a closer frame-receipt timestamp; otherwise controller observation-return time will be used as the approved fallback.

## 14. Boundaries that must not be changed without approval

The following are fixed boundaries, not implementation suggestions:

1. Do not replace LeRobot v3 as the canonical training format.
2. Do not add master raw action to the training `action` feature of v2/production datasets.
3. Do not use driver return as the sole action source for v2/production datasets.
4. Do not mix legacy and new action semantics in one dataset root or v2-qualified export.
5. Do not silently migrate existing datasets.
6. Do not change the three canonical image keys:
   - `observation.images.main`
   - `observation.images.wrist_left`
   - `observation.images.wrist_right`
7. Do not enable production collection without confirmed safety configuration.
8. Do not couple Start Recording with implicit Move to Ready or implicit Sync.
9. Do not permit recording before ready verification and sync.
10. Do not permit clutch/re-zero/sync during recording without contaminating the episode.
11. Do not implement Emergency Freeze as merely stopping commands or automatically disabling motor torque.
12. Do not physically delete a saved discarded episode from raw LeRobot data.
13. Do not let `success` alone imply acceptance after phase 3.
14. Do not write per-frame timing JSONL in the control loop.
15. Do not perform unsupervised hardware motion.
16. Do not modify UI workflow, schema, safety semantics, or phase scope beyond the PRD without stopping for approval.
17. Do not commit or push without the explicit gates specified by the owner.

## 15. Blueprint acceptance gate

No functional development begins until:

1. the project owner approves this blueprint;
2. the confirmed unversioned-root classification in section 13.1 is enforced by the phase-0 implementation;
3. the confirmed independent 4090 clone has been prepared and its baseline verified without losing host-specific ignored config.

After approval, only phase 0 is implemented. Development stops again after phase-0 automated testing and before any commit.
