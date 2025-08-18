import importlib
import math
import os
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, Callable, Dict, List, Optional, Tuple

import cantera as ct  # type: ignore

from .config import CANTERA_MECHANISM
from .sankey import generate_sankey_input_from_sim
from .verbose_utils import get_verbose_logger, is_verbose_mode

logger = get_verbose_logger(__name__)


# Custom builder/hook types
ReactorBuilder = Callable[["DualCanteraConverter", Dict[str, Any]], ct.Reactor]
ConnectionBuilder = Callable[["DualCanteraConverter", Dict[str, Any]], ct.FlowDevice]
PostBuildHook = Callable[["DualCanteraConverter", Dict[str, Any]], None]


@dataclass
class BoulderPlugins:
    """A container for discovered Boulder plugins."""

    reactor_builders: Dict[str, ReactorBuilder] = field(default_factory=dict)
    connection_builders: Dict[str, ConnectionBuilder] = field(default_factory=dict)
    post_build_hooks: List[PostBuildHook] = field(default_factory=list)
    mechanism_path_resolver: Optional[Callable[[str], str]] = None


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


# class CanteraConverter:
#    """Former Cantera converter lived there, now fully replaced by DualCanteraConverter
#    which generates code in parallel to solving the simulation
#    """"
class DualCanteraConverter:
    """Unified Cantera converter with streaming simulation capabilities."""

    def __init__(
        self,
        mechanism: Optional[str] = None,
        plugins: Optional[BoulderPlugins] = None,
    ) -> None:
        """Initialize CanteraConverter.

        Executes the Cantera network with streaming capabilities.
        Simultaneously builds a string of Python code that, if run, will produce the same objects and results.
        """
        # Use provided mechanism or fall back to config default
        self.mechanism = mechanism or CANTERA_MECHANISM
        self.plugins = plugins or get_plugins()
        try:
            # Use plugin mechanism path resolver if available
            if self.plugins.mechanism_path_resolver:
                resolved_mechanism = self.plugins.mechanism_path_resolver(
                    self.mechanism
                )
            else:
                resolved_mechanism = self.mechanism
            self.gas = ct.Solution(resolved_mechanism)
        except Exception as e:
            raise ValueError(f"Failed to load mechanism '{self.mechanism}': {e}")
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

    def build_network(self, config: Dict[str, Any]) -> ct.ReactorNet:
        """Build the Cantera network without running simulation."""
        self.code_lines = []
        self.code_lines.append("import cantera as ct")
        self.code_lines.append(f"gas = ct.Solution('{self.mechanism}')")
        try:
            self.gas = ct.Solution(self.mechanism)
        except Exception as e:
            logger.error(
                f"[ERROR] Failed to reload mechanism '{self.mechanism}' in build_network: {e}"
            )
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
            elif typ == "IdealGasConstPressureReactor":
                self.code_lines.append(f"{rid} = ct.IdealGasConstPressureReactor(gas)")
                self.code_lines.append(f"{rid}.name = '{rid}'")
                self.reactors[rid] = ct.IdealGasConstPressureReactor(self.gas)
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
            elif typ == "IdealGasConstPressureMoleReactor":
                self.code_lines.append(
                    f"{rid} = ct.IdealGasConstPressureMoleReactor(gas)"
                )
                self.code_lines.append(f"{rid}.name = '{rid}'")
                self.reactors[rid] = ct.IdealGasConstPressureMoleReactor(self.gas)
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
            elif typ == "IdealGasMoleReactor":
                # Available in Cantera 3.x
                self.code_lines.append(f"{rid} = ct.IdealGasMoleReactor(gas)")
                self.code_lines.append(f"{rid}.name = '{rid}'")
                self.reactors[rid] = ct.IdealGasMoleReactor(self.gas)  # type: ignore[attr-defined]
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
                # After validation, electric_power_kW is converted to kilowatts if it had units
                electric_power_kW = float(props.get("electric_power_kW", 0.0))
                torch_eff = float(props.get("torch_eff", 1.0))
                gen_eff = float(props.get("gen_eff", 1.0))
                # Convert from kW to W
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

        return self.network

    def run_streaming_simulation(
        self,
        simulation_time: float = 10.0,
        time_step: float = 1.0,
        progress_callback=None,
    ) -> Tuple[Dict[str, Any], str]:
        """Run simulation with streaming progress updates."""
        if self.network is None:
            raise RuntimeError("Network not built. Call build_network() first.")

        # Add simulation loop code generation
        sim_time = int(simulation_time)
        step_time = int(time_step)
        self.code_lines.append(
            f"""# Run the simulation\nfor t in range(0, {sim_time}, {step_time}):\n    network.advance(t)\n    """
            + """print(f\"t={t}, T={[r.thermo.T for r in network.reactors]}\")"""
        )

        # Initialize data structures
        times: List[float] = []
        reactor_list = [
            r for r in self.reactors.values() if not isinstance(r, ct.Reservoir)
        ]

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

        # Simulation loop with streaming updates
        current_time = 0.0
        while current_time < simulation_time:
            try:
                self.network.advance(current_time)
            except Exception as e:
                # Log warning but continue with partial results
                logger.warning(f"Cantera advance failed at t={current_time}s: {e}")
                if len(times) == 0:
                    # If we haven't captured any data yet, this is a real failure
                    raise RuntimeError(
                        f"Cantera advance failed at t={current_time}s: {e}"
                    ) from e
                # Otherwise, break and return partial results
                logger.warning(f"Returning partial results up to t={times[-1]}s")
                break

            times.append(current_time)

            # Capture reactor states
            for reactor in reactor_list:
                reactor_id = getattr(reactor, "name", "") or str(id(reactor))
                T = reactor.thermo.T
                P = reactor.thermo.P
                X_vec = reactor.thermo.X

                # Detect non-finite states and handle gracefully
                if not (
                    math.isfinite(T)
                    and math.isfinite(P)
                    and all(math.isfinite(float(x)) for x in X_vec)
                ):
                    logger.warning(
                        f"Non-finite state detected at t={current_time}s for reactor "
                        f"'{reactor_id}', using previous values"
                    )
                    # Duplicate last successful values if available
                    if len(reactors_series[reactor_id]["T"]) > 0:
                        T = reactors_series[reactor_id]["T"][-1]
                        P = reactors_series[reactor_id]["P"][-1]
                        X_vec = [
                            reactors_series[reactor_id]["X"][s][-1]
                            for s in self.gas.species_names
                        ]
                    else:
                        # Use default values
                        T, P = 300.0, 101325.0
                        X_vec = [
                            1.0 if s == "N2" else 0.0 for s in self.gas.species_names
                        ]

                sol_arrays[reactor_id].append(T=T, P=P, X=X_vec)
                reactors_series[reactor_id]["T"].append(T)
                reactors_series[reactor_id]["P"].append(P)
                for species_name, x_value in zip(self.gas.species_names, X_vec):
                    reactors_series[reactor_id]["X"][species_name].append(
                        float(x_value)
                    )

            # Call progress callback if provided (for streaming updates)
            if progress_callback:
                progress_data = {
                    "time": times.copy(),
                    "reactors": {
                        k: {
                            "T": v["T"].copy(),
                            "P": v["P"].copy(),
                            "X": {s: v["X"][s].copy() for s in v["X"]},
                        }
                        for k, v in reactors_series.items()
                    },
                }
                progress_callback(progress_data, current_time, simulation_time)

            current_time += time_step

        # Finalize results
        results = self.finalize_results(times, reactors_series)
        return results, "\n".join(self.code_lines)

    def finalize_results(
        self, times: List[float], reactors_series: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Finalize simulation results with post-processing."""
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

        return results

    def build_network_and_code(
        self, config: Dict[str, Any]
    ) -> Tuple[Any, Dict[str, Any], str]:
        """Legacy method for backward compatibility - runs full simulation at once."""
        network = self.build_network(config)
        results, code_str = self.run_streaming_simulation()
        return network, results, code_str
