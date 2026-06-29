# Phase 1 Workbench Safety Design

Status: approved through `.workspace/PRD.md` and the owner's instruction to begin Phase 1. This document remains uncommitted until hardware acceptance.

## Scope

Phase 1 makes `effective_command` the follower-space command after all Workbench safety transforms. It does not add relative teleoperation, Move to Ready integration, timing sidecars, or the complete data-quality state machine.

## Chosen approach

Use a pure, Workbench-owned `FollowerSafetyProcessor` driven by explicit, versioned per-joint configuration. Do not import LeRobot driver limit constants at runtime and do not infer safety from the driver's returned command.

Alternatives rejected:

1. Dynamically importing driver limits hides dataset semantics behind an installed-package revision.
2. Treating the driver return as the training action runs after the send boundary and violates the PRD's single-source invariant.

## Boundaries and order

Compatibility mapping owns OpenArm Mini master-to-follower semantics: gripper `0..100 -> 0..-65`, joint 6/7 remap, and right joint 7 direction correction. Safety receives only follower-space `.pos` keys and never remaps endpoints, swaps joints, or reverses direction.

```text
master raw
→ compatibility mapping
→ LeRobot teleop/robot action processors
→ follower-space target
→ deadband against current follower qpos
→ soft-limit clamp
→ max-step clamp against current qpos on the first frame, then previous effective command
→ velocity clamp against previous effective command using monotonic dt
→ tracking-error monitor and optional hold-current-qpos substitution
→ hard-limit clamp
→ effective_command
→ same snapshot to dataset and robot.send_action
→ driver return used only for mismatch validation
```

## Configuration

`safety_config_version` is a non-empty immutable identifier. Revised semantics use `openarm_follower_safety_v2_candidate` and a new dataset root. Every expected left/right follower action key has a hard limit, a contained soft limit, non-negative deadband, positive max step/velocity, and strictly increasing tracking warning/contamination/freeze thresholds. Hard limits reproduce the installed OpenArm follower tables exactly.

Initial soft/step/velocity values are candidate hardware-test values and remain `safety_config_verified=false` until owner acceptance. Trial operation is allowed, but recorded episodes from an unverified config are contaminated and cannot be accepted/exported.

After the first frame, live follower qpos never becomes the max-step reference. Tracking error is `abs(previous_effective - follower_qpos)` and is monitoring-only unless freeze fires. Freeze substitutes current follower qpos as a hold candidate, applies hard limits last, stops teleoperation, contaminates and saves an active episode, and blocks another episode until explicit reconnect/reset.

The processor rejects missing or unexpected keys, non-finite values, invalid time deltas, and incomplete configuration rather than guessing.

## Label and acceptance contract

The UI submits label/notes/index only. The backend derives acceptance from label, `dq_status`, compatibility verification, safety verification, and contamination. A success label is always storable; with unverified safety it remains `accepted=false` and returns explicit gate reasons instead of raising a compatibility-only error.

## Mismatch and metadata

The driver input, dataset action, and mismatch expected side are copied from the same immutable `effective_command`. Each episode accumulates mismatch frame count, maximum absolute error, affected joints, and maximum consecutive streak. Any mismatch creates a warning; reaching `mismatch_contamination_frames` makes contamination sticky.

Dataset and episode metadata record the compatibility version, safety version and verification state, complete limits, deadband, step/velocity/tracking values, mismatch tolerance/threshold, tracking summary/freeze state, and episode summary. An existing root with different or missing Phase 1 safety semantics is fail-closed.

## Test boundary

Automated tests use pure processors and fake robot/dataset objects only. No automated test connects CAN, serial devices, cameras, or the installed driver. Hardware acceptance is a separate owner gate. No Git commit, push, or stable deployment occurs before that gate passes.
