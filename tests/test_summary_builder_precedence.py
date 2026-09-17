"""A registered plugin builder must win over the always-compatible default."""

from __future__ import annotations

from typing import Any, Dict, List, cast

import cantera as ct

from boulder.summary_builder import (
    DefaultSummaryBuilder,
    SummaryBuilder,
    SummaryBuilderRegistry,
    SummaryContext,
)


class _PickyBuilder(SummaryBuilder):
    """Compatible only when the config asks for it."""

    @property
    def builder_id(self) -> str:
        return "picky"

    @property
    def name(self) -> str:
        return "Picky"

    def is_compatible(self, context: SummaryContext) -> bool:
        return bool((context.config or {}).get("picky"))

    def build_summary(self, context: SummaryContext) -> List[Dict[str, Any]]:
        return [{"label": "picky", "value": 1.0}]


def _context(config: Dict[str, Any] | None) -> SummaryContext:
    return SummaryContext(
        # Any non-None network: no builder under test touches it.
        simulation=cast(ct.ReactorNet, object()),
        config=config,
        simulation_data=None,
        output_config={},
    )


def _registry() -> SummaryBuilderRegistry:
    registry = SummaryBuilderRegistry()
    # Registration order as it happens in practice: Boulder's default first,
    # plugins afterwards, because plugins load later.
    registry.register(DefaultSummaryBuilder())
    registry.register(_PickyBuilder())
    return registry


def test_a_compatible_plugin_outranks_the_default():
    """Otherwise no plugin builder could ever be selected.

    The default builder is compatible with every simulation and registers
    first, so ordering by registration alone always picked it.
    """
    compatible = _registry().get_compatible_builders(_context({"picky": True}))

    assert [b.builder_id for b in compatible] == ["picky", "default-summary-builder"]


def test_the_default_still_answers_when_no_plugin_claims_the_run():
    compatible = _registry().get_compatible_builders(_context({}))

    assert [b.builder_id for b in compatible] == ["default-summary-builder"]


class _StageAwareBuilder(SummaryBuilder):
    """Reports one row per stage, which only the stage networks can supply."""

    @property
    def builder_id(self) -> str:
        return "stage-aware"

    @property
    def name(self) -> str:
        return "Stage aware"

    def is_compatible(self, context: SummaryContext) -> bool:
        return bool(context.stage_networks)

    def build_summary(self, context: SummaryContext) -> List[Dict[str, Any]]:
        return [{"label": stage, "value": 1.0} for stage in context.stage_networks]


def test_stage_networks_reach_the_builder():
    """The visualization network is flat, so a stage's own solver is the only
    place a stage-level quantity can come from.
    """
    from boulder.summary_builder import (
        build_summary_from_simulation,
        register_summary_builder,
    )

    register_summary_builder(_StageAwareBuilder())

    rows = build_summary_from_simulation(
        simulation=cast(ct.ReactorNet, object()),
        config={},
        simulation_data={},
        builder_id="stage-aware",
        stage_networks={"torch_stage": object(), "reactor_stage": object()},
    )

    assert [r["label"] for r in rows] == ["torch_stage", "reactor_stage"]


def test_stage_networks_default_to_empty_for_a_single_stage_solve():
    assert SummaryContext().stage_networks == {}
