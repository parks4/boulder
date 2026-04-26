"""Boulder - A Cantera ReactorNet Visualization Tool."""

__version__ = "0.5.0"

from .schema_registry import (
    ReactorSchemaEntry,
    describe_kind,
    get_report_metadata_for_config,
    get_schema_entry,
    register_reactor_builder,
    registered_kinds,
    validate_against_plugin_schemas,
)
from .lagrangian import LagrangianTrajectory
from .runner import BoulderRunner
from .simulation_result import SimulationResult, make_simulation_result
from .stage_network import CustomStageNetwork
from .validation import (
    METADATA_ALLOWED_KEYS,
    METADATA_MANDATORY_KEYS,
    METADATA_OPTIONAL_KEYS,
    MetadataModel,
)

__all__ = [
    "BoulderRunner",
    "LagrangianTrajectory",
    "CustomStageNetwork",
    "METADATA_ALLOWED_KEYS",
    "METADATA_MANDATORY_KEYS",
    "METADATA_OPTIONAL_KEYS",
    "MetadataModel",
    "ReactorSchemaEntry",
    "SimulationResult",
    "describe_kind",
    "get_report_metadata_for_config",
    "get_schema_entry",
    "make_simulation_result",
    "register_reactor_builder",
    "registered_kinds",
    "validate_against_plugin_schemas",
]
