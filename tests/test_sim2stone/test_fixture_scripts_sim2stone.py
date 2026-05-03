"""sim2stone + headless --download for ``docs/cantera_examples`` (vendored Cantera scripts)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES_DIR = _REPO_ROOT / "docs" / "cantera_examples"


def _subprocess_env() -> dict[str, str]:
    """Environment for ``boulder`` / downloaded scripts so Cantera finds bundled data.

    STONE YAML may record mechanisms as ``example_data/...``; resolving those
    requires Cantera's ``example_data`` directory on ``CANTERA_DATA``.
    """
    import cantera as ct

    base = Path(ct.__file__).resolve().parent / "data"
    example = base / "example_data"
    parts: list[str] = []
    if example.is_dir():
        parts.append(str(example))
    parts.append(str(base))
    prev = os.environ.get("CANTERA_DATA", "").strip()
    if prev:
        parts.append(prev)
    return {**os.environ, "CANTERA_DATA": os.pathsep.join(parts)}

# (script filename, default ``--mechanism`` for sim2stone phases.gas)
_FIXTURES: tuple[tuple[str, str], ...] = (
    ("combustor.py", "gri30.yaml"),
    ("reactor2.py", "gri30.yaml"),
    ("nanosecond_pulse_discharge.py", "example_data/methane-plasma-pavan-2023.yaml"),
)

# Headless ``--download`` can still fail for some upstream examples:
# - combustor: CVODE during staged solve on the extinguished end-state.
# - nanosecond_pulse_discharge: PlasmaPhase ``cp_mole`` not implemented when the
#   runner rebuilds/solves (sim2stone executing the .py alone may still succeed).
_DOWNLOAD_XFAIL: frozenset[str] = frozenset(
    {"combustor.py", "nanosecond_pulse_discharge.py"}
)

_DOWNLOAD_PARAMS: list = []
for _n, _m in _FIXTURES:
    if _n in _DOWNLOAD_XFAIL:
        _DOWNLOAD_PARAMS.append(
            pytest.param(_n, _m, marks=pytest.mark.xfail(strict=False))
        )
    else:
        _DOWNLOAD_PARAMS.append((_n, _m))


@pytest.mark.parametrize("script_name,mechanism", _FIXTURES)
def test_sim2stone_cantera_examples_yaml_valid(
    tmp_path: Path, script_name: str, mechanism: str
) -> None:
    """Each bundled Cantera example runs through sim2stone and yields valid STONE YAML."""
    script = _EXAMPLES_DIR / script_name
    if not script.is_file():
        pytest.skip(f"{script_name} not found under docs/cantera_examples")

    if script_name == "nanosecond_pulse_discharge.py":
        import cantera as ct

        try:
            ct.Solution(mechanism)
        except (OSError, ValueError, RuntimeError) as exc:
            pytest.skip(f"Plasma mechanism not available ({mechanism}): {exc}")

    os.environ.setdefault("MPLBACKEND", "Agg")

    out_yaml = tmp_path / f"{script.stem}.yaml"

    from boulder.config import load_config_file, normalize_config, validate_config
    from boulder.sim2stone_cli import main as sim2stone_main
    from boulder.validation import validate_normalized_config

    rc = sim2stone_main(
        [
            str(script),
            "-o",
            str(out_yaml),
            "--no-comments",
            "--mechanism",
            mechanism,
        ]
    )
    assert rc == 0
    assert out_yaml.is_file()

    if script_name == "nanosecond_pulse_discharge.py":
        assert "example_data/methane-plasma-pavan-2023.yaml" in out_yaml.read_text(
            encoding="utf-8"
        )

    cfg = load_config_file(str(out_yaml))
    normalized = normalize_config(cfg)
    validate_normalized_config(normalized)
    validated = validate_config(normalized)
    assert validated is not None
    assert "nodes" in validated
    assert "connections" in validated


@pytest.mark.integration
@pytest.mark.parametrize("script_name,mechanism", _DOWNLOAD_PARAMS)
def test_cantera_examples_headless_download_script_runs(
    tmp_path: Path, script_name: str, mechanism: str
) -> None:
    """YAML from sim2stone(example) yields a ``boulder --headless --download`` script that runs.

    Mirrors ``boulder config.yaml --headless --download out.py`` then executes
    ``python out.py`` with the YAML kept at the absolute path embedded in the script.
    """
    script = _EXAMPLES_DIR / script_name
    if not script.is_file():
        pytest.skip(f"{script_name} not found under docs/cantera_examples")

    if script_name == "nanosecond_pulse_discharge.py":
        import cantera as ct

        try:
            ct.Solution(mechanism)
        except (OSError, ValueError, RuntimeError) as exc:
            pytest.skip(f"Plasma mechanism not available ({mechanism}): {exc}")

    os.environ.setdefault("MPLBACKEND", "Agg")

    stone_yaml = (tmp_path / f"{Path(script_name).stem}.yaml").resolve()
    download_py = (tmp_path / "downloaded_network.py").resolve()

    from boulder.sim2stone_cli import main as sim2stone_main

    assert sim2stone_main(
        [
            str(script),
            "-o",
            str(stone_yaml),
            "--no-comments",
            "--mechanism",
            mechanism,
        ]
    ) == 0

    cmd_gen = [
        sys.executable,
        "-m",
        "boulder.cli",
        str(stone_yaml),
        "--headless",
        "--download",
        str(download_py),
    ]
    gen = subprocess.run(
        cmd_gen,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=str(_REPO_ROOT),
        env=_subprocess_env(),
    )
    assert gen.returncode == 0, (gen.stderr or "") + (gen.stdout or "")
    assert "Python code generated:" in (gen.stdout or "")
    assert download_py.is_file()

    with open(download_py, encoding="utf-8") as fh:
        body = fh.read()
    assert "from boulder.runner import BoulderRunner" in body
    assert "BoulderRunner.from_yaml" in body

    run = subprocess.run(
        [sys.executable, str(download_py)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=str(_REPO_ROOT),
        env=_subprocess_env(),
    )
    assert run.returncode == 0, (run.stderr or "") + (run.stdout or "")
    out = (run.stdout or "") + (run.stderr or "")
    assert "Simulation completed" in out or "Reactor" in out


def _agg_env() -> dict[str, str]:
    """Match Boulder CLI needs on Windows (emoji logs, Agg, Cantera data paths)."""
    return {
        **_subprocess_env(),
        "MPLBACKEND": "Agg",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }


@pytest.mark.parametrize("script_name,mechanism", _FIXTURES)
def test_boulder_headless_py_writes_valid_stone_yaml(
    tmp_path: Path, script_name: str, mechanism: str
) -> None:
    """``boulder <example.py> --headless --output-yaml`` writes YAML that ``boulder validate`` accepts."""
    script = _EXAMPLES_DIR / script_name
    if not script.is_file():
        pytest.skip(f"{script_name} not found under docs/cantera_examples")

    if script_name == "nanosecond_pulse_discharge.py":
        import cantera as ct

        try:
            ct.Solution(mechanism)
        except (OSError, ValueError, RuntimeError) as exc:
            pytest.skip(f"Plasma mechanism not available ({mechanism}): {exc}")

    stone_yaml = (tmp_path / f"{Path(script_name).stem}_boulder.yaml").resolve()
    conv = subprocess.run(
        [
            sys.executable,
            "-m",
            "boulder.cli",
            str(script),
            "--headless",
            "--output-yaml",
            str(stone_yaml),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        cwd=str(_REPO_ROOT),
        env=_agg_env(),
    )
    assert conv.returncode == 0, (conv.stderr or "") + (conv.stdout or "")
    assert stone_yaml.is_file()

    val = subprocess.run(
        [sys.executable, "-m", "boulder.cli", "validate", str(stone_yaml)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(_REPO_ROOT),
        env=_agg_env(),
    )
    assert val.returncode == 0, (val.stderr or "") + (val.stdout or "")


@pytest.mark.integration
@pytest.mark.parametrize("script_name,mechanism", _DOWNLOAD_PARAMS)
def test_boulder_headless_py_yaml_validate_download_run_roundtrip(
    tmp_path: Path, script_name: str, mechanism: str
) -> None:
    """After native .py→YAML, ``--headless --download`` then ``python`` completes (xfail where upstream fails)."""
    script = _EXAMPLES_DIR / script_name
    if not script.is_file():
        pytest.skip(f"{script_name} not found under docs/cantera_examples")

    if script_name == "nanosecond_pulse_discharge.py":
        import cantera as ct

        try:
            ct.Solution(mechanism)
        except (OSError, ValueError, RuntimeError) as exc:
            pytest.skip(f"Plasma mechanism not available ({mechanism}): {exc}")

    stone_yaml = (tmp_path / f"{Path(script_name).stem}_boulder.yaml").resolve()
    download_py = (tmp_path / f"{Path(script_name).stem}_downloaded.py").resolve()

    assert (
        subprocess.run(
            [
                sys.executable,
                "-m",
                "boulder.cli",
                str(script),
                "--headless",
                "--output-yaml",
                str(stone_yaml),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            cwd=str(_REPO_ROOT),
            env=_agg_env(),
        ).returncode
        == 0
    )

    assert (
        subprocess.run(
            [sys.executable, "-m", "boulder.cli", "validate", str(stone_yaml)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(_REPO_ROOT),
            env=_agg_env(),
        ).returncode
        == 0
    )

    gen = subprocess.run(
        [
            sys.executable,
            "-m",
            "boulder.cli",
            str(stone_yaml),
            "--headless",
            "--download",
            str(download_py),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        cwd=str(_REPO_ROOT),
        env=_agg_env(),
    )
    assert gen.returncode == 0, (gen.stderr or "") + (gen.stdout or "")
    assert "Python code generated:" in (gen.stdout or "")
    assert download_py.is_file()

    run = subprocess.run(
        [sys.executable, str(download_py)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        cwd=str(_REPO_ROOT),
        env=_agg_env(),
    )
    assert run.returncode == 0, (run.stderr or "") + (run.stdout or "")
    out = (run.stdout or "") + (run.stderr or "")
    assert "Simulation completed" in out or "Reactor" in out
