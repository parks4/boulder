"""A registered plugin builder must win over the always-compatible default."""

from __future__ import annotations

from typing import Any, Dict, List

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
        simulation=object(),  # any non-None network
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
