# Phase 0 Implementation Plan: Freeze Data Semantics

## Scope

Phase 0 changes only command provenance, action-semantic metadata, dataset append protection, and accepted-export protection. It does not implement relative teleoperation, safety limits, ready-state control, DQ gates, or timing sidecars.

No commit or push is permitted before operator acceptance.

## Task 1: Command provenance object

Create `src/workbench/command.py` with an immutable `CommandFrame` containing:

- `master_action_raw`
- `master_action_processed`
- `relative_target`
- `safe_command`
- `effective_command`
- `send_result`
- `safety_events`

Add helpers that:

- construct phase-0 absolute passthrough stages;
- attach the driver return without changing `effective_command`;
- choose the training action from explicit `action_semantics`;
- report missing, extra, and numerically different driver-return keys.

Test-first file: `tests/test_command_semantics.py`.

Red tests:

1. v2 training action is `effective_command`.
2. legacy training action is `master_action_processed`.
3. attaching `send_result` does not mutate command stages.
4. driver mismatch reports changed/missing/extra keys.
5. controller sends and records `effective_command` for v2 even when the driver returns a different value.
6. Action feature specifications pass through `aggregate_pipeline_dataset_features()` with the robot action processor so LeRobot receives dataset-ready `dtype/shape/names` metadata.

## Task 2: Explicit schema configuration

Extend `DatasetSettings` with:

- `dataset_schema_version`
- `action_semantics`
- `command_frame_version`

Read `teleop.mode` as the selected `teleop_mode`.

Approved combinations:

```text
openarm_workbench_v1_legacy + master_absolute_legacy + absolute_legacy
openarm_workbench_v2 + follower_effective_command + absolute_passthrough
openarm_workbench_v2 + follower_effective_command + relative_joint_offset
```

Phase 0 collection supports the first two control modes. `relative_joint_offset` is reserved in the schema but must fail collection with a clear not-yet-implemented error until phase 2.

Test-first file: `tests/test_config_semantics.py`.

Red tests:

1. Explicit v2 settings load successfully.
2. Missing semantic fields are rejected by JSON config loading.
3. Invalid field combinations are rejected.
4. Unsupported schema/semantic/mode values are rejected.
5. Example configuration contains the approved v2 values.

## Task 3: Dataset-root schema gate

Extend `CanonicalDatasetManifest` to own expected semantics and validate before LeRobot dataset creation/resume.

Rules:

1. A missing/empty root may initialize with configured semantics.
2. A non-empty root without `dataset_manifest.json` is `legacy_unknown` and is blocked.
3. A manifest missing any semantic field is `legacy_unknown` and is blocked.
4. Existing integer `schema_version` remains unchanged.
5. Existing dataset semantics must exactly match configured `dataset_schema_version`, `action_semantics`, `teleop_mode`, and `command_frame_version`.
6. No field is automatically backfilled.
7. Each episode record carries the four semantic/control values.
8. An episode whose values differ from its dataset root is rejected.

Test-first files:

- `tests/test_dataset_manifest.py`
- `tests/test_dataset_schema_gate.py`

The controller calls the validation gate before opening or creating a LeRobot dataset and initializes the canonical manifest only after the LeRobot dataset object is successfully opened/created.

## Task 4: Accepted export gate

Change `scripts/export_accepted_episodes.py` to use a canonical dataset root rather than trusting a session mirror.

Rules:

1. `--dataset-root` is required for v2 accepted export.
2. Legacy `--session-dir` export is rejected because it cannot prove action semantics.
3. Export requires:
   - `dataset_schema_version=openarm_workbench_v2`
   - `action_semantics=follower_effective_command`
   - `command_frame_version=1`
   - `teleop_mode` in the approved v2 set
4. Missing fields, unknown roots, v1, and mismatches fail closed.
5. The exported index list is rebuilt from canonical dataset-root `episodes.jsonl` and only includes `success + accepted=true` under the current pre-DQ phase-0 rule.

Test-first file: `tests/test_export_schema_gate.py`.

## Task 5: Verification

Run on 4090 with all temporary test output under `/tmp`:

```bash
cd /home/sh/src/lerobot-openarm-workbench-dev
source /home/sh/miniforge3/etc/profile.d/conda.sh
conda activate lerobot04
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/lerobot-workbench-phase0-pytest
```

Run syntax/static checks without writing repository bytecode:

```bash
python - <<'PY'
import ast
from pathlib import Path
for root in ('src', 'scripts', 'tests'):
    for path in Path(root).rglob('*.py'):
        ast.parse(path.read_text(), filename=str(path))
print('AST parse: PASS')
PY

ruff check src scripts tests
```

Run a no-hardware dry-run that creates a fake v2 dataset root under `/tmp`, validates it, records a synthetic command frame, and exports accepted indexes.

## Acceptance stop

After verification, report:

- exact changed files;
- diff summary separated from pre-existing production-baseline changes;
- all test commands and outputs;
- untested hardware behavior;
- schema and rollback risks;
- operator test procedure.

Then stop. Do not commit or push.
