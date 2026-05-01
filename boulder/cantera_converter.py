import importlib
import math
import os
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    cast,
)

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
#: ``node_dict -> {"nodes": [...], "connections": [...]}``
#: Called during ``normalize_config`` to expand a composite reactor kind into
#: its satellite nodes and connections before any Cantera build runs.
ReactorUnfolder = Callable[[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]


@dataclass
class BoulderPlugins:
    """A container for discovered Boulder plugins."""

    reactor_builders: Dict[str, ReactorBuilder] = field(default_factory=dict)
    connection_builders: Dict[str, ConnectionBuilder] = field(default_factory=dict)
    post_build_hooks: List[PostBuildHook] = field(default_factory=list)
    #: Per-kind unfolders that emit satellite nodes/connections at config-normalise time.
    #: Registered via :func:`boulder.register_reactor_unfolder`.
    reactor_unfolders: Dict[str, ReactorUnfolder] = field(default_factory=dict)
    output_pane_plugins: List[Any] = field(
        default_factory=list
    )  # Import will be handled dynamically
    summary_builders: Dict[str, Any] = field(
        default_factory=dict
    )  # Summary builder plugins
    sankey_generator: Optional[Callable] = None  # Custom Sankey generation function
    #: ``(gas, new_mechanism, htol, Xtol) -> ct.Solution``
    #: Called when an inter-stage connection carries a ``mechanism_switch`` block.
    #: Registered by an external plugin package via its plugin entry point.
    mechanism_switch_fn: Optional[Callable] = None

    #: Per-source provenance for introspection (``boulder plugins list``).
    #: ``{"entry_point": [(ep_name, module)], "env_var": [module_name]}``.
    sources: Dict[str, List[Any]] = field(
        default_factory=lambda: {
            "entry_point": [],
            "env_var": [],
        }
    )


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


def resolve_dotted_path(dotted: str) -> Any:
    """Resolve a dotted path of the form ``pkg.mod:Symbol`` or ``pkg.mod.Symbol``.

    Used to load YAML-declared ``network_class`` overrides and other
    plugin-provided callables referenced as strings in the configuration.
    """
    if not isinstance(dotted, str) or not dotted:
        raise ValueError(f"Expected non-empty string for dotted path, got {dotted!r}")
    if ":" in dotted:
        module_name, _, attr = dotted.partition(":")
    else:
        module_name, _, attr = dotted.rpartition(".")
        if not module_name:
            raise ValueError(
                f"Dotted path {dotted!r} must be of the form 'pkg.mod:Symbol' "
                "or 'pkg.mod.Symbol'."
            )
    module = importlib.import_module(module_name)
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise ImportError(
            f"Module {module_name!r} has no attribute {attr!r} "
            f"(while resolving dotted path {dotted!r})."
        ) from exc


def _select_network_class_for_stage(
    converter: "DualCanteraConverter",
    stage_id: Optional[str],
    stage_nodes: List[Dict[str, Any]],
    non_res_ids: List[str],
) -> Tuple[Any, Dict[str, Any]]:
    """Pick the ReactorNet class for a single stage.

    Precedence (high -> low):

    1. Per-node YAML ``network_class`` dotted-path override.
    2. ``reactor.NETWORK_CLASS`` class attribute.
    3. :class:`cantera.ReactorNet`.

    Raises
    ------
    ValueError
        If two reactors in the same stage resolve to different non-default
        classes.  Previously the first-wins silent fallback hid misconfiguration.
    """
    node_by_id: Dict[str, Dict[str, Any]] = {n["id"]: n for n in stage_nodes}

    resolved: Optional[Any] = None
    resolved_from: Optional[str] = None
    owner_rid: Optional[str] = None
    net_kw: Dict[str, Any] = {}

    for rid in non_res_ids:
        reactor = converter.reactors[rid]
        node_dict = node_by_id.get(rid, {})
        props = node_dict.get("properties") or {}

        candidate: Optional[Any] = None
        source: Optional[str] = None

        dotted = node_dict.get("network_class") or props.get("network_class")
        if dotted:
            candidate = resolve_dotted_path(str(dotted))
            source = f"YAML node {rid!r}.network_class"
        elif hasattr(reactor, "NETWORK_CLASS"):
            candidate = reactor.NETWORK_CLASS
            source = f"{type(reactor).__name__}.NETWORK_CLASS"

        if candidate is None:
            continue
        if resolved is None:
            resolved = candidate
            resolved_from = source
            owner_rid = rid
        elif candidate is not resolved:
            raise ValueError(
                f"Stage {stage_id!r} has conflicting ReactorNet overrides: "
                f"{resolved!r} (from {resolved_from} on reactor {owner_rid!r}) "
                f"vs {candidate!r} (from {source}). Split these reactors "
                "into separate groups or remove the conflicting override."
            )

    if resolved is None:
        return ct.ReactorNet, {}

    if owner_rid is not None:
        net_kw["meta"] = converter.reactor_meta.get(owner_rid, {})
    return resolved, net_kw


def resolve_unset_flow_rates(
    mfc_topology: Dict[str, Tuple[str, str]],
    flow_rates: Dict[str, float],
    mfc_objects: Dict[str, "ct.MassFlowController"],
    reactors: Mapping[str, "ct.ReactorBase"],
    unresolved_ids: Set[str],
) -> None:
    """Resolve mass flow rates for MFCs not specified in the config.

    Applies steady-state mass conservation at each non-Reservoir reactor node::

        sum(incoming mass flows) == sum(outgoing mass flows)

    Iterates until all unresolved MFCs are determined. Raises ``ValueError``
    if the system is underdetermined (more than one unknown per node at any step).

    Parameters
    ----------
    mfc_topology :
        Mapping from connection ID to ``(source_node_id, target_node_id)``
        for every MFC in the network (resolved and unresolved).
    flow_rates :
        Mapping from connection ID to the known mass flow rate (kg/s).
        Unresolved IDs are absent; resolved ones are added here in-place.
        Callers must not read ``ct.MassFlowController.mass_flow_rate`` directly
        because that property requires an initialized ``ReactorNet``.
    mfc_objects :
        Mapping from connection ID to the Cantera ``MassFlowController`` object.
        Resolved flow rates are written to the MFC objects via the setter, which
        works before the network is initialized.
    reactors :
        All reactor/reservoir objects keyed by node ID.
        ``ct.Reservoir`` nodes are excluded from conservation.
    unresolved_ids :
        Set of connection IDs whose ``mass_flow_rate`` was not specified in the
        config. Modified in-place: IDs are removed as they are resolved.

    Raises
    ------
    ValueError
        If a resolved flow rate is negative (inconsistent inlet conditions),
        or if any MFC remains unresolved after no further progress can be made.
    """
    remaining = set(unresolved_ids)

    while remaining:
        progress = False
        for reactor_id, reactor in list(reactors.items()):
            if isinstance(reactor, ct.Reservoir):
                continue

            in_mfcs = [
                cid
                for cid, (src, tgt) in mfc_topology.items()
                if tgt == reactor_id and cid in mfc_objects
            ]
            out_mfcs = [
                cid
                for cid, (src, tgt) in mfc_topology.items()
                if src == reactor_id and cid in mfc_objects
            ]

            unset_in = [cid for cid in in_mfcs if cid in remaining]
            unset_out = [cid for cid in out_mfcs if cid in remaining]
            n_unset = len(unset_in) + len(unset_out)

            if n_unset != 1:
                continue  # Cannot uniquely resolve at this node yet

            known_in = sum(
                flow_rates.get(cid, 0.0) for cid in in_mfcs if cid not in remaining
            )
            known_out = sum(
                flow_rates.get(cid, 0.0) for cid in out_mfcs if cid not in remaining
            )

            if unset_in:
                resolved_flow = known_out - known_in
                cid = unset_in[0]
            else:
                resolved_flow = known_in - known_out
                cid = unset_out[0]

            if resolved_flow < 0.0:
                raise ValueError(
                    f"Mass conservation yields a negative flow rate "
                    f"({resolved_flow:.4g} kg/s) for connection '{cid}'. "
                    "Check the inlet mass flow rates."
                )

            flow_rates[cid] = resolved_flow
            mfc_objects[cid].mass_flow_rate = resolved_flow  # type: ignore[misc]
            remaining.discard(cid)
            unresolved_ids.discard(cid)
            progress = True
            break  # restart loop to propagate newly resolved value

        if not progress:
            break

    if remaining:
        raise ValueError(
            f"Cannot determine mass flow rate for connection(s): {sorted(remaining)}. "
            "Specify mass_flow_rate explicitly, or ensure exactly one unknown "
            "per reactor node so that mass conservation uniquely determines it."
        )


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
                    ep_module = getattr(ep, "value", None) or getattr(ep, "module", "")
                    plugins.sources["entry_point"].append((ep.name, ep_module))
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
                    plugins.sources["env_var"].append(mod_name)
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
            resolved_mechanism = self.resolve_mechanism(self.mechanism)
            self.gas = ct.Solution(resolved_mechanism)
        except Exception as e:
            raise ValueError(f"Failed to load mechanism '{self.mechanism}': {e}")
        # Cache of mechanisms -> Solution to support per-node overrides
        self._gases_by_mech: Dict[str, ct.Solution] = {resolved_mechanism: self.gas}
        self.reactors: Dict[str, ct.ReactorBase] = {}
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
        # Flow-conservation tracking: populated during connection building
        self._unresolved_mfc_ids: Set[str] = set()
        self._mfc_topology: Dict[str, Tuple[str, str]] = {}  # conn_id -> (src, tgt)
        self._mfc_flow_rates: Dict[str, float] = {}  # known flow rates (kg/s)

    def parse_composition(self, comp_str: str) -> Dict[str, float]:
        comp_dict = {}
        for pair in comp_str.split(","):
            species, value = pair.split(":")
            comp_dict[species.strip()] = float(value)
        return comp_dict

    # ------------------------------------------------------------------
    # Low-level helpers shared by build_network / build_sub_network
    # ------------------------------------------------------------------

    def resolve_mechanism(self, name: str) -> str:
        """Resolve a mechanism name to a path.

        Default implementation returns ``name`` unchanged, allowing Cantera to
        handle bare built-in names (e.g. ``"gri30.yaml"``) directly.
        Subclasses may override this to implement custom mechanism search paths
        without requiring a plugin registration.
        """
        return name

    def script_load_lines(self, config_path: str, plan: Any = None) -> list:
        """Return the staged-solve block for the generated standalone script.

        The block uses :class:`~boulder.runner.BoulderRunner` class methods
        only — no free-function imports.  When *plan* is provided its stage
        list is unrolled into one :meth:`~boulder.runner.BoulderRunner.solve_stage`
        call per stage with a comment showing the stage id and node list.

        Subclasses may override this to substitute their own runner class name
        and import line in emitted scripts.

        Parameters
        ----------
        config_path :
            Path to the original YAML file, embedded verbatim in the script.
        plan :
            :class:`~boulder.staged_solver.StageExecutionPlan` produced by
            ``build_stage_graph()``.  When ``None`` the stage loop is omitted
            and a plain ``runner.build()`` call is emitted instead.
        """
        runner_import = "from boulder.runner import BoulderRunner"
        runner_class = "BoulderRunner"
        return self._script_lines_for_runner(
            runner_import, runner_class, config_path, plan
        )

    @staticmethod
    def _script_lines_for_runner(
        runner_import: str,
        runner_class: str,
        config_path: str,
        plan: Any,
    ) -> list:
        """Shared helper: emit the runner-based staged-solve script block."""
        lines = [
            runner_import,
            "",
            f"config_path = {repr(config_path)}",
            f"runner = {runner_class}.from_yaml(config_path)",
            "plan = runner.build_stage_graph()",
            "trajectory = runner.new_trajectory()",
            "inlet_states = {}",
            "",
        ]
        if plan is not None and plan.ordered_stages:
            n = len(plan.ordered_stages)
            for i, stage in enumerate(plan.ordered_stages):
                node_list = ", ".join(stage.node_ids)
                lines += [
                    f"# Stage {i + 1}/{n}: {stage.id}  [nodes: {node_list}]",
                    f"runner.solve_stage(plan, plan.ordered_stages[{i}], "
                    "inlet_states, trajectory)",
                    "",
                ]
        else:
            lines += ["runner.build()", ""]
        lines += [
            "# Assemble visualization network from all converged states",
            "runner.build_viz_network(plan, trajectory)",
            "network = runner.network",
            "converter = runner.converter",
        ]
        return lines

    def _get_gas_for_mech(self, mech_name: str) -> ct.Solution:
        """Return (creating and caching if needed) a :class:`~cantera.Solution`.

        Uses ``resolve_mechanism`` so subclass overrides are honored for both
        the top-level mechanism and per-node mechanism switches.
        """
        resolved = self.resolve_mechanism(mech_name)
        if resolved in self._gases_by_mech:
            return self._gases_by_mech[resolved]
        gas_obj = ct.Solution(resolved)
        self._gases_by_mech[resolved] = gas_obj
        return gas_obj

    def set_reactor_volume(
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

    def create_reactor_from_node(
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
            reactor = ct.Reservoir(gas_for_node, clone=True)  # type: ignore[assignment]
            reactor.name = rid
        else:
            raise ValueError(f"Unsupported reactor type: '{typ}'")

        self.set_reactor_volume(reactor, props, rid)
        try:
            reactor.group_name = str(props.get("group", props.get("group_name", "")))
        except Exception:
            pass

        return reactor

    def build_connection(self, conn: Dict[str, Any]) -> None:
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
            self._mfc_topology[cid] = (src, tgt)
            mfc = ct.MassFlowController(self.reactors[src], self.reactors[tgt])
            if "mass_flow_rate" in props:
                mfr = float(props["mass_flow_rate"])
                mfc.mass_flow_rate = mfr  # type: ignore[misc]
                self._mfc_flow_rates[cid] = mfr
            else:
                mfc.mass_flow_rate = 0.0  # type: ignore[misc]  # resolved by conservation
                self._unresolved_mfc_ids.add(cid)
            self.connections[cid] = mfc
        elif typ == "Valve":
            coeff = float(props.get("valve_coeff", 1.0))
            valve = ct.Valve(self.reactors[src], self.reactors[tgt])
            valve.valve_coeff = coeff  # type: ignore[attr-defined]
            self.connections[cid] = valve
        elif typ == "PressureController":
            master_id = props.get("master")
            if not master_id:
                raise ValueError(
                    f"PressureController '{cid}' requires a 'master' property "
                    "pointing at an already-declared MassFlowController."
                )
            master = self.connections.get(master_id)
            if master is None:
                raise ValueError(
                    f"PressureController '{cid}' master '{master_id}' not found; "
                    "ensure the master MassFlowController is declared earlier "
                    "in connections: (or via an inlet port on an upstream node)."
                )
            if not isinstance(master, ct.MassFlowController):
                raise ValueError(
                    f"PressureController '{cid}' master '{master_id}' must be a "
                    f"MassFlowController, got {type(master).__name__}."
                )
            coeff = float(props.get("pressure_coeff", 0.0))
            pc = ct.PressureController(self.reactors[src], self.reactors[tgt])
            pc.primary = master  # type: ignore[attr-defined]
            pc.pressure_coeff = coeff  # type: ignore[attr-defined]
            self.connections[cid] = pc
        elif typ == "Wall":
            if "electric_power_kW" in props:
                # Torch-style wall: constant power delivered via electric heating.
                torch_eff = float(props.get("torch_eff", 1.0))
                gen_eff = float(props.get("gen_eff", 1.0))
                Q_watts = float(props["electric_power_kW"]) * 1e3 * torch_eff * gen_eff
                area = float(props.get("area", 1.0))
                wall = ct.Wall(
                    self.reactors[src],
                    self.reactors[tgt],
                    A=area,
                    Q=lambda t: Q_watts,
                    name=cid,  # type: ignore[arg-type]
                )
            else:
                # Generic passive wall: heat_flux=0 by default, settable post-build.
                area = float(props.get("area", 1.0))
                wall = ct.Wall(
                    self.reactors[src],
                    self.reactors[tgt],
                    A=area,
                    name=cid,  # type: ignore[arg-type]
                )
                if "heat_flux" in props:
                    wall.heat_flux = float(props["heat_flux"])
            self.walls[cid] = wall
        else:
            raise ValueError(f"Unsupported connection type: '{typ}'")

    def apply_flow_conservation(self) -> None:
        """Resolve unset MFC flow rates via mass conservation, then reset tracking state.

        Called after all connections for a network (or sub-network stage) have been
        built. MFCs without an explicit ``mass_flow_rate`` in the YAML config are
        resolved by enforcing steady-state mass conservation at each non-Reservoir
        reactor node. Resolved values are also appended to ``code_lines`` so the
        ``--download`` script reflects the actual flow rates.

        Raises
        ------
        ValueError
            Propagated from :func:`resolve_unset_flow_rates` if any flow rate
            cannot be uniquely determined.
        """
        originally_unresolved = set(self._unresolved_mfc_ids)
        if originally_unresolved:
            all_mfcs: Dict[str, ct.MassFlowController] = {
                cid: dev  # type: ignore[assignment]
                for cid, dev in self.connections.items()
                if isinstance(dev, ct.MassFlowController)
            }
            resolve_unset_flow_rates(
                self._mfc_topology,
                self._mfc_flow_rates,
                all_mfcs,
                self.reactors,
                self._unresolved_mfc_ids,
            )
            for cid in originally_unresolved:
                resolved_rate = self._mfc_flow_rates[cid]
                cid_var = _make_valid_python_identifier(cid)
                self.code_lines.append(
                    f"{cid_var}.mass_flow_rate = {resolved_rate}"
                    "  # resolved by mass conservation"
                )
        # Only clear the pending set. Keep _mfc_topology and _mfc_flow_rates so
        # later stages (and the post-solve viz network pass) can resolve MFCs
        # against the FULL cross-stage topology.
        self._unresolved_mfc_ids = set()

    def post_build(self, config: Dict[str, Any]) -> None:
        """Run registered post-build hooks on a (sub-)config.

        Called once per stage (with the stage subset config) and once after the
        full viz network is built. Default iterates ``plugins.post_build_hooks``.
        Subclasses may override to add behavior without touching the plugin list.
        """
        for hook in self.plugins.post_build_hooks:
            try:
                hook(self, config)
            except Exception as exc:
                logger.warning("Post-build hook failed: %s", exc)

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
    ) -> Tuple["ct.ReactorNet", Dict[str, "ct.ReactorBase"]]:
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
            ``stage_reactors`` is a ``{node_id: ct.ReactorBase}`` dict for
            this stage (a subset of ``self.reactors``).
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

            reactor = self.create_reactor_from_node(node, gas_for_node)

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

        # Build intra-stage connections.  Do NOT reset _mfc_topology or
        # _mfc_flow_rates — they accumulate across stages so the final
        # viz-network conservation pass sees the full cross-stage topology.
        self._unresolved_mfc_ids = set()
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
                self.build_connection(conn)
            except Exception as exc:
                logger.warning(
                    "Stage '%s': failed to build connection '%s': %s",
                    stage_id,
                    cid,
                    exc,
                )

        self.apply_flow_conservation()

        # Apply post-build hooks for this stage's subset
        stage_config_subset: Dict[str, Any] = {
            "nodes": stage_nodes,
            "connections": stage_connections,
        }
        self.post_build(stage_config_subset)

        # Build ReactorNet (non-Reservoir reactors only)
        non_res_ids = [
            rid
            for rid in stage_reactor_ids
            if not isinstance(self.reactors[rid], ct.Reservoir)
        ]

        # Select ReactorNet class with precedence:
        #   1. Per-node YAML ``network_class`` dotted-path override.
        #   2. ``reactor.NETWORK_CLASS`` class attribute (e.g. DesignPFRNet).
        #   3. ``ct.ReactorNet`` default.
        #
        # If two reactors in the same stage resolve to different non-default
        # network classes, raise an error (previously the first-wins silent
        # fallback hid a latent misconfiguration).
        ReactorNetClass, net_kw = _select_network_class_for_stage(
            self, stage_id, stage_nodes, non_res_ids
        )

        rseq = [self.reactors[rid] for rid in non_res_ids]
        network = ReactorNetClass(cast(Sequence[ct.Reactor], rseq), **net_kw)
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

        The returned network is initialized with ``advance(0.0)`` so flow-device
        properties (``mass_flow_rate``) are ready for downstream reporting.

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
                self.build_connection(conn)
            except Exception as exc:
                logger.warning(
                    "Viz network: could not build connection '%s': %s", cid, exc
                )

        # Resolve any MFC mass flow rates that were still pending once all
        # inter-stage devices are in place.  Until now intra-stage passes only
        # saw a sub-topology; mixers on stage boundaries (SPRING_A3 shape) or
        # inter-stage MFCs without explicit mass_flow_rate would otherwise
        # stay at 0 kg/s and make Sankey bands collapse.
        self.apply_flow_conservation()

        non_res = [r for r in self.reactors.values() if not isinstance(r, ct.Reservoir)]
        viz_net = ct.ReactorNet(cast(Sequence[ct.Reactor], non_res))
        viz_net.advance(0.0)
        self.network = viz_net
        self.last_network = viz_net
        return viz_net

    def build_network(
        self,
        config: Dict[str, Any],
        progress_callback: Optional[Callable] = None,
    ) -> ct.ReactorNet:
        """Build and solve the Cantera network through the staged solver.

        ``normalize_config`` guarantees that the config has a top-level
        ``groups`` section (synthesising a single ``default`` group when the
        YAML does not declare one), so this method always delegates to
        :func:`~boulder.staged_solver.solve_staged`.  It builds one sub-
        :class:`~cantera.ReactorNet` per stage, solves each according to its
        ``solve_directive`` and returns a visualization ReactorNet with all
        reactors in their converged state.  The Lagrangian trajectory is
        stored on ``self._staged_trajectory``.

        Parameters
        ----------
        config :
            Normalised and validated configuration dict.
        progress_callback :
            Optional ``(stage_id: str, n_done: int, n_total: int) -> None``
            called after each stage completes.  Forwarded to
            :func:`~boulder.staged_solver.solve_staged`.
        """
        self._last_config = config

        if not config.get("groups"):
            raise ValueError(
                "build_network requires a config with a 'groups' section. "
                "Call normalize_config() first — it synthesises a single "
                "'default' group when the YAML has none."
            )

        from .staged_solver import build_stage_graph, solve_staged

        plan = build_stage_graph(config)
        trajectory = solve_staged(
            self, plan, config, progress_callback=progress_callback
        )
        self._staged_trajectory = trajectory

        # Generate a downloadable script mirroring the staged load+build flow.
        # When called from BoulderRunner.build(), code_lines is overwritten
        # afterwards with the plan-aware unrolled version. This fallback
        # serves direct callers (e.g. SimulationWorker) that bypass the runner.
        download_path = getattr(self, "_download_config_path", None) or "config.yaml"
        self.code_lines = [
            "# Load configuration from YAML and build Cantera network",
            "import cantera as ct",
            *self.script_load_lines(download_path, plan),
        ]
        # viz_network is already set on self.network by build_viz_network
        return self.network  # type: ignore[return-value]

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
            settings_config = config.get("settings") or {}

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

        # ``build_network`` always routes through the staged solver, so by the
        # time we get here the reactor states are already converged.  Calling
        # ``network.advance()`` on that fully-solved network is not only
        # redundant, it can diverge numerically (mechanism-switch networks
        # contain reactors with mismatched species lists that were only
        # integrated independently inside their own stage sub-network).  We
        # therefore emit a downloadable script that just prints the final
        # states, and capture a single-time-point "trajectory" for the UI.
        already_solved = getattr(self, "_staged_trajectory", None) is not None

        self.code_lines.append("")
        self.code_lines.append("# ===== SIMULATION EXECUTION =====")
        if already_solved:
            self.code_lines.append(
                "# solve_stage() has already solved each stage sequentially;"
            )
            self.code_lines.append(
                "# network = runner.network holds the converged reactor states."
            )
            self.code_lines.append("print('Simulation completed (staged solve).')")
            self.code_lines.append("print('Reactor\\tT [K]\\tP [Pa]')")
            self.code_lines.append("for r in network.reactors:")
            self.code_lines.append(
                '    print(f"{r.name}\\t{r.phase.T:.2f}\\t{r.phase.P:.2f}")'
            )
        else:
            self.code_lines.append("# Import numpy for time array generation")
            self.code_lines.append("import numpy as np")
            self.code_lines.append("")
            self.code_lines.append(
                f"# Create time array: 0 to {simulation_time}s with {time_step}s steps"
            )
            self.code_lines.append(
                f"times = np.arange(0, {simulation_time}, {time_step})"
            )
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

        if already_solved:
            # Network already converged by the staged solver — record the
            # final per-reactor state as a single time point and skip the
            # (redundant, potentially-diverging) ``network.advance`` loop.
            # We still call ``advance(0.0)`` once so that Cantera marks the
            # flow devices as "ready" (otherwise downstream consumers such as
            # the Sankey generator would raise ``FlowDevice::massFlowRate:
            # Flow device is not ready``).
            try:
                self.network.advance(0.0)
            except Exception as e:
                logger.warning(
                    f"Post-staged network.advance(0) warmup failed, "
                    f"flow-device reads may be unavailable: {e}"
                )
            times.append(0.0)
            for reactor in reactor_list:
                reactor_id = getattr(reactor, "name", "") or str(id(reactor))
                reactor_gas = self.reactor_meta.get(reactor_id, {}).get(
                    "gas_solution", self.gas
                )
                reactor_species_names = reactor_gas.species_names
                T = float(reactor.phase.T)
                P = float(reactor.phase.P)
                X_vec = reactor.phase.X
                Y_vec = reactor.phase.Y
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
                    },
                    simulation_time,
                    simulation_time,
                )
            results = self.finalize_results(times, reactors_series)
            return results, "\n".join(self.code_lines)

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
        """Build+solve the network and return ``(network, results, code_str)``.

        ``build_network`` now solves the whole network through the staged
        solver, so ``results`` only reports what the staged path already
        produced: the converged per-reactor states (as a single-time-point
        SolutionArray) and any scalars stored by post-build hooks.
        """
        network = self.build_network(config)
        results: Dict[str, Any] = {
            "time": [0.0],
            "reactors": {
                rid: {
                    "T": [float(r.phase.T)],
                    "P": [float(r.phase.P)],
                    "X": {
                        s: [float(r.phase.X[r.phase.species_index(s)])]
                        for s in r.phase.species_names
                    },
                    "Y": {
                        s: [float(r.phase.Y[r.phase.species_index(s)])]
                        for s in r.phase.species_names
                    },
                }
                for rid, r in self.reactors.items()
                if not isinstance(r, ct.Reservoir)
            },
            "trajectory": getattr(self, "_staged_trajectory", None),
        }
        code_str = "\n".join(self.code_lines)
        return network, results, code_str
