# Phase 1 Workbench Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use test-driven development task-by-task. The owner's no-commit-before-hardware-test rule overrides generic commit steps.

**Goal:** Generate one follower-space `effective_command` after Workbench safety, send and record that same command, and fail closed on driver mismatch or incompatible safety metadata.

**Architecture:** A pure `FollowerSafetyProcessor` applies versioned follower-space limits after compatibility and existing action processors. Controller-owned episode state aggregates mismatch evidence; canonical metadata and export gates enforce the same semantics.

**Tech Stack:** Python dataclasses, monotonic timestamps, JSON configuration/manifests, pytest, LeRobot 0.4 fake-device tests.

---

### Task 1: Configuration

**Files:** `src/workbench/safety.py`, `src/workbench/config.py`, `config/workbench_config.example.json`, `tests/test_safety.py`, `tests/test_config_semantics.py`

- [x] Write failing tests for complete 16-key config, missing keys, non-finite values, invalid limits, non-positive step/velocity, versions, and mismatch thresholds.
- [x] Verify RED, implement immutable settings/parser, then verify GREEN and full suite.

### Task 2: Pure follower-space processor

**Files:** `src/workbench/safety.py`, `src/workbench/command.py`, `tests/test_safety.py`, `tests/test_command_semantics.py`

- [x] Write failing tests for deadband, soft clamp, max step, velocity, hard clamp, fixed ordering, invalid inputs, and structured events.
- [x] Verify RED, implement the pure processor, then verify GREEN and full suite.

### Task 3: Controller command path

**Files:** `src/workbench/controller.py`, `tests/test_controller_episode_finalize.py`

- [x] Write failing fake-device tests proving safety runs after compatibility, driver and dataset receive equal effective commands, and gripper mapping occurs once.
- [x] Verify RED, integrate before `effective_command`, then verify GREEN and full suite.

### Task 4: Mismatch contamination and accepted gates

**Files:** `src/workbench/controller.py`, `src/workbench/episode_manifest.py`, `src/workbench/dataset_manifest.py`, `scripts/export_accepted_episodes.py`, controller/manifest/export tests.

- [x] Write failing tests for warning, consecutive threshold, sticky contamination, summary metadata, label rejection, and export rejection.
- [x] Verify RED, implement accumulator and fail-closed gates, then verify GREEN and full suite.

### Task 5: Safety semantics metadata

**Files:** manifest/controller files and dataset/export tests.

- [x] Write failing tests for complete metadata and append/export rejection on safety-version or configuration mismatch.
- [x] Verify RED, persist and validate the complete safety snapshot, then verify GREEN and full suite.

### Task 6: Automated acceptance and owner handoff

- [x] Run compileall, full pytest, and Ruff on changed/new files using the existing `/home/sh/openpi/.venv/bin/ruff` binary.
- [x] Confirm stable workspace and 8091 are unchanged.
- [x] Provide low-speed hardware test instructions and wait for owner results.
- [ ] Do not commit or push until owner hardware acceptance.

### Task 7: Hardware-feedback revision — labeling and max-step semantics

**Files:** `src/workbench/web_assets.py`, `src/workbench/server.py`, `src/workbench/controller.py`, `src/workbench/dataset_manifest.py`, `src/workbench/safety.py`, manifests/config and tests.

- [x] RED: success labeling without client `accepted` stores the label and derives `accepted=false` with explicit reasons when safety is unverified.
- [x] GREEN: remove `accepted` from the UI/server/controller input contract and centralize backend acceptance derivation including `dq_status`.
- [x] RED: after frame one, changing follower qpos cannot reverse a monotonic follower target command.
- [x] GREEN: max-step and velocity both reference previous effective command after initialization.
- [x] RED: tracking warning, persistent contamination, and freeze-hold behavior are independently observable and metadata-backed.
- [x] GREEN: add per-joint tracking thresholds, persistence, hold substitution, sticky contamination, freeze state, and final hard clamp.
- [x] Upgrade to `openarm_follower_safety_v2_candidate`; create `/tmp/lerobot-phase1-hardware-v2/dataset`; never append to the v1 candidate root.
- [x] Run full pytest/compileall/lint and hand off a short comparison protocol. Do not commit before owner hardware acceptance.
