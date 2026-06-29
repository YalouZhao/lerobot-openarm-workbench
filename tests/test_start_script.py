from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "start_with_can.sh"


def test_start_script_supports_deployment_environment_overrides() -> None:
    content = SCRIPT.read_text()

    assert 'WORKBENCH_ROOT="${WORKBENCH_ROOT:-' in content
    assert 'source "$WORKBENCH_ROOT/.env"' in content
    assert 'CONDA_SH="${CONDA_SH:-' in content
    assert 'conda activate "$CONDA_ENV"' in content
    assert 'python "$WORKBENCH_ROOT/scripts/start_workbench.py"' in content
