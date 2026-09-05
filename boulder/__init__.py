"""Boulder - A Cantera ReactorNet Visualization Tool."""

try:
    from .version import __version__
except ImportError:
    __version__ = "0.0.0+unknown"

from .config import STONE_FORMAT_VERSION, migrate_stone_config
from .lagrangian import LagrangianTrajectory
from .runner import BoulderRunner
from .schema_registry import (
    ReactorSchemaEntry,
    describe_kind,
    get_report_metadata_for_config,
    get_schema_entry,
    register_reactor_builder,
    register_reactor_unfolder,
    registered_kinds,
    validate_against_plugin_schemas,
)
from .simulation_result import SimulationResult, make_simulation_result
from .stage_network import CustomStageNetwork
from .staged_network import StagedReactorNet
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
    "STONE_FORMAT_VERSION",
    "migrate_stone_config",
    "ReactorSchemaEntry",
    "SimulationResult",
    "StagedReactorNet",
    "describe_kind",
    "get_report_metadata_for_config",
    "get_schema_entry",
    "make_simulation_result",
    "register_reactor_builder",
    "register_reactor_unfolder",
    "registered_kinds",
    "validate_against_plugin_schemas",
]
