"""Summary builders receive the run's config on the runner path (#209)."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
import yaml

from boulder.summary_builder import (
    DefaultSummaryBuilder,
    SummaryBuilder,
    SummaryContext,
    get_summary_builder_registry,
)
from tests.test_runner import MINIMAL_YAML_CONTENT

ROW = {"label": "export", "value": 1.0}


class _ExportBuilder(SummaryBuilder):
    """Compatible only when the YAML carries an ``export`` block."""

    @property
    def builder_id(self) -> str:
        return "export-test"

    @property
    def name(self) -> str:
        return "Export test"

    def is_compatible(self, context: SummaryContext) -> bool:
        return bool((context.config or {}).get("export"))

    def build_summary(self, context: SummaryContext) -> List[Dict[str, Any]]:
        return [ROW]


@pytest.fixture
def export_builder():
    """Registry holding only the default builder and the test builder.

    Plugins installed in the environment may register always-compatible
    builders of their own (and the runner loads them); isolate from them.
    """
    registry = get_summary_builder_registry()
    saved = dict(registry.builders)
    builder = _ExportBuilder()
    registry.builders = {
        k: v for k, v in saved.items() if isinstance(v, DefaultSummaryBuilder)
    }
    registry.register(builder)
    yield builder
    registry.builders = saved


def _yaml(tmp_path) -> str:
    path = tmp_path / "export.yaml"
    path.write_text(
        MINIMAL_YAML_CONTENT + "\nexport:\n  kind: test\n", encoding="utf-8"
    )
    return str(path)


def test_runner_path_passes_config_to_summary_builders(tmp_path, export_builder):
    """BoulderRunner.run_headless: a builder keyed on the YAML's ``export`` block runs.

    Before the fix finalize_results handed builders ``{}`` on the runner path
    (only ``_download_config`` is set there), so ``is_compatible`` declined and
    no summary rows were produced.
    """
    from boulder.runner import BoulderRunner

    runner = BoulderRunner.from_yaml(_yaml(tmp_path))
    runner.run_headless(end_time=1e-3, dt=1e-4)
    converter = runner._ensure_converter()
    assert converter._last_config is None  # runner path: GUI snapshot unset
    results = converter.finalize_results([0.0], {})
    assert ROW in results["summary"]


def test_gui_path_config_unchanged(tmp_path, export_builder):
    """build_network sets ``_last_config``, which still feeds the builders."""
    from boulder.cantera_converter import DualCanteraConverter
    from boulder.config import normalize_config

    with open(_yaml(tmp_path), encoding="utf-8") as fh:
        config = normalize_config(yaml.safe_load(fh))
    converter = DualCanteraConverter()
    converter.build_network(config)
    results = converter.finalize_results([0.0], {})
    assert converter._last_config["export"] == {"kind": "test"}
    assert ROW in results["summary"]
