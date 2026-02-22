import importlib
import math
import os
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, Callable, Dict, List, Optional, Tuple

import cantera as ct  # type: ignore
import numpy as np

from .config import CANTERA_MECHANISM
from .output_summary import evaluate_output_items, parse_output_block
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
    output_pane_plugins: List[Any] = field(
        default_factory=list
    )  # Import will be handled dynamically
    summary_builders: Dict[str, Any] = field(
        default_factory=dict
    )  # Summary builder plugins
    sankey_generator: Optional[Callable] = None  # Custom Sankey generation function
    #: ``(gas, new_mechanism, htol, Xtol) -> ct.Solution``
    #: Called when an inter-stage connection carries a ``mechanism_switch`` block.
    #: Registered by the *bloc* package via its plugin entry point.
    mechanism_switch_fn: Optional[Callable] = None


# Global cache to ensure plugins are discovered only once
_PLUGIN_CACHE: Optional[BoulderPlugins] = None


def _make_valid_python_identifier(name: str) -> str:
    """Convert a name to a valid Python identifier.

    Replaces spaces and invalid characters with underscores, ensures it starts
    with a letter or underscore, and handles Python keywords.
    """
    import keyword
    import re

    # Replace spaces and invalid characters with underscores
    identifier = re.sub(r"[^a-zA-Z0-9_]", "_", name)

    # Ensure it starts with a letter or underscore
    if identifier and identifier[0].isdigit():
        identifier = "_" + identifier

    # Handle empty string
    if not identifier:
        identifier = "_unnamed"

    # Handle Python keywords
    if keyword.iskeyword(identifier):
        identifier += "_"

    return identifier


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
            else getattr(eps, "get", lambda x: [])(  # type: ignore[attr-defined]
                "boulder.plugins"
            )
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

    # Load output pane plugins from the global registry
    try:
        from .output_pane_plugins import get_output_pane_registry

        output_registry = get_output_pane_registry()
        plugins.output_pane_plugins = output_registry.plugins.copy()
    except ImportError as e:
        logger.debug(f"Output pane plugins not available: {e}")

    # Load summary builder plugins from the global registry
    try:
        from .summary_builder import get_summary_builder_registry

        summary_registry = get_summary_builder_registry()
        plugins.summary_builders = summary_registry.builders.copy()
    except ImportError as e:
        logger.debug(f"Summary builder plugins not available: {e}")

    _PLUGIN_CACHE = plugins

    if is_verbose_mode():
        logger.info(
            f"Plugin discovery complete: {len(plugins.reactor_builders)} reactor builders, "
            f"{len(plugins.connection_builders)} connection builders, "
            f"{len(plugins.post_build_hooks)} post-build hooks, "
            f"{len(plugins.output_pane_plugins)} output pane plugins, "
            f"{len(plugins.summary_builders)} summary builders"
        )

    return plugins


# class CanteraConverter:
#    """Former Cantera converter lived there, now fully replaced by DualCanteraConverter
#    which generates code in parallel to solving the simulation
#    """"
class DualCanteraConverter:
    """Unified Cantera converter with streaming simulation capabilities.

    Examples
    --------
    .. minigallery:: boulder.cantera_converter.DualCanteraConverter
       :add-heading: Examples using DualCanteraConverter
    """

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
        # Cache of mechanisms -> Solution to support per-node overrides
        self._gases_by_mech: Dict[str, ct.Solution] = {resolved_mechanism: self.gas}
        self.reactors: Dict[str, ct.Reactor] = {}
        self.reactor_meta: Dict[str, Dict[str, Any]] = {}
        self.connections: Dict[str, ct.FlowDevice] = {}
        self.walls: Dict[str, Any] = {}
        self.network: Optional[ct.ReactorNet] = None
        self.code_lines: List[str] = []
        self.last_network: Optional[ct.ReactorNet] = (
            None  # Store the last successfully built network
        )
        # Preserve last config for post-processing (e.g., output summary)
        self._last_config: Optional[Dict[str, Any]] = None
        # Path to config file for --download script (set by CLI in headless mode)
        self._download_config_path: Optional[str] = None

    def parse_composition(self, comp_str: str) -> Dict[str, float]:
        comp_dict = {}
        for pair in comp_str.split(","):
            species, value = pair.split(":")
            comp_dict[species.strip()] = float(value)
        return comp_dict

    def _set_reactor_volume(
        self, reactor: ct.Reactor, props: Dict[str, Any], reactor_id: str
    ) -> None:
        """Set reactor volume if specified in properties."""
        volume = props.get("volume")
        if volume is not None and not isinstance(reactor, ct.Reservoir):
            try:
                volume_val = float(volume)
                if volume_val > 0:
                    reactor.volume = volume_val
                    python_var = _make_valid_python_identifier(reactor_id)
                    self.code_lines.append(
                        f"{python_var}.volume = {volume_val}  # Set reactor volume in m³"
                    )
                    logger.debug(f"Set volume for {reactor_id}: {volume_val} m³")
            except (ValueError, TypeError, AttributeError) as e:
                logger.warning(f"Failed to set volume for {reactor_id}: {e}")

    # ------------------------------------------------------------------
    # Low-level helpers shared by build_network / build_sub_network
    # ------------------------------------------------------------------

    def _get_gas_for_mech(self, mech_name: str) -> ct.Solution:
        """Return (creating and caching if needed) a :class:`~cantera.Solution`.

        Uses the registered mechanism path resolver so that both short names
        (``"gri30.yaml"``) and absolute paths work uniformly.
        """
        resolved = (
            self.plugins.mechanism_path_resolver(mech_name)
            if self.plugins.mechanism_path_resolver
            else mech_name
        )
        if resolved in self._gases_by_mech:
            return self._gases_by_mech[resolved]
        gas_obj = ct.Solution(resolved)
        self._gases_by_mech[resolved] = gas_obj
        return gas_obj

    def _create_reactor_from_node(
        self, node: Dict[str, Any], gas_for_node: ct.Solution
    ) -> ct.Reactor:
        """Instantiate a Cantera reactor from a normalized node dict.

        Uses the plugin reactor builder registry when the type matches a
        registered custom builder; otherwise falls back to the standard
        Cantera reactor types.

        Parameters
        ----------
        node :
            Normalized node dict with ``id``, ``type``, and ``properties``.
        gas_for_node :
            The :class:`~cantera.Solution` carrying the initial state.

        Returns
        -------
        ct.Reactor
            The newly created reactor (not yet added to any network).
        """
        rid = node["id"]
        typ = node["type"]
        props = node.get("properties") or {}

        if typ in self.plugins.reactor_builders:
            reactor = self.plugins.reactor_builders[typ](self, node)
            reactor.name = rid
        elif typ == "IdealGasReactor":
            reactor = ct.IdealGasReactor(gas_for_node, clone=True)
            reactor.name = rid
        elif typ == "IdealGasConstPressureReactor":
            reactor = ct.IdealGasConstPressureReactor(gas_for_node, clone=True)
            reactor.name = rid
        elif typ == "IdealGasConstPressureMoleReactor":
            reactor = ct.IdealGasConstPressureMoleReactor(gas_for_node, clone=True)
            reactor.name = rid
        elif typ == "IdealGasMoleReactor":
            reactor = ct.IdealGasMoleReactor(gas_for_node, clone=True)  # type: ignore[attr-defined]
            reactor.name = rid
        elif typ == "Reservoir":
            reactor = ct.Reservoir(gas_for_node, clone=True)
            reactor.name = rid
        else:
            raise ValueError(f"Unsupported reactor type: '{typ}'")

        self._set_reactor_volume(reactor, props, rid)
        try:
            reactor.group_name = str(props.get("group", props.get("group_name", "")))
        except Exception:
            pass

        return reactor

    def _build_single_connection(self, conn: Dict[str, Any]) -> None:
        """Create and register one Cantera flow device or wall from a connection dict.

        The connection is added to ``self.connections`` (for
        :class:`~cantera.FlowDevice` subtypes) or ``self.walls`` (for
        :class:`~cantera.Wall`).

        Parameters
        ----------
        conn :
            Normalized connection dict with ``id``, ``type``, ``source``,
            ``target``, and ``properties``.
        """
        cid = conn["id"]
        typ = conn.get("type", "MassFlowController")
        src = conn["source"]
        tgt = conn["target"]
        props = conn.get("properties") or {}

        if typ in self.plugins.connection_builders:
            device = self.plugins.connection_builders[typ](self, conn)
            self.connections[cid] = device
        elif typ == "MassFlowController":
            mfr = float(props.get("mass_flow_rate", 0.1))
            mfc = ct.MassFlowController(self.reactors[src], self.reactors[tgt])
            mfc.mass_flow_rate = mfr  # type: ignore[misc]
            self.connections[cid] = mfc
        elif typ == "Valve":
            coeff = float(props.get("valve_coeff", 1.0))
            valve = ct.Valve(self.reactors[src], self.reactors[tgt])
            valve.valve_coeff = coeff  # type: ignore[attr-defined]
            self.connections[cid] = valve
        elif typ == "Wall":
            electric_power_kW = float(props.get("electric_power_kW", 0.0))
            torch_eff = float(props.get("torch_eff", 1.0))
            gen_eff = float(props.get("gen_eff", 1.0))
            Q_watts = electric_power_kW * 1e3 * torch_eff * gen_eff
            wall = ct.Wall(
                self.reactors[src],
                self.reactors[tgt],
                A=1.0,
                Q=lambda t: Q_watts,
                name=cid,  # type: ignore[arg-type]
            )
            self.walls[cid] = wall
        else:
            raise ValueError(f"Unsupported connection type: '{typ}'")

    # ------------------------------------------------------------------
    # Staged solving
    # ------------------------------------------------------------------

    def build_sub_network(
        self,
        stage_nodes: List[Dict[str, Any]],
        stage_connections: List[Dict[str, Any]],
        stage_mechanism: str,
        inlet_states: Dict[str, "ct.Solution"],
        stage_id: str = "",
        stage: Optional[Any] = None,
    ) -> Tuple["ct.ReactorNet", Dict[str, "ct.Reactor"]]:
        """Build (and solve) a :class:`~cantera.ReactorNet` for one stage.

        Reactors whose IDs appear in *inlet_states* are initialised from the
        provided :class:`~cantera.Solution` (upstream outlet, already
        mechanism-switched) instead of from the YAML properties.

        Parameters
        ----------
        stage_nodes :
            Normalized node dicts for this stage only.
        stage_connections :
            Intra-stage normalized connection dicts.
        stage_mechanism :
            Default kinetic mechanism for the stage.
        inlet_states :
            ``{node_id: ct.Solution}`` mapping inlet conditions for reactors
            that receive inter-stage flow.
        stage_id :
            For logging/error messages.
        stage :
            :class:`~boulder.staged_solver.Stage` dataclass; used to set the
            solve directive (``advance_to_steady_state`` vs ``advance``).

        Returns
        -------
        (network, stage_reactors)
            ``network`` is the solved :class:`~cantera.ReactorNet`.
            ``stage_reactors`` is a ``{node_id: ct.Reactor}`` dict for this
            stage (a subset of ``self.reactors``).
        """
        stage_reactor_ids: List[str] = []

        for node in stage_nodes:
            rid = node["id"]
            props = node.get("properties") or {}

            # Use inlet state if provided (inter-stage flow), else use YAML props
            if rid in inlet_states:
                inlet = inlet_states[rid]
                node_mech = stage_mechanism
                gas_for_node = self._get_gas_for_mech(node_mech)
                gas_for_node.TPY = inlet.T, inlet.P, inlet.Y
            else:
                node_mech = str(
                    props.get("mechanism") or node.get("mechanism") or stage_mechanism
                )
                gas_for_node = self._get_gas_for_mech(node_mech)
                temp = props.get("temperature", 300)
                pres = props.get("pressure", 101325)
                compo = props.get("composition", "N2:1")
                gas_for_node.TPX = (temp, pres, self.parse_composition(compo))

            self.gas = gas_for_node
            self.reactor_meta[rid] = {
                "mechanism": node_mech,
                "gas_solution": gas_for_node,
            }

            reactor = self._create_reactor_from_node(node, gas_for_node)

            # Guarantee gas_solution and mechanism are always present in meta.
            # Plugin builders overwrite reactor_meta[rid] entirely, losing these keys.
            meta = self.reactor_meta.setdefault(rid, {})
            meta["gas_solution"] = gas_for_node
            meta.setdefault("mechanism", node_mech)

            # For plugin-created reactors, also apply inlet state override
            if rid in inlet_states and not isinstance(reactor, ct.Reservoir):
                inlet = inlet_states[rid]
                try:
                    reactor.phase.TPY = inlet.T, inlet.P, inlet.Y
                except Exception as exc:
                    logger.warning(
                        "Could not override inlet state for '%s' in stage '%s': %s",
                        rid,
                        stage_id,
                        exc,
                    )

            self.reactors[rid] = reactor
            stage_reactor_ids.append(rid)

        # Build intra-stage connections
        for conn in stage_connections:
            cid = conn["id"]
            src = conn["source"]
            tgt = conn["target"]
            if src not in self.reactors or tgt not in self.reactors:
                logger.warning(
                    "Stage '%s': skipping connection '%s' — reactor not found.",
                    stage_id,
                    cid,
                )
                continue
            try:
                self._build_single_connection(conn)
            except Exception as exc:
                logger.warning(
                    "Stage '%s': failed to build connection '%s': %s",
                    stage_id,
                    cid,
                    exc,
                )

        # Apply post-build hooks for this stage's subset
        stage_config_subset: Dict[str, Any] = {
            "nodes": stage_nodes,
            "connections": stage_connections,
        }
        for hook in self.plugins.post_build_hooks:
            try:
                hook(self, stage_config_subset)
            except Exception as exc:
                logger.warning(
                    "Post-build hook failed for stage '%s': %s", stage_id, exc
                )

        # Build ReactorNet (non-Reservoir reactors only)
        non_res_ids = [
            rid
            for rid in stage_reactor_ids
            if not isinstance(self.reactors[rid], ct.Reservoir)
        ]

        # Select ReactorNet class — use a custom subclass if any reactor
        # declares NETWORK_CLASS (e.g. DesignPFR → DesignPFRNet).
        ReactorNetClass = ct.ReactorNet
        net_kw: dict = {}
        for rid in non_res_ids:
            r = self.reactors[rid]
            if hasattr(r, "NETWORK_CLASS"):
                ReactorNetClass = r.NETWORK_CLASS
                net_kw["meta"] = self.reactor_meta.get(rid, {})
                break

        network = ReactorNetClass([self.reactors[rid] for rid in non_res_ids], **net_kw)
        if ReactorNetClass is ct.ReactorNet:
            network.rtol = 1e-6
            network.atol = 1e-8

        # Solve
        solve_directive = (
            getattr(stage, "solve_directive", "advance_to_steady_state")
            if stage is not None
            else "advance_to_steady_state"
        )
        if solve_directive == "advance_to_steady_state":
            network.advance_to_steady_state()
        elif solve_directive == "advance":
            advance_time = getattr(stage, "advance_time", 1.0)
            network.advance(float(advance_time))
        else:
            logger.warning(
                "Unknown solve_directive '%s' for stage '%s'; using advance_to_steady_state.",
                solve_directive,
                stage_id,
            )
            network.advance_to_steady_state()

        stage_reactors = {rid: self.reactors[rid] for rid in stage_reactor_ids}
        return network, stage_reactors

    def build_viz_network(
        self,
        all_connections: List[Dict[str, Any]],
        built_conn_ids: Optional[set] = None,
    ) -> "ct.ReactorNet":
        """Build a visualization-only :class:`~cantera.ReactorNet`.

        Uses all reactor objects already in ``self.reactors`` (which carry
        converged states after a staged solve) and adds any inter-stage
        connections that were not built during the per-stage solve.

        The returned network is **not advanced** – it exists solely for
        ``ReactorNet.draw()`` and Sankey diagram generation.

        Parameters
        ----------
        all_connections :
            The full list of normalized connection dicts (including
            inter-stage ones).
        built_conn_ids :
            Set of connection IDs already built (intra-stage).  Inter-stage
            connections not in this set will be created now.

        Returns
        -------
        ct.ReactorNet
        """
        already_built = built_conn_ids or set()

        for conn in all_connections:
            cid = conn["id"]
            if cid in already_built:
                continue
            src = conn["source"]
            tgt = conn["target"]
            if src not in self.reactors or tgt not in self.reactors:
                logger.debug(
                    "Viz network: skipping connection '%s' — reactor not found.", cid
                )
                continue
            try:
                self._build_single_connection(conn)
            except Exception as exc:
                logger.warning(
                    "Viz network: could not build connection '%s': %s", cid, exc
                )

        non_res = [r for r in self.reactors.values() if not isinstance(r, ct.Reservoir)]
        viz_net = ct.ReactorNet(non_res)
        self.network = viz_net
        self.last_network = viz_net
        return viz_net

    def build_network(self, config: Dict[str, Any]) -> ct.ReactorNet:
        """Build the Cantera network without running simulation.

        If the config contains a top-level ``groups`` section, delegates to
        :func:`~boulder.staged_solver.solve_staged` which builds one sub-
        :class:`~cantera.ReactorNet` per stage and returns a visualization
        ReactorNet.  The :class:`~boulder.lagrangian.LagrangianTrajectory`
        is stored on ``self._staged_trajectory``.

        Without a ``groups`` section the original single-network behavior is
        preserved (backward compatible).
        """
        # Store config for later post-processing
        self._last_config = config

        # ----------------------------------------------------------------
        # Staged solving path
        # ----------------------------------------------------------------
        if config.get("groups"):
            from .staged_solver import build_stage_graph, solve_staged

            plan = build_stage_graph(config)
            trajectory = solve_staged(self, plan, config)
            self._staged_trajectory = trajectory
            # Generate downloadable script: load from YAML and build network
            download_path = getattr(
                self, "_download_config_path", None
            ) or "config.yaml"
            self.code_lines = [
                "# Load configuration from YAML and build Cantera network",
                "import cantera as ct",
                "from boulder.config import (",
                "    load_config_file_with_py_support,",
                "    normalize_config,",
                "    validate_config,",
                ")",
                "from boulder.cantera_converter import DualCanteraConverter",
                "",
                f"config_path = {repr(download_path)}",
                "config, _ = load_config_file_with_py_support(config_path, False)",
                "config = validate_config(normalize_config(config))",
                "",
                "converter = DualCanteraConverter()",
                "network = converter.build_network(config)",
            ]
            # viz_network is already set on self.network by build_viz_network
            return self.network  # type: ignore[return-value]

        # ----------------------------------------------------------------
        # Original single-network path (unchanged)
        # ----------------------------------------------------------------
        self.code_lines = []
        self.code_lines.append(
            "# Import Cantera for chemical kinetics and reactor modeling"
        )
        self.code_lines.append("import cantera as ct")
        self.code_lines.append("")
        self.code_lines.append(
            "# Load the chemical mechanism (contains species and reactions)"
        )
        self.code_lines.append(f"gas_default = ct.Solution('{self.mechanism}')")
        try:
            self.gas = ct.Solution(self.mechanism)
        except Exception as e:
            logger.error(
                f"[ERROR] Failed to reload mechanism '{self.mechanism}' in build_network: {e}"
            )
        # Reset cache for this build
        self._gases_by_mech = {}

        # Add metadata from config as docstring at the very top
        metadata = config.get("metadata", {})
        if metadata:
            title = metadata.get("title", "")
            description = metadata.get("description", "")

            if title or description:
                # Insert at the beginning of code_lines
                docstring_lines = ['"""']
                if title:
                    docstring_lines.append(title)
                if description:
                    if title:
                        docstring_lines.append("")
                    # Split description into lines and add each line
                    for line in description.split("\n"):
                        docstring_lines.append(line)
                docstring_lines.append('"""')
                docstring_lines.append("")

                # Insert at the beginning
                self.code_lines = docstring_lines + self.code_lines

        self.reactors = {}
        self.connections = {}

        # Create reactors from configuration
        self.code_lines.append("")
        self.code_lines.append("# ===== REACTOR SETUP =====")
        for node in config["nodes"]:
            rid = node["id"]
            typ = node["type"]
            props = node["properties"]
            temp = props.get("temperature", 300)
            pres = props.get("pressure", 101325)
            compo = props.get("composition", "N2:1")

            # Check if node has a description from YAML
            node_description = node.get("description", "")
            # Determine mechanism: node-level override, else global
            node_mech = (
                node.get("mechanism") or props.get("mechanism") or self.mechanism
            )
            gas_for_node = self._get_gas_for_mech(str(node_mech))
            gas_for_node.TPX = (temp, pres, self.parse_composition(compo))
            # Keep converter.gas referencing the last used gas (for back-compat),
            # but store per-reactor association in reactor_meta
            self.gas = gas_for_node
            # Store mechanism info for each reactor to handle multi-mechanism networks
            self.reactor_meta[rid] = {
                "mechanism": str(node_mech),
                "gas_solution": gas_for_node,
            }
            # Plugin-backed custom reactor types
            if typ in self.plugins.reactor_builders:
                reactor = self.plugins.reactor_builders[typ](self, node)
                reactor.name = rid
                self.reactors[rid] = reactor
                # Set volume if specified (plugins may support volume)
                self._set_reactor_volume(self.reactors[rid], props, rid)
                try:
                    self.reactors[rid].group_name = str(
                        props.get("group", props.get("group_name", ""))
                    )
                except Exception:
                    pass
                # Code gen: note plugin usage
                self.code_lines.append(f"# Plugin reactor {typ} -> created as '{rid}'")
            elif typ == "IdealGasReactor":
                self.code_lines.append(
                    f"# Create IdealGasReactor '{rid}' - variable volume, constant energy"
                )
                if node_description:
                    # Add description as comment if it exists in YAML
                    for desc_line in node_description.split("\n"):
                        if desc_line.strip():
                            self.code_lines.append(f"# {desc_line.strip()}")
                self.code_lines.append(
                    f"# Initial conditions: T={temp}K, P={pres}Pa, composition='{compo}'"
                )
                python_var = _make_valid_python_identifier(rid)
                self.code_lines.append(
                    f"{python_var} = ct.IdealGasReactor(gas_default)"
                )
                self.code_lines.append(f"{python_var}.name = '{rid}'")
                self.reactors[rid] = ct.IdealGasReactor(gas_for_node, clone=True)
                self.reactors[rid].name = rid
                # Set volume if specified
                self._set_reactor_volume(self.reactors[rid], props, rid)
                try:
                    self.reactors[rid].group_name = str(
                        props.get("group", props.get("group_name", ""))
                    )
                    self.code_lines.append(
                        f"{python_var}.group_name = '{props.get('group', props.get('group_name', ''))}'"
                    )
                except Exception:
                    pass
            elif typ == "IdealGasConstPressureReactor":
                self.code_lines.append(
                    f"# Create IdealGasConstPressureReactor '{rid}' - constant pressure"
                )
                if node_description:
                    # Add description as comment if it exists in YAML
                    for desc_line in node_description.split("\n"):
                        if desc_line.strip():
                            self.code_lines.append(f"# {desc_line.strip()}")
                self.code_lines.append(
                    f"# Initial conditions: T={temp}K, P={pres}Pa, composition='{compo}'"
                )
                python_var = _make_valid_python_identifier(rid)
                self.code_lines.append(
                    f"{python_var} = ct.IdealGasConstPressureReactor(gas_default)"
                )
                self.code_lines.append(f"{python_var}.name = '{rid}'")
                self.reactors[rid] = ct.IdealGasConstPressureReactor(
                    gas_for_node, clone=True
                )
                self.reactors[rid].name = rid
                # Set volume if specified
                self._set_reactor_volume(self.reactors[rid], props, rid)
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
                    f"# Create IdealGasConstPressureMoleReactor '{rid}' - mole-based"
                )
                self.code_lines.append(
                    f"# Initial conditions: T={temp}K, P={pres}Pa, composition='{compo}'"
                )
                self.code_lines.append(
                    f"{rid} = ct.IdealGasConstPressureMoleReactor(gas_default)"
                )
                self.code_lines.append(f"{rid}.name = '{rid}'")
                self.reactors[rid] = ct.IdealGasConstPressureMoleReactor(
                    gas_for_node, clone=True
                )
                self.reactors[rid].name = rid
                # Set volume if specified
                self._set_reactor_volume(self.reactors[rid], props, rid)
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
                self.code_lines.append(
                    f"# Create IdealGasMoleReactor '{rid}' - mole-based (Cantera 3.x)"
                )
                self.code_lines.append(
                    f"# Initial conditions: T={temp}K, P={pres}Pa, composition='{compo}'"
                )
                self.code_lines.append(f"{rid} = ct.IdealGasMoleReactor(gas_default)")
                self.code_lines.append(f"{rid}.name = '{rid}'")
                self.reactors[rid] = ct.IdealGasMoleReactor(gas_for_node, clone=True)  # type: ignore[attr-defined]
                self.reactors[rid].name = rid
                # Set volume if specified
                self._set_reactor_volume(self.reactors[rid], props, rid)
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
                self.code_lines.append(
                    f"# Create Reservoir '{rid}' - infinite capacity, constant state"
                )
                if node_description:
                    # Add description as comment if it exists in YAML
                    for desc_line in node_description.split("\n"):
                        if desc_line.strip():
                            self.code_lines.append(f"# {desc_line.strip()}")
                self.code_lines.append(
                    f"# Fixed conditions: T={temp}K, P={pres}Pa, composition='{compo}'"
                )
                python_var = _make_valid_python_identifier(rid)
                self.code_lines.append(f"{python_var} = ct.Reservoir(gas_default)")
                self.code_lines.append(f"{python_var}.name = '{rid}'")
                reservoir = ct.Reservoir(gas_for_node, clone=True)
                self.reactors[rid] = reservoir  # type: ignore[assignment]
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

        # Create connections between reactors
        self.code_lines.append("")
        self.code_lines.append("# ===== CONNECTION SETUP =====")
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
                self.code_lines.append(
                    f"# Create MassFlowController '{cid}': {src} -> {tgt}"
                )
                self.code_lines.append(f"# Controls mass flow rate at {mfr} kg/s")
                cid_var = _make_valid_python_identifier(cid)
                src_var = _make_valid_python_identifier(src)
                tgt_var = _make_valid_python_identifier(tgt)
                self.code_lines.append(
                    f"{cid_var} = ct.MassFlowController({src_var}, {tgt_var})"
                )
                self.code_lines.append(f"{cid_var}.mass_flow_rate = {mfr}")
                mfc = ct.MassFlowController(self.reactors[src], self.reactors[tgt])
                mfc.mass_flow_rate = mfr  # type: ignore[misc]
                self.connections[cid] = mfc
            elif typ == "Valve":
                coeff = float(props.get("valve_coeff", 1.0))
                self.code_lines.append(f"# Create Valve '{cid}': {src} -> {tgt}")
                self.code_lines.append(
                    f"# Flow depends on pressure difference, valve coeff = {coeff}"
                )
                cid_var = _make_valid_python_identifier(cid)
                src_var = _make_valid_python_identifier(src)
                tgt_var = _make_valid_python_identifier(tgt)
                self.code_lines.append(f"{cid_var} = ct.Valve({src_var}, {tgt_var})")
                self.code_lines.append(f"{cid_var}.valve_coeff = {coeff}")
                valve = ct.Valve(self.reactors[src], self.reactors[tgt])
                valve.valve_coeff = coeff  # type: ignore[attr-defined]
                self.connections[cid] = valve
            elif typ == "Wall":
                # Handle walls as energy connections (e.g., torch power or losses)
                # After validation, electric_power_kW is converted to kilowatts if it had units
                electric_power_kW = float(props.get("electric_power_kW", 0.0))
                torch_eff = float(props.get("torch_eff", 1.0))
                gen_eff = float(props.get("gen_eff", 1.0))
                # Convert from kW to W
                Q_watts = electric_power_kW * 1e3 * torch_eff * gen_eff
                self.code_lines.append(f"# Create Wall '{cid}': {src} <-> {tgt}")
                self.code_lines.append(
                    f"# Heat transfer: {Q_watts} W (from {electric_power_kW} kW input)"
                )
                self.code_lines.append(
                    f"# Efficiencies: torch={torch_eff}, generator={gen_eff}"
                )
                self.code_lines.append(
                    f"{cid} = ct.Wall({src}, {tgt}, A=1.0, Q={Q_watts}, name='{cid}')"
                )
                wall = ct.Wall(
                    self.reactors[src],
                    self.reactors[tgt],
                    A=1.0,
                    Q=lambda t: Q_watts,
                    name=cid,  # type: ignore[arg-type]
                )
                self.walls[cid] = wall
                # Note: Walls are not flow devices, so we track them separately
            else:
                self.code_lines.append(f"# Unsupported connection type: {typ}")
                raise ValueError(f"Unsupported connection type: {typ}")

        # Create reactor network (exclude reservoirs as they don't evolve in time)
        reactor_ids = [
            rid for rid, r in self.reactors.items() if not isinstance(r, ct.Reservoir)
        ]
        self.code_lines.append("")
        self.code_lines.append("# ===== NETWORK SETUP =====")
        self.code_lines.append(
            "# Create reactor network with all time-evolving reactors"
        )
        reactor_vars = [_make_valid_python_identifier(rid) for rid in reactor_ids]
        self.code_lines.append(f"# Reactors in network: {', '.join(reactor_ids)}")
        self.code_lines.append(f"network = ct.ReactorNet([{', '.join(reactor_vars)}])")
        self.network = ct.ReactorNet([self.reactors[rid] for rid in reactor_ids])
        self.code_lines.append("")
        self.code_lines.append("# Set solver tolerances for numerical integration")
        self.code_lines.append("network.rtol = 1e-6  # Relative tolerance")
        self.code_lines.append("network.atol = 1e-8  # Absolute tolerance")
        self.code_lines.append(
            "network.max_steps = 10000  # Maximum steps per time step"
        )
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
        config: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], str]:
        """Run simulation with streaming progress updates."""
        if self.network is None:
            raise RuntimeError("Network not built. Call build_network() first.")

        # Override parameters from config if provided
        if config:
            # Only use 'settings' section with 'end_time' and 'dt'
            settings_config = config.get("settings", {})

            # Check for deprecated keys and raise errors only if they contain values
            deprecated_keys = []

            # Only error if simulation section exists and has content
            simulation_section = config.get("simulation", {})
            if simulation_section:  # Only if not empty
                deprecated_keys.append("'simulation' section (use 'settings' instead)")

            # Only error if deprecated keys exist in settings
            if "max_time" in settings_config:
                deprecated_keys.append(
                    "'max_time' in settings (use 'end_time' instead)"
                )
            if "time_step" in settings_config:
                deprecated_keys.append("'time_step' in settings (use 'dt' instead)")

            if deprecated_keys:
                raise ValueError(
                    f"Deprecated configuration keys found: {', '.join(deprecated_keys)}. "
                    "Please update your YAML to use 'settings' section with 'end_time' and 'dt' keys only."
                )

            # Extract values from settings section only
            config_simulation_time = settings_config.get("end_time")
            config_time_step = settings_config.get("dt")

            # Use config values if valid, otherwise keep defaults
            if config_simulation_time is not None and config_simulation_time > 0:
                simulation_time = float(config_simulation_time)
            if config_time_step is not None and config_time_step > 0:
                time_step = float(config_time_step)

            # Validate time_step is not greater than simulation_time
            if time_step > simulation_time:
                logger.warning(
                    f"time_step ({time_step}s) > simulation_time ({simulation_time}s), adjusting time_step"
                )
                time_step = simulation_time / 10.0  # Use 10 steps minimum

            logger.info(
                f"Using config parameters: time={simulation_time}s, step={time_step}s"
            )

        # Add simulation loop code generation
        self.code_lines.append("")
        self.code_lines.append("# ===== SIMULATION EXECUTION =====")
        self.code_lines.append("# Import numpy for time array generation")
        self.code_lines.append("import numpy as np")
        self.code_lines.append("")
        self.code_lines.append(
            f"# Create time array: 0 to {simulation_time}s with {time_step}s steps"
        )
        self.code_lines.append(f"times = np.arange(0, {simulation_time}, {time_step})")
        self.code_lines.append("")
        self.code_lines.append("# Run time integration loop")
        self.code_lines.append("print('Starting simulation...')")
        self.code_lines.append("print('Time (s)\\tTemperatures (K)')")
        self.code_lines.append("for t in times:")
        self.code_lines.append("    # Advance the reactor network to time t")
        self.code_lines.append("    network.advance(t)")
        self.code_lines.append("    # Print current time and reactor temperatures")
        self.code_lines.append(
            '    print(f"t={t:.4f}, T={[r.phase.T for r in network.reactors]}")'
        )
        self.code_lines.append("")
        self.code_lines.append("print('Simulation completed!')")

        # Initialize data structures
        times: List[float] = []
        reactor_list = [
            r for r in self.reactors.values() if not isinstance(r, ct.Reservoir)
        ]

        # Per-reactor capture using SolutionArray
        reactors_series: Dict[str, Dict[str, Any]] = {}
        sol_arrays: Dict[str, ct.SolutionArray] = {}
        last_error_message: str = ""
        for reactor in reactor_list:
            reactor_id = getattr(reactor, "name", "") or str(id(reactor))
            # Use the correct gas solution for this reactor's mechanism
            reactor_gas = self.reactor_meta.get(reactor_id, {}).get(
                "gas_solution", self.gas
            )
            sol_arrays[reactor_id] = ct.SolutionArray(reactor_gas, shape=(0,))
            reactors_series[reactor_id] = {
                "T": [],
                "P": [],
                "X": {s: [] for s in reactor_gas.species_names},
                "Y": {s: [] for s in reactor_gas.species_names},
            }

        # Simulation loop with streaming updates
        current_time = 0.0
        while current_time < simulation_time:
            try:
                self.network.advance(current_time)
            except Exception as e:
                # Log warning but continue with partial results
                last_error_message = str(e)
                logger.warning(
                    f"Cantera advance failed at t={current_time}s: {last_error_message}"
                )
                if len(times) == 0:
                    # Record initial state so we have at least one time point (for Sankey, etc.)
                    logger.warning(
                        "Recording initial reactor state and returning (integration failed)"
                    )
                    times.append(0.0)
                    for reactor in reactor_list:
                        reactor_id = getattr(reactor, "name", "") or str(id(reactor))
                        reactor_gas = self.reactor_meta.get(reactor_id, {}).get(
                            "gas_solution", self.gas
                        )
                        reactor_species_names = reactor_gas.species_names
                        try:
                            T = float(reactor.phase.T)
                            P = float(reactor.phase.P)
                            X_vec = reactor.phase.X
                            Y_vec = reactor.phase.Y
                            if not (
                                math.isfinite(T)
                                and math.isfinite(P)
                                and all(math.isfinite(float(x)) for x in X_vec)
                                and all(math.isfinite(float(y)) for y in Y_vec)
                            ):
                                T, P = 300.0, 101325.0
                                X_vec = np.array(
                                    [
                                        1.0 if s == "N2" else 0.0
                                        for s in reactor_species_names
                                    ]
                                )
                                Y_vec = np.array(
                                    [
                                        1.0 if s == "N2" else 0.0
                                        for s in reactor_species_names
                                    ]
                                )
                        except Exception:
                            T, P = 300.0, 101325.0
                            X_vec = np.array(
                                [
                                    1.0 if s == "N2" else 0.0
                                    for s in reactor_species_names
                                ]
                            )
                            Y_vec = np.array(
                                [
                                    1.0 if s == "N2" else 0.0
                                    for s in reactor_species_names
                                ]
                            )
                        sol_arrays[reactor_id].append(T=T, P=P, X=X_vec)
                        reactors_series[reactor_id]["T"].append(T)
                        reactors_series[reactor_id]["P"].append(P)
                        for species_name, x_value in zip(reactor_species_names, X_vec):
                            reactors_series[reactor_id]["X"][species_name].append(
                                float(x_value)
                            )
                        for species_name, y_value in zip(reactor_species_names, Y_vec):
                            reactors_series[reactor_id]["Y"][species_name].append(
                                float(y_value)
                            )
                    if progress_callback:
                        progress_callback(
                            {
                                "time": times.copy(),
                                "reactors": {
                                    k: {
                                        "T": v["T"].copy(),
                                        "P": v["P"].copy(),
                                        "X": {s: v["X"][s].copy() for s in v["X"]},
                                        "Y": {s: v["Y"][s].copy() for s in v["Y"]},
                                    }
                                    for k, v in reactors_series.items()
                                },
                                "error_message": last_error_message,
                            },
                            0.0,
                            simulation_time,
                        )
                    break
                # Otherwise, break and return partial results
                logger.warning(f"Returning partial results up to t={times[-1]}s")
                # Provide a partial-progress callback update containing the error
                if progress_callback:
                    progress_callback(
                        {
                            "time": times.copy(),
                            "reactors": {
                                k: {
                                    "T": v["T"].copy(),
                                    "P": v["P"].copy(),
                                    "X": {s: v["X"][s].copy() for s in v["X"]},
                                    "Y": {s: v["Y"][s].copy() for s in v["Y"]},
                                }
                                for k, v in reactors_series.items()
                            },
                            "error_message": last_error_message,
                        },
                        current_time,
                        simulation_time,
                    )
                break

            times.append(current_time)

            # Capture reactor states
            for reactor in reactor_list:
                reactor_id = getattr(reactor, "name", "") or str(id(reactor))
                T = reactor.phase.T
                P = reactor.phase.P
                X_vec = reactor.phase.X
                Y_vec = reactor.phase.Y

                # Get the correct gas solution for this reactor's mechanism
                reactor_gas = self.reactor_meta.get(reactor_id, {}).get(
                    "gas_solution", self.gas
                )
                reactor_species_names = reactor_gas.species_names

                # Detect non-finite states and handle gracefully
                if not (
                    math.isfinite(T)
                    and math.isfinite(P)
                    and all(math.isfinite(float(x)) for x in X_vec)
                    and all(math.isfinite(float(y)) for y in Y_vec)
                ):
                    last_error_message = (
                        "Non-finite state detected (T/P/X) — using previous values"
                    )
                    logger.warning(
                        f"Non-finite state detected at t={current_time}s for reactor "
                        f"'{reactor_id}', using previous values"
                    )
                    # Duplicate last successful values if available
                    if len(reactors_series[reactor_id]["T"]) > 0:
                        T = reactors_series[reactor_id]["T"][-1]
                        P = reactors_series[reactor_id]["P"][-1]
                        X_vec_list = [
                            reactors_series[reactor_id]["X"][s][-1]
                            for s in reactor_species_names
                        ]
                        import numpy as np

                        X_vec = np.array(X_vec_list)
                        Y_vec_list = [
                            reactors_series[reactor_id]["Y"][s][-1]
                            for s in reactor_species_names
                        ]
                        Y_vec = np.array(Y_vec_list)
                    else:
                        # Use default values
                        import numpy as np

                        T, P = 300.0, 101325.0
                        X_vec = np.array(
                            [1.0 if s == "N2" else 0.0 for s in reactor_species_names]
                        )
                        Y_vec = np.array(
                            [1.0 if s == "N2" else 0.0 for s in reactor_species_names]
                        )

                sol_arrays[reactor_id].append(T=T, P=P, X=X_vec)
                reactors_series[reactor_id]["T"].append(T)
                reactors_series[reactor_id]["P"].append(P)
                for species_name, x_value in zip(reactor_species_names, X_vec):
                    reactors_series[reactor_id]["X"][species_name].append(
                        float(x_value)
                    )
                for species_name, y_value in zip(reactor_species_names, Y_vec):
                    reactors_series[reactor_id]["Y"][species_name].append(
                        float(y_value)
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
                            "Y": {s: v["Y"][s].copy() for s in v["Y"]},
                        }
                        for k, v in reactors_series.items()
                    },
                }
                if last_error_message:
                    progress_data["error_message"] = last_error_message
                progress_callback(progress_data, current_time, simulation_time)

            current_time += time_step

        # Finalize results
        results = self.finalize_results(times, reactors_series)
        if last_error_message:
            results["error_message"] = last_error_message
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
            # Dynamically determine available species for Sankey diagram
            available_species = self._get_available_species_for_sankey()
            logger.info(f"Using species for Sankey diagram: {available_species}")

            plugins = get_plugins()
            if plugins.sankey_generator:
                # Use custom Sankey generator from plugin
                logger.info("Using custom Sankey generator from plugin")
                links, nodes = plugins.sankey_generator(
                    self.last_network,
                    show_species=available_species,  # TODO : let it be set by plugin
                    verbose=False,
                )
            else:
                # Use default Boulder Sankey generator
                logger.info("Using default Boulder Sankey generator")
                links, nodes = generate_sankey_input_from_sim(
                    self.last_network,
                    show_species=available_species,
                    verbose=False,
                    if_no_species="ignore",
                )

            logger.info(
                f"Sankey generation result: links={type(links)}, nodes={type(nodes)}"
            )
            if links:
                logger.info(f"Links has {len(links.get('source', []))} connections")
            if nodes:
                logger.info(f"Nodes has {len(nodes)} entries")

            results["sankey_links"] = links
            results["sankey_nodes"] = nodes
        except Exception as e:
            logger.error(f"Error generating Sankey diagram: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            results["sankey_links"] = None
            results["sankey_nodes"] = None

            # Propagate Sankey errors to the UI error system
            sankey_error_msg = f"Sankey diagram generation failed: {str(e)}"
            if "error_message" in results:
                results["error_message"] = (
                    f"{results['error_message']}\n\n{sankey_error_msg}"
                )
            else:
                results["error_message"] = sankey_error_msg

        # Evaluate custom output summary if configured
        try:
            cfg = self._last_config or {}
            output_block = cfg.get("output") if isinstance(cfg, dict) else None

            # Check if custom summary builder is specified
            summary_builder_id = None
            if isinstance(output_block, dict):
                summary_builder_id = output_block.get("summary_builder")

            if summary_builder_id and self.last_network:
                # Use custom summary builder
                from .summary_builder import build_summary_from_simulation

                summary = build_summary_from_simulation(
                    simulation=self.last_network,
                    config=cfg,
                    simulation_data=results,
                    builder_id=summary_builder_id,
                )
                results["summary"] = summary
            elif output_block is not None:
                # Use traditional output block parsing
                items = parse_output_block(output_block)
                summary = evaluate_output_items(items, results)
                results["summary"] = summary
            elif self.last_network:
                # Use default summary builder if no output configuration
                from .summary_builder import build_summary_from_simulation

                summary = build_summary_from_simulation(
                    simulation=self.last_network,
                    config=cfg,
                    simulation_data=results,
                )
                results["summary"] = summary

            # Log summary in verbose mode
            if is_verbose_mode():
                from .output_summary import format_summary_text

                summary_text = format_summary_text(results.get("summary", []))
                logger.info(f"📊 Output Summary:\n{summary_text}")
        except Exception as e:
            # Do not fail the simulation due to summary issues; log and continue
            logger.warning(f"Failed to evaluate custom output summary: {e}")

        return results

    def _get_available_species_for_sankey(self) -> List[str]:
        """Dynamically determine which species to use for Sankey diagram generation.

        Returns a list of species that are available in the mechanism and commonly
        used for energy flow analysis. Handles networks with multiple mechanisms.
        """
        if not self.network or not self.network.reactors:
            return []

        try:
            # Define priority species for energy flow analysis (in order of preference)
            # Only include species that are implemented in the Sankey generation code
            priority_species = [
                # Currently implemented species in Sankey generation
                "H2",  # Hydrogen - implemented
                "CH4",  # Methane - implemented
                # Note: Other species like H2O, CO2, etc. are not yet implemented in Sankey
                # and will cause "not implemented yet" errors, so we exclude them for now
            ]

            # Check all reactors in the network to find available species
            # Different reactors might use different mechanisms
            all_available_species = set()
            for reactor in self.network.reactors:
                try:
                    reactor_species = set(reactor.phase.species_names)
                    all_available_species.update(reactor_species)
                except Exception as e:
                    logger.debug(
                        f"Could not get species from reactor {reactor.name}: {e}"
                    )
                    continue

            # Find implemented species that are available in at least one reactor
            available_species = []
            for species in priority_species:
                if species in all_available_species:
                    available_species.append(species)

            # If no implemented species found, disable species-based Sankey generation
            # This prevents "not implemented yet" errors
            if not available_species:
                logger.info(
                    f"No implemented species found for Sankey diagram in network with "
                    f"{len(all_available_species)} total species, disabling species-based analysis"
                )
                return []  # Empty list disables species-based Sankey generation

            logger.info(f"Found implemented species for Sankey: {available_species}")
            return available_species

        except Exception as e:
            logger.warning(f"Could not determine species for Sankey diagram: {e}")
            # Return empty list to disable species-based Sankey generation
            return []

    def build_network_and_code(
        self, config: Dict[str, Any]
    ) -> Tuple[Any, Dict[str, Any], str]:
        """Legacy method for backward compatibility - runs full simulation at once."""
        network = self.build_network(config)
        results, code_str = self.run_streaming_simulation()
        return network, results, code_str
