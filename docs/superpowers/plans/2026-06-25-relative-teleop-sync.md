# Relative Teleop Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the first PRD Phase 3 slice so Move to Ready can be followed by Sync Master and recording without the follower jumping back to the master origin.

**Architecture:** Add a controller-owned sync snapshot that records current master/follower follower-space positions, applies a relative joint offset before the Workbench safety layer, exposes sync state through status/API/UI, and gates recording when configured. Keep dataset action and driver command sourced only from `effective_command`.

**Tech Stack:** Python controller/server tests with pytest, existing workbench JSON config, existing plain JS UI assets.

---

### Task 1: Sync state and start gate

**Files:**
- Modify: `src/workbench/config.py`
- Modify: `src/workbench/controller.py`
- Test: `tests/test_controller_episode_finalize.py`

- [ ] Write failing tests for `require_sync_for_recording`, sync invalidation after Move to Ready, and status payload.
- [ ] Run targeted pytest and verify failure is due missing sync behavior.
- [ ] Add `sync` settings, controller sync state fields, `_sync_required_for_recording()`, `_invalidate_sync()`, and start gate.
- [ ] Run targeted pytest and verify pass.

### Task 2: Relative joint sync mapping

**Files:**
- Modify: `src/workbench/controller.py`
- Test: `tests/test_controller_episode_finalize.py`

- [ ] Write failing test where follower is at ready pose, master is at origin, Sync Master is clicked, and the first command after recording equals the ready pose.
- [ ] Run targeted pytest and verify failure is due missing `sync_master()` or missing offset.
- [ ] Implement `sync_master()` snapshot and `_apply_sync_to_follower_target()` before safety processing.
- [ ] Run targeted pytest and verify pass.

### Task 3: API/UI exposure

**Files:**
- Modify: `src/workbench/server.py`
- Modify: `src/workbench/web_assets.py`
- Test: `tests/test_server_dataset_api.py`
- Test: `tests/test_label_acceptance.py`

- [ ] Write failing tests for `POST /api/sync/master` and UI containing the Sync Master action/status.
- [ ] Run targeted pytest and verify failure is due missing route/UI.
- [ ] Add route and UI button/status logging.
- [ ] Run targeted pytest and verify pass.

### Task 4: Full verification and commit

**Files:**
- Modify: `config/workbench_config.example.json`
- Modify: `config/workbench_config.phase1-hardware-test.json` if tracked/needed by dev config

- [ ] Add documented sync defaults.
- [ ] Run full pytest suite.
- [ ] Review git diff for stable-workspace isolation.
- [ ] Commit after tests pass.
