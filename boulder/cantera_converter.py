import importlib
import json
import math
import os
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import cantera as ct  # type: ignore

from .config import CANTERA_MECHANISM
from .sankey import generate_sankey_input_from_sim
from .verbose_utils import get_verbose_logger, is_verbose_mode

logger = get_verbose_logger(__name__)


# Custom builder/hook types
ReactorBuilder = Callable[
    [Union["CanteraConverter", "DualCanteraConverter"], Dict[str, Any]], ct.Reactor
]
ConnectionBuilder = Callable[
    [Union["CanteraConverter", "DualCanteraConverter"], Dict[str, Any]], ct.FlowDevice
]
PostBuildHook = Callable[
    [Union["CanteraConverter", "DualCanteraConverter"], Dict[str, Any]], None
]


@dataclass
class BoulderPlugins:
    """A container for discovered Boulder plugins."""

    reactor_builders: Dict[str, ReactorBuilder] = field(default_factory=dict)
    connection_builders: Dict[str, ConnectionBuilder] = field(default_factory=dict)
    post_build_hooks: List[PostBuildHook] = field(default_factory=list)


# Global cache to ensure plugins are discovered only once
_PLUGIN_CACHE: Optional[BoulderPlugins] = None


def get_plugins() -> BoulderPlugins:
    """Discover and load all Boulder plugins, returning them in a container.

    This function is idempotent and caches the results.
    """
    global _PLUGIN_CACHE
    if _PLUGIN_CACHE is not None:
        if is_verbose_mode():
            logger.info("Using cached plugins")
        return _PLUGIN_CACHE

    if is_verbose_mode():
        logger.info("Discovering Boulder plugins...")
    plugins = BoulderPlugins()

    # Discover from entry points
    try:
        eps = entry_points()
        eps_group = getattr(eps, "select", None)
        selected = (
            eps_group(group="boulder.plugins")
            if eps_group
            else eps.get("boulder.plugins", [])
        )
        for ep in selected:
            try:
                plugin_func = ep.load()
                if callable(plugin_func):
                    plugin_func(plugins)
            except Exception as e:
                logger.warning(f"Failed to load plugin entry point {ep}: {e}")
    except Exception as e:
        logger.debug(f"Entry point discovery failed: {e}")

    # Discover from environment variable
    raw = os.environ.get("BOULDER_PLUGINS", "").strip()
    if raw:
        for mod_name in [
            m.strip() for m in raw.replace(";", ",").split(",") if m.strip()
        ]:
            try:
                mod = importlib.import_module(mod_name)
                registrar = getattr(mod, "register_plugins", None)
                if callable(registrar):
                    registrar(plugins)
            except Exception as e:
                logger.warning(
                    f"Failed to import BOULDER_PLUGINS module '{mod_name}': {e}"
                )

    _PLUGIN_CACHE = plugins

    if is_verbose_mode():
        logger.info(
            f"Plugin discovery complete: {len(plugins.reactor_builders)} reactor builders, "
            f"{len(plugins.connection_builders)} connection builders, "
            f"{len(plugins.post_build_hooks)} post-build hooks"
        )

    return plugins


class CanteraConverter:
    def __init__(
        self,
        mechanism: Optional[str] = None,
        plugins: Optional[BoulderPlugins] = None,
    ) -> None:
        # Use provided mechanism or fall back to config default
        self.mechanism = mechanism or CANTERA_MECHANISM
        self.plugins = plugins or get_plugins()
        try:
            self.gas = ct.Solution(self.mechanism)
        except Exception as e:
            raise ValueError(f"Failed to load mechanism '{self.mechanism}': {e}")
        self.reactors: Dict[str, ct.Reactor] = {}
        self.reactor_meta: Dict[str, Dict[str, Any]] = {}
        self.connections: Dict[str, ct.FlowDevice] = {}
        self.walls: Dict[str, Any] = {}
        self.network: ct.ReactorNet = None
        self.last_network: ct.ReactorNet = (
            None  # Store the last successfully built network
        )

    def parse_composition(self, comp_str: str) -> Dict[str, float]:
        """Convert composition string to dictionary of species and mole fractions."""
        comp_dict = {}
        for pair in comp_str.split(","):
            species, value = pair.split(":")
            comp_dict[species] = float(value)
        return comp_dict

    def create_reactor(self, reactor_config: Dict[str, Any]) -> ct.Reactor:
        """Create a Cantera reactor from configuration."""
        reactor_type = reactor_config["type"]
        props = reactor_config["properties"]

        # Set gas state
        self.gas.TPX = (
            props.get("temperature", 300),
            props.get("pressure", 101325),
            self.parse_composition(props.get("composition", "N2:1")),
        )

        # Custom builder extension point
        if reactor_type in self.plugins.reactor_builders:
            reactor = self.plugins.reactor_builders[reactor_type](self, reactor_config)
        elif reactor_type == "IdealGasReactor":
            reactor = ct.IdealGasReactor(self.gas)
        elif reactor_type == "IdealGasConstPressureReactor":
            reactor = ct.IdealGasConstPressureReactor(self.gas)
        elif reactor_type == "IdealGasConstPressureMoleReactor":
            reactor = ct.IdealGasConstPressureMoleReactor(self.gas)
        elif reactor_type == "Reservoir":
            reactor = ct.Reservoir(self.gas)
        else:
            raise ValueError(f"Unsupported reactor type: {reactor_type}")

        # Set the reactor name to match the config ID
        reactor.name = reactor_config["id"]

        # Optional grouping: propagate group name to reactor for downstream tools
        props_group = reactor_config.get("properties", {}).get("group")
        if props_group is None:
            props_group = reactor_config.get("properties", {}).get("group_name", "")
        try:
            # Cantera Reactors allow arbitrary attributes in Python layer
            reactor.group_name = str(props_group or "")
        except Exception:
            # Best-effort; ignore if backend forbids attribute
            pass

        return reactor

    def create_connection(self, conn_config: Dict[str, Any]):
        """Create a Cantera connection (flow device or wall) from configuration."""
        conn_type = conn_config["type"]
        props = conn_config["properties"]

        # Ensure source/target exist (create placeholder Reservoirs if needed)
        src_id = conn_config["source"]
        tgt_id = conn_config["target"]
        if src_id not in self.reactors:
            # Create a benign reservoir for external sources like 'Electricity'/'Losses'
            self.gas.TPX = (300, 101325, {"N2": 1.0})
            self.reactors[src_id] = ct.Reservoir(self.gas)
            self.reactors[src_id].name = src_id
        if tgt_id not in self.reactors:
            self.gas.TPX = (300, 101325, {"N2": 1.0})
            self.reactors[tgt_id] = ct.Reservoir(self.gas)
            self.reactors[tgt_id].name = tgt_id
        source = self.reactors[src_id]
        target = self.reactors[tgt_id]

        # Custom builder extension point
        if conn_type in self.plugins.connection_builders:
            flow_device = self.plugins.connection_builders[conn_type](self, conn_config)
        elif conn_type == "MassFlowController":
            # Default MassFlowController implementation
            mfc = ct.MassFlowController(source, target)
            mfc.mass_flow_rate = float(props.get("mass_flow_rate", 0.1))
        elif conn_type == "Valve":
            valve = ct.Valve(source, target)
            valve.valve_coeff = float(props.get("valve_coeff", 1.0))
        elif conn_type == "Wall":
            # Handle walls as energy connections (e.g., torch power or losses)
            electric_power_kW = float(props.get("electric_power_kW", 0.0))
            torch_eff = float(props.get("torch_eff", 1.0))
            gen_eff = float(props.get("gen_eff", 1.0))
            # Net heat rate into the target from the source (W)
            Q_watts = electric_power_kW * 1e3 * torch_eff * gen_eff
            wall = ct.Wall(source, target, A=1.0, Q=Q_watts, name=conn_config["id"])
            self.walls[conn_config["id"]] = wall
            return wall
        else:
            raise ValueError(f"Unsupported connection type: {conn_type}")

        return flow_device

    def build_network(
        self, config: Dict[str, Any]
    ) -> Tuple[ct.ReactorNet, Dict[str, Any]]:
        """Build a ReactorNet from configuration and return network and results."""
        # Clear previous state
        self.reactors.clear()
        self.connections.clear()

        # Create reactors (built-ins or via registered custom builders)
        for node in config["nodes"]:
            r = self.create_reactor(node)
            r.name = node["id"]
            self.reactors[node["id"]] = r

        # Create connections
        for conn in config["connections"]:
            if conn["type"] in ("MassFlowController", "Valve"):
                self.connections[conn["id"]] = self.create_connection(conn)
            elif conn["type"] == "Wall":
                # Create and track walls separately
                self.create_connection(conn)

        # Create network - include all Cantera reactors (exclude pure Reservoirs)
        reactor_list = [
            r for r in self.reactors.values() if not isinstance(r, ct.Reservoir)
        ]
        if not reactor_list:
            raise ValueError("No IdealGasReactors found in the network")

        self.network = ct.ReactorNet(reactor_list)

        # Configure solver for better stability
        self.network.rtol = 1e-6  # Relaxed relative tolerance
        self.network.atol = 1e-8  # Relaxed absolute tolerance
        self.network.max_steps = 10000  # Increase maximum steps

        # Apply post-build hooks for custom modifications
        for hook in self.plugins.post_build_hooks:
            hook(self, config)

        # Run simulation with smaller time steps
        times: List[float] = []

        # Per-reactor capture using Cantera's native SolutionArray
        # Note: We serialize minimal arrays for frontend consumption; no HDF needed here
        reactors_series: Dict[str, Dict[str, Any]] = {}
        sol_arrays: Dict[str, ct.SolutionArray] = {}
        for reactor in reactor_list:
            reactor_id = getattr(reactor, "name", "") or str(id(reactor))
            sol_arrays[reactor_id] = ct.SolutionArray(self.gas, shape=(0,))
            reactors_series[reactor_id] = {
                "T": [],
                "P": [],
                "X": {s: [] for s in self.gas.species_names},
            }

        # Use smaller time steps and shorter simulation time
        for t in range(0, 10, 1):  # Simulate for 10 seconds with 1-second steps
            try:
                self.network.advance(t)
                times.append(t)
                # Append state for each reactor
                for reactor in reactor_list:
                    reactor_id = getattr(reactor, "name", "") or str(id(reactor))
                    # Record to SolutionArray (native Cantera capture)
                    sol_arrays[reactor_id].append(
                        T=reactor.thermo.T,
                        P=reactor.thermo.P,
                        X=reactor.thermo.X,
                    )
                    # Also keep a minimal numeric representation for the UI
                    reactors_series[reactor_id]["T"].append(reactor.thermo.T)
                    reactors_series[reactor_id]["P"].append(reactor.thermo.P)
                    for species_name, x_value in zip(
                        self.gas.species_names, reactor.thermo.X
                    ):
                        reactors_series[reactor_id]["X"][species_name].append(
                            float(x_value)
                        )
            except Exception as e:
                logger.warning(f"Warning at t={t}: {str(e)}")
                # If we hit an error, duplicate the last successful values
                if times:
                    times.append(t)
                    for reactor in reactor_list:
                        reactor_id = getattr(reactor, "name", "") or str(id(reactor))
                        # Repeat last state in SolutionArray and numeric series
                        last_idx = -1
                        last_T = reactors_series[reactor_id]["T"][last_idx]
                        last_P = reactors_series[reactor_id]["P"][last_idx]
                        last_X = [
                            reactors_series[reactor_id]["X"][s][last_idx]
                            for s in self.gas.species_names
                        ]
                        sol_arrays[reactor_id].append(T=last_T, P=last_P, X=last_X)
                        reactors_series[reactor_id]["T"].append(last_T)
                        reactors_series[reactor_id]["P"].append(last_P)
                        for species_name, x_value in zip(
                            self.gas.species_names, last_X
                        ):
                            reactors_series[reactor_id]["X"][species_name].append(
                                float(x_value)
                            )

        results: Dict[str, Any] = {
            "time": times,
            # New structure: per-reactor series captured via SolutionArray, serialized minimally
            "reactors": reactors_series,
        }

        # Store the successful network for later use (e.g., Sankey diagrams)
        self.last_network = self.network

        # Generate Sankey data
        try:
            links, nodes = generate_sankey_input_from_sim(
                self.last_network,
                show_species=["H2", "CH4"],
                verbose=False,
                mechanism=self.mechanism,
            )
            results["sankey_links"] = links
            results["sankey_nodes"] = nodes
        except Exception as e:
            logger.error(f"Error generating Sankey diagram: {e}")
            results["sankey_links"] = None
            results["sankey_nodes"] = None

        return self.network, results

    def load_config(self, filepath: str) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        with open(filepath, "r") as f:
            return json.load(f)


class DualCanteraConverter:
    def __init__(
        self,
        mechanism: Optional[str] = None,
        plugins: Optional[BoulderPlugins] = None,
    ) -> None:
        """Initialize DualCanteraConverter.

        Executes the Cantera network as before.
        Simultaneously builds a string of Python code that, if run, will produce the same objects and results.
        Returns (network, results, code_str) from build_network_and_code(config).
        """
        # Use provided mechanism or fall back to config default
        self.mechanism = mechanism or CANTERA_MECHANISM
        try:
            self.gas = ct.Solution(self.mechanism)
        except Exception as e:
            raise ValueError(f"Failed to load mechanism '{self.mechanism}': {e}")
        self.plugins = plugins or get_plugins()
        self.reactors: Dict[str, ct.Reactor] = {}
        self.reactor_meta: Dict[str, Dict[str, Any]] = {}
        self.connections: Dict[str, ct.FlowDevice] = {}
        self.walls: Dict[str, Any] = {}
        self.network: ct.ReactorNet = None
        self.code_lines: List[str] = []
        self.last_network: ct.ReactorNet = (
            None  # Store the last successfully built network
        )

    def parse_composition(self, comp_str: str) -> Dict[str, float]:
        comp_dict = {}
        for pair in comp_str.split(","):
            species, value = pair.split(":")
            comp_dict[species] = float(value)
        return comp_dict

    def build_network_and_code(
        self, config: Dict[str, Any]
    ) -> Tuple[Any, Dict[str, Any], str]:
        self.code_lines = []
        self.code_lines.append("import cantera as ct")
        self.code_lines.append(f"gas = ct.Solution('{self.mechanism}')")
        try:
            self.gas = ct.Solution(self.mechanism)
        except Exception as e:
            logger.error(
                f"[ERROR] Failed to reload mechanism '{self.mechanism}' in build_network_and_code: {e}"
            )
            # Note: self.gas should already be set from __init__, so this is just for consistency
        self.reactors = {}
        self.connections = {}
        self.network = None

        # Reactors
        for node in config["nodes"]:
            rid = node["id"]
            typ = node["type"]
            props = node["properties"]
            temp = props.get("temperature", 300)
            pres = props.get("pressure", 101325)
            compo = props.get("composition", "N2:1")
            self.code_lines.append(f"gas.TPX = ({temp}, {pres}, '{compo}')")
            self.gas.TPX = (temp, pres, self.parse_composition(compo))
            # Plugin-backed custom reactor types
            if typ in self.plugins.reactor_builders:
                reactor = self.plugins.reactor_builders[typ](self, node)
                reactor.name = rid
                self.reactors[rid] = reactor
                try:
                    self.reactors[rid].group_name = str(
                        props.get("group", props.get("group_name", ""))
                    )
                except Exception:
                    pass
                # Code gen: note plugin usage
                self.code_lines.append(f"# Plugin reactor {typ} -> created as '{rid}'")
            elif typ == "IdealGasReactor":
                self.code_lines.append(f"{rid} = ct.IdealGasReactor(gas)")
                self.code_lines.append(f"{rid}.name = '{rid}'")
                self.reactors[rid] = ct.IdealGasReactor(self.gas)
                self.reactors[rid].name = rid
                try:
                    self.reactors[rid].group_name = str(
                        props.get("group", props.get("group_name", ""))
                    )
                    self.code_lines.append(
                        f"{rid}.group_name = '{props.get('group', props.get('group_name', ''))}'"
                    )
                except Exception:
                    pass
            elif typ == "Reservoir":
                self.code_lines.append(f"{rid} = ct.Reservoir(gas)")
                self.code_lines.append(f"{rid}.name = '{rid}'")
                self.reactors[rid] = ct.Reservoir(self.gas)
                self.reactors[rid].name = rid
                try:
                    self.reactors[rid].group_name = str(
                        props.get("group", props.get("group_name", ""))
                    )
                    self.code_lines.append(
                        f"{rid}.group_name = '{props.get('group', props.get('group_name', ''))}'"
                    )
                except Exception:
                    pass
            else:
                self.code_lines.append(f"# Unsupported reactor type: {typ}")
                raise ValueError(f"Unsupported reactor type: {typ}")

        # Connections
        for conn in config["connections"]:
            cid = conn["id"]
            typ = conn["type"]
            src = conn["source"]
            tgt = conn["target"]
            props = conn["properties"]
            # Plugin-backed custom connections
            if typ in self.plugins.connection_builders:
                device = self.plugins.connection_builders[typ](self, conn)
                self.connections[cid] = device
                self.code_lines.append(
                    f"# Plugin connection {typ} -> created as '{cid}'"
                )
            elif typ == "MassFlowController":
                mfr = float(props.get("mass_flow_rate", 0.1))
                self.code_lines.append(f"{cid} = ct.MassFlowController({src}, {tgt})")
                self.code_lines.append(f"{cid}.mass_flow_rate = {mfr}")
                self.connections[cid] = ct.MassFlowController(
                    self.reactors[src], self.reactors[tgt]
                )
                self.connections[cid].mass_flow_rate = mfr
            elif typ == "Valve":
                coeff = float(props.get("valve_coeff", 1.0))
                self.code_lines.append(f"{cid} = ct.Valve({src}, {tgt})")
                self.code_lines.append(f"{cid}.valve_coeff = {coeff}")
                self.connections[cid] = ct.Valve(self.reactors[src], self.reactors[tgt])
                self.connections[cid].valve_coeff = coeff
            elif typ == "Wall":
                # Handle walls as energy connections (e.g., torch power or losses)
                electric_power_kW = float(props.get("electric_power_kW", 0.0))
                torch_eff = float(props.get("torch_eff", 1.0))
                gen_eff = float(props.get("gen_eff", 1.0))
                Q_watts = electric_power_kW * 1e3 * torch_eff * gen_eff
                self.code_lines.append(
                    f"{cid} = ct.Wall({src}, {tgt}, A=1.0, Q={Q_watts}, name='{cid}')"
                )
                wall = ct.Wall(
                    self.reactors[src], self.reactors[tgt], A=1.0, Q=Q_watts, name=cid
                )
                self.walls[cid] = wall
                # Note: Walls are not flow devices, so we track them separately
            else:
                self.code_lines.append(f"# Unsupported connection type: {typ}")
                raise ValueError(f"Unsupported connection type: {typ}")

        # ReactorNet (include all non-Reservoir reactors)
        reactor_ids = [
            rid for rid, r in self.reactors.items() if not isinstance(r, ct.Reservoir)
        ]
        self.code_lines.append(f"network = ct.ReactorNet([{', '.join(reactor_ids)}])")
        self.network = ct.ReactorNet([self.reactors[rid] for rid in reactor_ids])
        self.code_lines.append("network.rtol = 1e-6")
        self.code_lines.append("network.atol = 1e-8")
        self.code_lines.append("network.max_steps = 10000")
        self.network.rtol = 1e-6
        self.network.atol = 1e-8
        self.network.max_steps = 10000

        # Apply post-build hooks from plugins
        for hook in self.plugins.post_build_hooks:
            hook(self, config)

        # Simulation loop (example)
        self.code_lines.append(
            """# Run the simulation\nfor t in range(0, 10, 1):\n    network.advance(t)\n    """
            + """print(f\"t={t}, T={[r.thermo.T for r in network.reactors]}\")"""
        )
        # TOOD: add dual code directly in the simulation loop too.

        # Run simulation (same as CanteraConverter)
        times: List[float] = []
        reactor_list = [self.reactors[rid] for rid in reactor_ids]

        # Per-reactor capture using SolutionArray
        reactors_series: Dict[str, Dict[str, Any]] = {}
        sol_arrays: Dict[str, ct.SolutionArray] = {}
        for reactor in reactor_list:
            reactor_id = getattr(reactor, "name", "") or str(id(reactor))
            sol_arrays[reactor_id] = ct.SolutionArray(self.gas, shape=(0,))
            reactors_series[reactor_id] = {
                "T": [],
                "P": [],
                "X": {s: [] for s in self.gas.species_names},
            }
        for t in range(0, 10, 1):
            try:
                self.network.advance(t)
            except Exception as e:
                # Fail fast for Dual converter so the GUI shows the error immediately
                raise RuntimeError(f"Cantera advance failed at t={t}s: {e}") from e

            times.append(t)
            for reactor in reactor_list:
                reactor_id = getattr(reactor, "name", "") or str(id(reactor))
                T = reactor.thermo.T
                P = reactor.thermo.P
                X_vec = reactor.thermo.X
                # Detect non-finite states early and fail fast
                if not (
                    math.isfinite(T)
                    and math.isfinite(P)
                    and all(math.isfinite(float(x)) for x in X_vec)
                ):
                    raise RuntimeError(
                        f"Non-finite state detected at t={t}s for reactor '{reactor_id}'"
                    )
                sol_arrays[reactor_id].append(T=T, P=P, X=X_vec)
                reactors_series[reactor_id]["T"].append(T)
                reactors_series[reactor_id]["P"].append(P)
                for species_name, x_value in zip(self.gas.species_names, X_vec):
                    reactors_series[reactor_id]["X"][species_name].append(
                        float(x_value)
                    )
        results: Dict[str, Any] = {
            "time": times,
            "reactors": reactors_series,
        }

        # Store the successful network for later use (e.g., Sankey diagrams)
        self.last_network = self.network

        # Generate Sankey data
        try:
            links, nodes = generate_sankey_input_from_sim(
                self.last_network,
                show_species=["H2", "CH4"],
                verbose=False,
                mechanism=self.mechanism,
            )
            results["sankey_links"] = links
            results["sankey_nodes"] = nodes
        except Exception as e:
            logger.error(f"Error generating Sankey diagram: {e}")
            results["sankey_links"] = None
            results["sankey_nodes"] = None

        return self.network, results, "\n".join(self.code_lines)
