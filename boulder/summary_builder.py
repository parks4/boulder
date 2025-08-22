"""Summary Builder System for Boulder.

This module provides the base classes and infrastructure for creating
custom summary builders that can process simulation results and generate
summary data for display in Boulder's output panes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import cantera as ct


@dataclass
class SummaryContext:
    """Context information passed to summary builders."""

    # Current simulation object (ReactorNet)
    simulation: Optional[ct.ReactorNet] = None

    # Configuration data
    config: Optional[Dict[str, Any]] = None

    # Additional simulation data
    simulation_data: Optional[Dict[str, Any]] = None

    # Output configuration from YAML
    output_config: Optional[Dict[str, Any]] = None


class SummaryBuilder(ABC):
    """Base class for Summary builders.

    Summary builders process simulation results and generate summary data
    that can be displayed in Boulder's Summary output pane.
    """

    @property
    @abstractmethod
    def builder_id(self) -> str:
        """Unique identifier for this summary builder."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for this summary builder."""
        pass

    def is_compatible(self, context: SummaryContext) -> bool:
        """Check if this builder is compatible with the given simulation context.

        Args:
            context: Current context information

        Returns
        -------
            True if the builder can process this simulation, False otherwise
        """
        return context.simulation is not None

    @abstractmethod
    def build_summary(self, context: SummaryContext) -> List[Dict[str, Any]]:
        """Build summary data from the simulation context.

        Args:
            context: Current context information

        Returns
        -------
            List of summary entries, each containing:
            - reactor: reactor name (optional)
            - quantity: quantity name
            - label: display label
            - value: numeric value or string
            - unit: unit string (optional)
        """
        pass


class DefaultSummaryBuilder(SummaryBuilder):
    """Default summary builder that extracts basic reactor properties."""

    @property
    def builder_id(self) -> str:
        return "default-summary-builder"

    @property
    def name(self) -> str:
        return "Default Summary Builder"

    def build_summary(self, context: SummaryContext) -> List[Dict[str, Any]]:
        """Build default summary from reactor states."""
        summary: List[Dict[str, Any]] = []

        if not context.simulation:
            return summary

        # Extract basic properties from each reactor
        for reactor in context.simulation.reactors:
            reactor_name = getattr(reactor, "name", f"Reactor_{id(reactor)}")

            # Temperature
            summary.append(
                {
                    "reactor": reactor_name,
                    "quantity": "temperature",
                    "label": f"{reactor_name} Temperature",
                    "value": reactor.T,
                    "unit": "K",
                }
            )

            # Pressure
            summary.append(
                {
                    "reactor": reactor_name,
                    "quantity": "pressure",
                    "label": f"{reactor_name} Pressure",
                    "value": reactor.thermo.P,
                    "unit": "Pa",
                }
            )

            # Volume (if available)
            if hasattr(reactor, "volume"):
                summary.append(
                    {
                        "reactor": reactor_name,
                        "quantity": "volume",
                        "label": f"{reactor_name} Volume",
                        "value": reactor.volume,
                        "unit": "m³",
                    }
                )

        return summary


@dataclass
class SummaryBuilderRegistry:
    """Registry for Summary Builder plugins."""

    builders: Dict[str, SummaryBuilder] = field(default_factory=dict)

    def register(self, builder: SummaryBuilder) -> None:
        """Register a new summary builder."""
        if builder.builder_id in self.builders:
            raise ValueError(
                f"Builder with ID '{builder.builder_id}' already registered"
            )

        self.builders[builder.builder_id] = builder

    def get_builder(self, builder_id: str) -> Optional[SummaryBuilder]:
        """Get a builder by its ID."""
        return self.builders.get(builder_id)

    def get_compatible_builders(self, context: SummaryContext) -> List[SummaryBuilder]:
        """Get list of builders compatible with the given context."""
        return [
            builder
            for builder in self.builders.values()
            if builder.is_compatible(context)
        ]


# Global registry instance
_summary_builder_registry = SummaryBuilderRegistry()


def get_summary_builder_registry() -> SummaryBuilderRegistry:
    """Get the global summary builder registry."""
    return _summary_builder_registry


def register_summary_builder(builder: SummaryBuilder) -> None:
    """Register a summary builder with the global registry."""
    _summary_builder_registry.register(builder)


def build_summary_from_simulation(
    simulation: ct.ReactorNet,
    config: Optional[Dict[str, Any]] = None,
    simulation_data: Optional[Dict[str, Any]] = None,
    builder_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build summary data from a simulation using the specified or default builder.

    Args:
        simulation: Cantera ReactorNet simulation
        config: Configuration dictionary
        simulation_data: Additional simulation data
        builder_id: ID of specific builder to use, or None for default

    Returns
    -------
        List of summary entries
    """
    registry = get_summary_builder_registry()

    # Create context
    output_config = config.get("output", {}) if config else {}
    context = SummaryContext(
        simulation=simulation,
        config=config,
        simulation_data=simulation_data,
        output_config=output_config,
    )

    # Get builder
    if builder_id:
        builder = registry.get_builder(builder_id)
        if not builder:
            raise ValueError(f"Summary builder '{builder_id}' not found")
        if not builder.is_compatible(context):
            raise ValueError(
                f"Summary builder '{builder_id}' is not compatible with this simulation"
            )
    else:
        # Use first compatible builder, or default
        compatible_builders = registry.get_compatible_builders(context)
        if compatible_builders:
            builder = compatible_builders[0]
        else:
            # Fall back to default builder
            builder = DefaultSummaryBuilder()

    return builder.build_summary(context)


# Register default builder at import time
register_summary_builder(DefaultSummaryBuilder())
