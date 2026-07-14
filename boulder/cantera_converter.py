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

from .config import CANTERA_MECHANISM, TRANSIENT_SOLVER_KINDS
from .output_summary import evaluate_output_items, parse_output_block
from .reactor_energy import (
    build_reactor_with_energy,
    validate_energy_on_built_reactor,
    validate_explicit_energy,
)
from .sankey import generate_sankey_input_from_sim, sankey_links_for_api
from .spatial_inference import try_infer_spatial_reactor_series
from .staged_solver import _order_stage_nodes_for_flow
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
    gui_actions: List[Any] = field(default_factory=list)
    cache_contributors: List[Any] = field(default_factory=list)
    sankey_generator: Optional[Callable] = None  # Custom Sankey generation function
    #: Hex color mapping for species bands in the Sankey diagram.
    #: Keys: ``"H2"``, ``"CH4"``, ``"Cs"`` (and any others the plugin wants to add).
    #: Registered by an external plugin via the ``boulder.plugins`` entry
    #: point.  When ``None``, Boulder falls back to its own light-theme defaults.
    sankey_link_colors: Optional[Dict[str, str]] = None
    #: ``(gas, new_mechanism, htol, Xtol) -> ct.Solution``
    #: Called when an inter-stage connection carries a ``mechanism_switch`` block.
    #: Registered by an external plugin package via its plugin entry point.
    mechanism_switch_fn: Optional[Callable] = None
    #: ``(config: dict) -> dict`` transforms applied to the raw STONE config at the
    #: start of :func:`normalize_config`, before dialect detection. Lets a host
    #: derive recognised STONE fields from its own ``export``/``metadata`` blocks
    #: (e.g. a transient ``settings.solver`` grid from a residence-time spec)
    #: without editing the YAML. Each returns the (possibly new) config; a raising
    #: transform is skipped. Registered by an external plugin package.
    config_transforms: List[Callable[[Dict[str, Any]], Dict[str, Any]]] = field(
        default_factory=list
    )
    #: Extra ``python`` args that run a host's scenario/sweep runner for the Run
    #: Sweep button, invoked as ``[python, *sweep_runner, <config>, "--no-plot"]``.
    #: e.g. ``["-m", "<host_pkg>.scenario_sweep"]``. Used when no ``run_sweep.py``
    #: sits next to the config. Registered by an external plugin package.
    sweep_runner: Optional[List[str]] = None

    #: GUI branding set by a host plugin: ``{"name": "MyApp", "version": "1.2"}``.
    #: When set, the frontend header shows the host name and version next to
    #: the Boulder title.
    branding: Optional[Dict[str, str]] = None

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
    stage_network_class: Optional[str] = None,
) -> Tuple[Any, Dict[str, Any]]:
    """Pick the ReactorNet class for a single stage.

    Precedence (high -> low):

    0. Stage-level ``network_class`` dotted-path (set on the group config,
       e.g. by a composite-reactor unfolder).  When present, this takes top
       precedence and the per-reactor conflict scan is **skipped** entirely,
       allowing multiple child reactors with their own ``NETWORK_CLASS`` to
       coexist inside one composite stage.
    1. Per-node YAML ``network_class`` dotted-path override.
    2. ``reactor.NETWORK_CLASS`` class attribute.
    3. :class:`cantera.ReactorNet`.

    Parameters
    ----------
    stage_network_class :
        Optional dotted-path string from the stage/group config.  When not
        ``None`` it bypasses the per-reactor scan entirely.

    Raises
    ------
    ValueError
        If two reactors in the same stage resolve to different non-default
        classes (only when *stage_network_class* is ``None``).
    """
    # Precedence 0: stage-level override — skips all per-reactor conflict logic.
    if stage_network_class:
        resolved_class = resolve_dotted_path(str(stage_network_class))
        return resolved_class, {}

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


def _series_from_stage_states(
    states: Any, scalars: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """Flatten a stage network's ``.states`` SolutionArray into a GUI series.

    A :class:`~boulder.stage_network.CustomStageNetwork` that integrates its
    whole stage internally (its own macro-grid, a single ``advance`` call)
    records the real trajectory in :attr:`~boulder.stage_network.CustomStageNetwork.states`.
    The per-step trajectory recorder cannot see such a solve (it observes only
    the outer reactor state at each grid step), so this surfaces the recorded
    profile as the reactor's time series for the plots and output panes.

    Returns ``None`` when there is no usable (>= 2 point) trajectory. Any extra
    SolutionArray columns (e.g. plugin-specific ``T_e``/``n_e``) and the
    network's JSON-serialisable ``scalars`` are carried through verbatim so
    downstream panes can consume them.
    """
    # Errors expected from a SolutionArray/phase that doesn't support a given
    # accessor (missing attribute, wrong shape/dtype, or a Cantera-native
    # rejection e.g. for a phase type without the requested property) -- never
    # a bare `except Exception`, so a genuine bug elsewhere still surfaces.
    _states_errors = (AttributeError, ValueError, TypeError, ct.CanteraError)

    if states is None:
        return None
    try:
        t_col = [float(v) for v in states.t]
    except _states_errors as exc:
        logger.debug("Stage states have no usable time column: %s", exc)
        return None
    if len(t_col) < 2:
        return None

    # Core state variables come straight from the array; ``to_pandas`` is used
    # only to enumerate the plugin-specific extra columns (``T_e``, ``n_e``, ...)
    # since their names are not known ahead of time.
    series: Dict[str, Any] = {
        "t": t_col,
        "T": [float(v) for v in states.T],
        "P": [float(v) for v in states.P],
    }
    # Species composition is optional: a phase with no species, or one whose
    # composition Cantera can't expose here (e.g. some incompressible/pure-fluid
    # phases), must not stop the core T/P/t series from being returned.
    try:
        names = list(states.species_names)
    except _states_errors as exc:
        logger.debug("Stage states expose no species composition: %s", exc)
        names = []
    if names:
        try:
            x_mat = np.atleast_2d(np.asarray(states.X, dtype=float))
            if x_mat.shape[0] == len(t_col):
                series["X"] = {
                    sp: [float(x_mat[i, j]) for i in range(x_mat.shape[0])]
                    for j, sp in enumerate(names)
                }
        except _states_errors as exc:
            logger.debug("Could not read mole fractions from stage states: %s", exc)
        try:
            y_mat = np.atleast_2d(np.asarray(states.Y, dtype=float))
            if y_mat.shape[0] == len(t_col):
                series["Y"] = {
                    sp: [float(y_mat[i, j]) for i in range(y_mat.shape[0])]
                    for j, sp in enumerate(names)
                }
        except _states_errors as exc:
            logger.debug("Could not read mass fractions from stage states: %s", exc)
    try:
        frame = states.to_pandas()
    except _states_errors as exc:
        logger.debug("Could not read extra columns from stage states: %s", exc)
        frame = None
    if frame is not None:
        for col in frame.columns:
            if col in series or col in ("density", "D") or col.startswith(("X_", "Y_")):
                continue
            series[col] = [float(v) for v in frame[col].tolist()]

    for key, value in (scalars or {}).items():
        series.setdefault(key, value)
    return series


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

    try:
        from .gui_actions import get_gui_action_registry

        plugins.gui_actions = get_gui_action_registry().actions.copy()
    except ImportError as e:
        logger.debug(f"GUI action plugins not available: {e}")

    try:
        from .result_cache import get_cache_contributor_registry

        plugins.cache_contributors = (
            get_cache_contributor_registry().contributors.copy()
        )
    except ImportError as e:
        logger.debug(f"Cache contributor plugins not available: {e}")

    _PLUGIN_CACHE = plugins

    if is_verbose_mode():
        logger.info(
            f"Plugin discovery complete: {len(plugins.reactor_builders)} reactor builders, "
            f"{len(plugins.connection_builders)} connection builders, "
            f"{len(plugins.post_build_hooks)} post-build hooks, "
            f"{len(plugins.output_pane_plugins)} output pane plugins, "
            f"{len(plugins.summary_builders)} summary builders, "
            f"{len(plugins.gui_actions)} GUI actions, "
            f"{len(plugins.cache_contributors)} cache contributors"
        )

    return plugins


class _TrajectoryRecorder:
    """Capture full reactor state at each transient grid step.

    Driven by the existing ``_scope_recorder.record(t)`` hook in
    :meth:`_run_transient_solver`. The staged ``advance_grid`` solve already steps
    each reactor through every grid time; this captures the per-reactor state at
    each step so the GUI can show the real ``T(t)`` trajectory. The network is
    therefore solved **once** — no re-integration. It does not modify the solve
    (the ``record`` calls already exist) and produces no side effects.
    """

    def __init__(self, converter: "DualCanteraConverter") -> None:
        self._converter = converter
        self._data: Dict[str, Dict[str, Any]] = {}

    def record(self, t: float) -> None:
        try:
            reactors = self._converter._unique_non_reservoir_reactors()
        except Exception:  # noqa: BLE001 — recording must never break the solve
            return
        for reactor in reactors:
            rid = getattr(reactor, "name", "") or str(id(reactor))
            phase = reactor.phase
            d = self._data.setdefault(
                rid,
                {
                    "t": [],
                    "T": [],
                    "P": [],
                    "X": [],
                    "Y": [],
                    "names": list(phase.species_names),
                },
            )
            d["t"].append(float(t))
            d["T"].append(float(phase.T))
            d["P"].append(float(phase.P))
            d["X"].append(phase.X.copy())
            d["Y"].append(phase.Y.copy())

    def series(self) -> Dict[str, Dict[str, Any]]:
        """Return ``{reactor_id: series}`` for reactors with a real trajectory."""
        import numpy as np

        out: Dict[str, Dict[str, Any]] = {}
        for rid, d in self._data.items():
            if len(d["t"]) < 2:
                continue
            names = d["names"]
            xmat = np.asarray(d["X"], dtype=float)
            ymat = np.asarray(d["Y"], dtype=float)
            out[rid] = {
                "T": [float(v) for v in d["T"]],
                "P": [float(v) for v in d["P"]],
                "X": {
                    sp: [float(xmat[i, j]) for i in range(xmat.shape[0])]
                    for j, sp in enumerate(names)
                },
                "Y": {
                    sp: [float(ymat[i, j]) for i in range(ymat.shape[0])]
                    for j, sp in enumerate(names)
                },
                "t": [float(v) for v in d["t"]],
                "is_residence": True,
            }
        return out


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

    from .download_script_emitter import CanteraScriptEmitter as _CanteraScriptEmitter

    SCRIPT_EMITTER_CLASS: type = _CanteraScriptEmitter

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
            from .ctutils import create_solution_from_spec, parse_mechanism_spec

            mech_path, mech_phase = parse_mechanism_spec(self.mechanism)
            resolved_mechanism = self.resolve_mechanism(mech_path)
            cache_key = (
                f"{resolved_mechanism}#{mech_phase}"
                if mech_phase
                else resolved_mechanism
            )
            spec = (
                f"{resolved_mechanism}#{mech_phase}"
                if mech_phase
                else resolved_mechanism
            )
            self.gas = create_solution_from_spec(spec, resolver=lambda path: path)
        except Exception as e:
            raise ValueError(f"Failed to load mechanism '{self.mechanism}': {e}")
        # Cache of mechanisms -> Solution to support per-node overrides
        self._gases_by_mech: Dict[str, ct.Solution] = {cache_key: self.gas}
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
        # Pre-sync normalised config snapshot used to emit the --download script.
        # It must be captured BEFORE _sync_streams_into_config mutates nodes/
        # connections, otherwise build_stage_graph in the generated file would
        # rebuild a different plan than the live solve.
        self._download_config: Optional[Dict[str, Any]] = None
        # Path to config file for --download script (set by CLI in headless mode)
        self._download_config_path: Optional[str] = None
        # Flow-conservation tracking: populated during connection building
        self._unresolved_mfc_ids: Set[str] = set()
        self._mfc_topology: Dict[str, Tuple[str, str]] = {}  # conn_id -> (src, tgt)
        self._mfc_flow_rates: Dict[str, float] = {}  # known flow rates (kg/s)
        # Persistent record of MFCs that had no explicit mass_flow_rate in the
        # YAML. Used by build_viz_network to re-attempt conservation resolution
        # for MFCs prematurely resolved to 0 during a partial-topology stage pass.
        self._originally_unspecified_mfc_ids: Set[str] = set()
        # PressureControllers deferred during stage builds because their master
        # MFC was a logical inter-stage connection not yet registered.  These
        # are built in build_viz_network once the full topology is available.
        self._deferred_pc_conn_dicts: List[Dict[str, Any]] = []
        # Phase-B schedule callbacks: each entry is a callable
        # ``(network, t_start, t_end)`` fired before every micro_step chunk.
        self._schedule_callbacks: List[Callable] = []

    def parse_composition(self, comp_str: str) -> Dict[str, float]:
        """Parse a ``"species:value,species:value,..."`` composition string.

        A handful of real mechanisms (e.g. ``n-heptane-NUIG-2016.yaml``) have
        species names that themselves contain a literal comma (``C6H101-3,3``),
        so naively splitting on every ``,`` before every ``:`` misparses them.
        Values are always plain floats, so a fragment is only a complete entry
        once the text after its last ``:`` parses as one; until then the next
        comma-separated fragment is folded into the same (comma-bearing) name.
        """
        comp_dict: Dict[str, float] = {}
        buf: Optional[str] = None
        for fragment in comp_str.split(","):
            buf = fragment if buf is None else f"{buf},{fragment}"
            if ":" not in buf:
                continue
            name, _, value = buf.rpartition(":")
            try:
                comp_dict[name.strip()] = float(value.strip())
            except ValueError:
                continue  # value isn't numeric yet; more of the name follows
            buf = None
        if buf is not None:
            raise ValueError(f"Malformed composition string: {comp_str!r}")
        return comp_dict

    # ------------------------------------------------------------------
    # Phase-B schedule helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_func1_from_spec(spec: Any) -> "ct.Func1":
        """Convert a STONE schedule spec to a :class:`~cantera.Func1`.

        Supported forms
        ---------------
        Scalar float/int:
            ``mass_flow_rate: 0.1`` → constant Func1.
        Mapping with ``func:`` key (Cantera named functions):
            ``{func: sin, args: [1.0, 100.0, 0.0]}`` →
            ``ct.Func1('sin', 1.0) * ... `` – passed to ``ct.Func1(name, *args)``.
        Mapping with ``profile:`` key (piecewise linear interpolation):
            ``{profile: piecewise_linear, points: [[t0, v0], [t1, v1], ...]}`` →
            ``ct.Func1('tabulated-linear', times, values)``.
        Mapping with ``tabulated:`` key (same as profile piecewise_linear):
            ``{tabulated: [[t0, v0], [t1, v1], ...]}`` →
            ``ct.Func1('tabulated-linear', times, values)``.

        Parameters
        ----------
        spec:
            Raw value from the STONE property (float, int, or dict).

        Returns
        -------
        ct.Func1
            A Cantera Func1 object ready to assign to an MFC or device.
        """
        if isinstance(spec, (int, float)):
            return ct.Func1(float(spec))
        if not isinstance(spec, dict):
            raise ValueError(
                f"Unsupported schedule spec type {type(spec).__name__!r}. "
                "Expected a scalar, {func:, args:} or {profile:, points:} mapping."
            )
        if "func" in spec:
            func_name = str(spec["func"])
            args = spec.get("args", [])
            if not isinstance(args, (list, tuple)):
                args = [args]
            # Cantera's Func1 constructor wants a single list argument for
            # multi-coefficient kinds (e.g. Gaussian: [peak, center, fwhm]) --
            # unpacking into separate positional args raises "Invalid arguments".
            return ct.Func1(func_name, [float(a) for a in args])
        if "profile" in spec or "tabulated" in spec:
            pts_key = "points" if "points" in spec else "tabulated"
            points = spec[pts_key] if pts_key in spec else spec.get("profile")
            if not isinstance(points, list):
                raise ValueError(
                    "schedule profile/tabulated spec requires a 'points:' list of [t, v] pairs."
                )
            times = np.array([float(p[0]) for p in points])
            values = np.array([float(p[1]) for p in points])
            return ct.Func1("tabulated-linear", times, values)
        raise ValueError(
            f"Unrecognised schedule spec keys: {sorted(spec.keys())}. "
            "Expected 'func' or 'profile'/'tabulated'."
        )

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
        """Return the staged-solve script block for generated download scripts.

        When a normalised config snapshot is available (``_download_config`` or
        ``_last_config``), the Cantera-level emitter recomputes the stage plan
        from that embedded config snapshot and delegates to
        ``self.SCRIPT_EMITTER_CLASS`` — producing a fully self-contained
        Cantera-native script with no runner dependency.

        When no config snapshot is available, falls back to a runner-based
        script that re-loads the YAML at runtime.

        Parameters
        ----------
        config_path :
            Path to the original YAML file. Used only as a fallback when no
            normalised config is available on the converter.
        plan :
            :class:`~boulder.staged_solver.StageExecutionPlan` produced by
            ``build_stage_graph()``. Passed through to the runner-based fallback;
            the Cantera-level emitter recomputes its own plan from the config
            snapshot and does not use this argument.
        """
        cfg = self._download_config or self._last_config
        if cfg is not None:
            return self._script_lines_for_cantera(
                "from boulder.cantera_converter import DualCanteraConverter",
                "DualCanteraConverter",
                cfg,
            )
        return self._script_lines_for_runner(
            "from boulder.runner import BoulderRunner",
            "BoulderRunner",
            config_path,
            plan,
        )

    @staticmethod
    def _script_lines_for_runner(
        runner_import: str,
        runner_class: str,
        config_path: str,
        plan: Any,
        continuation: Any = None,
        signals_block: Any = None,
        bindings_block: Any = None,
    ) -> list:
        """Thin wrapper kept for backward compatibility with callers using this as an instance method.

        Delegates entirely to :func:`boulder.download_script_emitter.script_lines_for_runner`.
        """
        from .download_script_emitter import script_lines_for_runner

        return script_lines_for_runner(
            runner_import,
            runner_class,
            config_path,
            plan,
            continuation,
            signals_block,
            bindings_block,
        )

    def _script_lines_for_cantera(
        self,
        converter_import: str,
        converter_class: str,
        config: Dict[str, Any],
    ) -> list:
        """Emit a Cantera-native download script.

        Generates module-level ``reactors`` / ``connections`` / ``walls``
        registries and direct ``ct.*`` construction per stage — see
        :mod:`boulder.download_script_emitter`.

        Dispatch is virtual: subclasses override ``SCRIPT_EMITTER_CLASS`` to inject
        a custom emitter without modifying Boulder.
        The ``converter_import`` and ``converter_class`` parameters are kept for
        backward compatibility with existing callers but are ignored.
        """
        return self.SCRIPT_EMITTER_CLASS(converter=self).emit(config)

    def _get_gas_for_mech(self, mech_name: str) -> ct.Solution:
        """Return (creating and caching if needed) a :class:`~cantera.Solution`.

        Uses ``resolve_mechanism`` so subclass overrides are honored for both
        the top-level mechanism and per-node mechanism switches.

        Mechanism names may include an optional phase suffix after ``#``, e.g.
        ``nDodecane_Reitz.yaml#nDodecane_IG``.
        """
        from .ctutils import create_solution_from_spec, parse_mechanism_spec

        resolved = self.resolve_mechanism(mech_name)
        if resolved in self._gases_by_mech:
            return self._gases_by_mech[resolved]
        mech_path, phase = parse_mechanism_spec(resolved)
        mech_path = self.resolve_mechanism(mech_path)
        cache_key = f"{mech_path}#{phase}" if phase else mech_path
        if cache_key in self._gases_by_mech:
            return self._gases_by_mech[cache_key]
        gas_obj = create_solution_from_spec(
            f"{mech_path}#{phase}" if phase else mech_path,
            resolver=lambda path: path,
        )
        self._gases_by_mech[cache_key] = gas_obj
        return gas_obj

    def _upstream_reservoir_tpy(
        self,
        stage_connections: List[Dict[str, Any]],
        target_id: str,
    ) -> Optional[Tuple[float, float, np.ndarray]]:
        """Return ``(T, P, Y)`` from a Reservoir that feeds *target_id* via an MFC.

        When a reactor omits ``temperature`` / ``composition`` in YAML but is
        connected from an upstream boundary reservoir (built earlier in the
        same stage), inherit its thermochemical state instead of defaulting to
        300 K — required for shared-phase reactors (e.g. ``clone=False``).
        """
        for conn in stage_connections:
            if conn.get("type") != "MassFlowController":
                continue
            if conn.get("target") != target_id:
                continue
            src_id = conn.get("source")
            if not src_id or src_id not in self.reactors:
                continue
            src_r = self.reactors[src_id]
            if not isinstance(src_r, ct.Reservoir):
                continue
            sol = src_r.phase
            return float(sol.T), float(sol.P), sol.Y.copy()
        return None

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

        # STONE v2: clone: and energy: may be specified per-node.
        # Default clone=True preserves existing behaviour; set clone=False only
        # when a shared Solution instance is needed (e.g. micro_step plasma runs).
        clone = bool(props.get("clone", True))

        if typ in self.plugins.reactor_builders:
            reactor = self.plugins.reactor_builders[typ](self, node)
            reactor.name = rid
            validate_energy_on_built_reactor(reactor, props, typ)
        elif typ == "IdealGasReactor":
            reactor = build_reactor_with_energy(
                ct.IdealGasReactor,
                gas_for_node,
                props=props,
                clone=clone,
                type_name=typ,
            )
            reactor.name = rid
        elif typ == "ConstPressureReactor":
            reactor = build_reactor_with_energy(
                ct.ConstPressureReactor,
                gas_for_node,
                props=props,
                clone=clone,
                type_name=typ,
            )
            reactor.name = rid
        elif typ == "IdealGasConstPressureReactor":
            reactor = build_reactor_with_energy(
                ct.IdealGasConstPressureReactor,
                gas_for_node,
                props=props,
                clone=clone,
                type_name=typ,
            )
            reactor.name = rid
        elif typ == "IdealGasConstPressureMoleReactor":
            reactor = build_reactor_with_energy(
                ct.IdealGasConstPressureMoleReactor,
                gas_for_node,
                props=props,
                clone=clone,
                type_name=typ,
            )
            reactor.name = rid
        elif typ == "IdealGasMoleReactor":
            reactor = build_reactor_with_energy(
                ct.IdealGasMoleReactor,  # type: ignore[arg-type]
                gas_for_node,
                props=props,
                clone=clone,
                type_name=typ,
            )
            reactor.name = rid
        elif typ == "Reservoir":
            validate_explicit_energy(props, ct.Reservoir, typ)
            reactor = ct.Reservoir(gas_for_node, clone=clone)  # type: ignore[assignment]
            reactor.name = rid
        elif typ == "OutletSink":
            # DEPRECATED: OutletSink is legacy single-stage diagram syntax.
            # Prefer inter-stage stream-point diamonds (``{source}_outlet`` Reservoirs
            # populated by :func:`boulder.staged_solver._update_stream_point`).
            # Remove this branch when OutletSink is dropped from STONE v2.
            validate_explicit_energy(props, ct.Reservoir, typ)
            reactor = ct.Reservoir(gas_for_node, clone=clone)  # type: ignore[assignment]
            reactor.name = rid
        else:
            raise ValueError(f"Unsupported reactor type: '{typ}'")

        self.set_reactor_volume(reactor, props, rid)
        try:
            reactor.group_name = str(props.get("group", props.get("group_name", "")))
        except Exception:
            pass

        # Phase-B: handle node-level schedule: for reduced_electric_field (plasma reactors)
        # The schedule fires each micro_step chunk to update the field on the Phase object.
        schedule_spec = props.get("schedule")
        if schedule_spec is not None and isinstance(schedule_spec, dict):
            ref_field_spec = schedule_spec.get("reduced_electric_field")
            if ref_field_spec is not None:
                # Build a Func1 representing E/N(t) and register it as a callback.
                ref_func = self._build_func1_from_spec(ref_field_spec)
                # reactor.phase (not gas_for_node) is whichever Solution the
                # reactor actually integrates -- gas_for_node is only correct
                # when clone=False; with the (now default) clone=True, the
                # reactor gets an independent copy, and mutating gas_for_node
                # would silently update a phase object nothing reads from.
                phase = reactor.phase

                def _ref_callback(net, t0, t1, _phase=phase, _f=ref_func):
                    t_mid = (t0 + t1) / 2.0
                    try:
                        _phase.reduced_electric_field = _f(t_mid)
                        if hasattr(_phase, "update_electron_energy_distribution"):
                            _phase.update_electron_energy_distribution()
                    except Exception as exc:
                        logger.debug("reduced_electric_field callback error: %s", exc)

                self._schedule_callbacks.append(_ref_callback)

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
            mfr_spec = props.get("mass_flow_rate")
            if mfr_spec is None and props.get("closure"):
                mfr_spec = props
            if mfr_spec is not None:
                if isinstance(mfr_spec, dict):
                    if "closure" in mfr_spec:
                        closure_kind = str(mfr_spec["closure"])
                        if closure_kind == "residence_time":
                            reactor_id = mfr_spec.get("reactor", tgt)
                            tau_s = float(mfr_spec.get("tau_s", 1.0))

                            # Build a callable that queries reactor.mass at integration time
                            def _mdot_closure(t, _rid=reactor_id, _tau=tau_s):
                                r = self.reactors.get(_rid)
                                if r is None:
                                    return 0.0
                                try:
                                    return r.mass / _tau
                                except Exception:
                                    return 0.0

                            mfc.mass_flow_rate = ct.Func1(_mdot_closure)  # type: ignore[misc]
                        else:
                            raise ValueError(
                                f"MassFlowController '{cid}': unsupported mass_flow_rate "
                                f"closure '{closure_kind}'. Only 'residence_time' is supported."
                            )
                    else:
                        # Schedule spec: { func: gaussian, args: [...] } or piecewise_linear
                        func1 = self._build_func1_from_spec(mfr_spec)
                        mfc.mass_flow_rate = func1  # type: ignore[misc]
                else:
                    mfr = float(mfr_spec)
                    mfc.mass_flow_rate = mfr  # type: ignore[misc]
                    self._mfc_flow_rates[cid] = mfr
            else:
                mfc.mass_flow_rate = 0.0  # type: ignore[misc]  # resolved by conservation
                self._unresolved_mfc_ids.add(cid)
                self._originally_unspecified_mfc_ids.add(cid)
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
            # expansion_rate_coeff (K) makes this a moving piston wall: Cantera
            # moves it at K*(P_left - P_right) every step, transferring volume
            # between the two reactors -- native Wall/Reactor ODE physics that
            # only needs K passed through, not computed here. Independent of
            # (and combinable with) heat_transfer_coeff/electric_power_kW below.
            expansion_rate_coeff = (
                float(props["expansion_rate_coeff"])
                if "expansion_rate_coeff" in props
                else None
            )
            if "heat_transfer_coeff" in props:
                # Passive heat-conduction wall: Q = U*A*(T_left - T_right),
                # recomputed every step from the two reactors' live temperatures
                # (unlike electric_power_kW below, which is a fixed Q).
                area = float(props.get("area", 1.0))
                wall_kwargs: Dict[str, Any] = {
                    "A": area,
                    "U": float(props["heat_transfer_coeff"]),
                    "name": cid,
                }
                if expansion_rate_coeff is not None:
                    wall_kwargs["K"] = expansion_rate_coeff
                wall = ct.Wall(
                    self.reactors[src],
                    self.reactors[tgt],
                    **wall_kwargs,  # type: ignore[arg-type]
                )
            elif "electric_power_kW" in props:
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
                # Still honours a standalone expansion_rate_coeff (a purely
                # mechanical piston with no heat exchange).
                area = float(props.get("area", 1.0))
                wall_kwargs = {"A": area, "name": cid}
                if expansion_rate_coeff is not None:
                    wall_kwargs["K"] = expansion_rate_coeff
                wall = ct.Wall(
                    self.reactors[src],
                    self.reactors[tgt],
                    **wall_kwargs,  # type: ignore[arg-type]
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

    def build_isolated_reactor(
        self, node: Dict[str, Any]
    ) -> Tuple["ct.Reactor", "ct.Solution"]:
        """Build a single reactor from one node, with no surrounding network.

        Resolves the node's mechanism, sets the gas state from its initial
        properties (``temperature`` / ``pressure`` / ``composition`` /
        ``mass_composition``, either top-level or under ``initial:``), and
        delegates to :meth:`create_reactor_from_node` so that ``energy``,
        ``clone``, ``volume`` and any other recognised properties are honoured
        exactly as in a full network build.  This is the single source of truth
        for reactor construction for callers (e.g. parametric τ-sweeps) that
        drive their own :class:`~cantera.ReactorNet` instead of the staged
        solver.

        Property values may be unit strings (``"1273.15 K"``, ``"1 bar"``) or
        plain numbers; temperature/pressure are coerced to SI.

        Parameters
        ----------
        node :
            A node dict with ``id``, ``type``, and ``properties`` (the
            normalised form; STONE ``Kind: {...}`` blocks must be converted to
            ``type`` / ``properties`` by the caller first).

        Returns
        -------
        (reactor, gas)
            The constructed reactor and the :class:`~cantera.Solution` carrying
            its initial state.
        """
        from .utils import coerce_unit_string  # noqa: PLC0415

        rid = node.get("id", "reactor")
        props = node.get("properties") or {}
        node_mech = str(
            props.get("mechanism") or node.get("mechanism") or self.mechanism
        )
        gas = self._get_gas_for_mech(node_mech)

        initial = props.get("initial") or {}
        temp = initial.get("temperature", props.get("temperature"))
        pres = initial.get("pressure", props.get("pressure"))
        compo = initial.get("composition", props.get("composition"))
        mass_compo = initial.get("mass_composition", props.get("mass_composition"))

        t_use = (
            float(coerce_unit_string(temp, "temperature"))
            if temp is not None
            else float(gas.T)
        )
        p_use = (
            float(coerce_unit_string(pres, "pressure"))
            if pres is not None
            else float(gas.P)
        )
        if compo is not None:
            gas.TPX = (t_use, p_use, self.parse_composition(compo))
        elif mass_compo is not None:
            gas.TPY = (t_use, p_use, self.parse_composition(mass_compo))
        else:
            gas.TPX = (t_use, p_use, gas.X)

        self.gas = gas
        self.reactor_meta[rid] = {"mechanism": node_mech, "gas_solution": gas}
        reactor = self.create_reactor_from_node(node, gas)
        self.reactors[rid] = reactor
        return reactor, gas

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
        pre_solve_hook: Optional[Callable[["DualCanteraConverter"], None]] = None,
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
        pre_solve_hook :
            Optional callback invoked with ``self`` after ``self.reactors``/
            ``self.connections`` are populated for this stage but *before*
            the solve dispatch runs. This is the only correct place to wire
            causal-layer bindings (e.g. ``apply_bindings_block``) — calling
            them after this method returns means the solve already ran to
            completion with no schedule callbacks registered.

        Returns
        -------
        (network, stage_reactors)
            ``network`` is the solved :class:`~cantera.ReactorNet`.
            ``stage_reactors`` is a ``{node_id: ct.ReactorBase}`` dict for
            this stage (a subset of ``self.reactors``).
        """
        stage_nodes = _order_stage_nodes_for_flow(stage_nodes, stage_connections)
        stage_reactor_ids: List[str] = []

        for node in stage_nodes:
            rid = node["id"]
            props = node.get("properties") or {}

            # Stream-point reservoirs are created once (in the upstream stage that first
            # encounters them).  If already present in self.reactors, skip creation
            # and go straight to registering the stage_reactor_ids entry.
            if rid in self.reactors and (
                props.get("stream_point") or props.get("stage_interface")
            ):
                stage_reactor_ids.append(rid)
                continue

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
                # STONE v2: reactor state may live under props["initial"] for
                # non-Reservoir nodes; fall back to props directly for Reservoir
                # boundary nodes and legacy internal format.
                initial = props.get("initial") or {}
                temp = initial.get("temperature") or props.get("temperature")
                pres = initial.get("pressure") or props.get("pressure")
                compo = initial.get("composition") or props.get("composition")
                mass_compo = initial.get("mass_composition") or props.get(
                    "mass_composition"
                )
                # Inherit full (T, P, Y) from an upstream boundary reservoir when
                # temperature and both composition specs are absent.  Pressure alone
                # (e.g. auto-filled 1 atm) must not block inheritance.
                if temp is None and compo is None and mass_compo is None:
                    upstream_tpy = self._upstream_reservoir_tpy(stage_connections, rid)
                    if upstream_tpy is not None:
                        T_u, P_u, Y_u = upstream_tpy
                        gas_for_node.TPY = T_u, P_u, Y_u
                    # else: leave gas_for_node from _get_gas_for_mech; plugin reactors
                    # read the axial feed via _inlet_reservoir (plugin post-build hook).
                else:
                    node_type = node.get("type", "")
                    if node_type == "Reservoir":
                        if temp is None:
                            raise ValueError(
                                f"Reservoir '{rid}': 'temperature' is missing. "
                                "Reservoir nodes require an explicit temperature."
                            )
                        if pres is None:
                            raise ValueError(
                                f"Reservoir '{rid}': 'pressure' is missing. "
                                "Reservoir nodes require an explicit pressure."
                            )
                        if compo is None and mass_compo is None:
                            raise ValueError(
                                f"Reservoir '{rid}': 'composition' or "
                                "'mass_composition' is missing."
                            )
                    t_use = float(temp) if temp is not None else float(gas_for_node.T)
                    p_use = float(pres) if pres is not None else float(gas_for_node.P)
                    if compo is not None:
                        gas_for_node.TPX = (t_use, p_use, self.parse_composition(compo))
                    elif mass_compo is not None:
                        gas_for_node.TPX = (
                            t_use,
                            p_use,
                            self.parse_composition(mass_compo),
                        )
                    else:
                        gas_for_node.TPX = (t_use, p_use, gas_for_node.X)

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

        # Build intra-stage (and stream-MFC) connections.
        # LEGACY WORKAROUND NOTE: _mfc_topology and _mfc_flow_rates are NOT reset
        # between stages so that build_viz_network can run a second conservation pass
        # with the full cross-stage topology visible.  With stream_reservoirs=True
        # the conservation pass is self-contained per stage; this accumulation
        # becomes a no-op and can be removed when the flag is the default.
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
            # Detect PressureControllers whose master MFC has not been
            # registered yet (logical inter-stage MFCs are materialized only
            # in build_viz_network).  Defer these cleanly rather than letting
            # build_connection raise and swallowing the error silently.
            if conn.get("type") == "PressureController":
                master_id = (conn.get("properties") or {}).get("master")
                if master_id and master_id not in self.connections:
                    logger.debug(
                        "Stage '%s': deferring PressureController '%s' — "
                        "master '%s' not yet registered (logical inter-stage MFC).",
                        stage_id,
                        cid,
                        master_id,
                    )
                    self._deferred_pc_conn_dicts.append(conn)
                    continue
            try:
                self.build_connection(conn)
            except ValueError:
                raise
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
        #   0. Stage-level network_class (set on the group config by a composite unfolder) —
        #      takes top precedence and disables per-reactor conflict scan.
        #   1. Per-node YAML ``network_class`` dotted-path override.
        #   2. ``reactor.NETWORK_CLASS`` class attribute set by the plugin.
        #   3. ``ct.ReactorNet`` default.
        #
        # If two reactors in the same stage resolve to different non-default
        # network classes, raise an error (previously the first-wins silent
        # fallback hid a latent misconfiguration).
        stage_net_cls: Optional[str] = (
            stage.network_class if stage is not None else None
        )
        ReactorNetClass, net_kw = _select_network_class_for_stage(
            self, stage_id, stage_nodes, non_res_ids, stage_network_class=stage_net_cls
        )

        rseq = [self.reactors[rid] for rid in non_res_ids]
        network = ReactorNetClass(cast(Sequence[ct.Reactor], rseq), **net_kw)

        # Apply solver tolerances / integrator knobs
        solver = (getattr(stage, "solver", None) or {}) if stage is not None else {}
        network.rtol = float(solver.get("rtol", 1e-6))
        network.atol = float(solver.get("atol", 1e-8))
        if "max_time_step" in solver:
            network.max_time_step = float(solver["max_time_step"])
        if "max_steps" in solver:
            network.max_steps = int(solver["max_steps"])
        if solver.get("initial_time_reset", False):
            try:
                network.initial_time = 0.0
            except AttributeError:
                pass  # custom ReactorNet subclass may not support this

        # Optional sparse preconditioner (opt-in via solver.use_preconditioner).
        # Large-mechanism mole reactors integrated over long, near-inert horizons
        # otherwise collapse into a stiff dense-Jacobian regime where the CVODES
        # step underflows (t + h == t) and the solve stalls.  An
        # AdaptivePreconditioner switches CVODES to a sparse iterative linear
        # solver and makes those solves both fast and stable.  Guarded: reactor
        # kinds that do not support preconditioning fall back to the dense solve.
        if solver.get("use_preconditioner"):
            try:
                network.preconditioner = ct.AdaptivePreconditioner()
            except Exception as exc:  # noqa: BLE001 — never block the solve on this
                logger.warning(
                    "Stage '%s': could not enable AdaptivePreconditioner (%s); "
                    "falling back to the dense solver.",
                    stage_id,
                    exc,
                )

        # Give the caller a chance to wire causal-layer bindings (Phase B:
        # signals -> reduced_electric_field/mass_flow_rate/tau_s) now that
        # self.reactors/self.connections are populated but nothing has been
        # solved yet. A binding applied *after* this method returns (as when
        # this was the caller's own responsibility) is applied after the
        # solve already ran to completion -- e.g. a micro_step plasma pulse
        # would drive the reaction with reduced_electric_field frozen at
        # its initial value the entire time, never actually pulsing.
        if pre_solve_hook is not None:
            pre_solve_hook(self)

        # Dispatch to the right integrator
        kind = str(solver.get("kind", "advance_to_steady_state"))
        if kind == "advance_to_steady_state":
            network.advance_to_steady_state()
        elif kind == "solve_steady":
            network.solve_steady()
        elif kind == "advance":
            from .utils import coerce_unit_string  # noqa: PLC0415

            _at_raw = solver.get("advance_time", getattr(stage, "advance_time", 1.0))
            advance_time = float(coerce_unit_string(_at_raw, "advance_time"))
            network.advance(advance_time)
        elif kind in ("advance_grid", "micro_step"):
            # Phase B: delegated to _run_transient_solver helper
            self._run_transient_solver(network, kind, solver, stage_id)
        else:
            raise ValueError(
                f"Unknown solver.kind '{kind}' for stage '{stage_id}'. "
                "See STONE_SPECIFICATIONS.md for valid values."
            )

        stage_reactors = {rid: self.reactors[rid] for rid in stage_reactor_ids}
        # Remember the most recent solver network: build_viz_network falls back
        # to it on Cantera >= 4, where a reactor cannot join a second ReactorNet.
        self.last_network = network
        return network, stage_reactors

    def _run_transient_solver(
        self,
        network: "ct.ReactorNet",
        kind: str,
        solver: dict,
        stage_id: str,
    ) -> None:
        """Execute transient (advance_grid or micro_step) integration.

        Called by :meth:`build_sub_network` when ``solver.kind`` is one of the
        Phase-B transient kinds.  This method is the authoritative implementation
        of the grid loop and micro-step patterns; see :ref:`phase-b` in
        STONE_SPECIFICATIONS.md.

        Parameters
        ----------
        network:
            The already-constructed :class:`~cantera.ReactorNet`.
        kind:
            ``"advance_grid"`` or ``"micro_step"``.
        solver:
            The fully-resolved solver dict for this stage.
        stage_id:
            Stage identifier for error messages.
        """
        _scope_recorder = getattr(self, "_scope_recorder", None)

        if kind == "advance_grid":
            grid_spec = solver.get("grid")
            if grid_spec is None:
                raise ValueError(
                    f"Stage '{stage_id}': solver.kind='advance_grid' requires a 'grid:' entry."
                )
            if isinstance(grid_spec, dict):
                import numpy as np

                start = float(grid_spec.get("start", 0.0))
                stop = float(grid_spec["stop"])
                dt = float(grid_spec["dt"])
                times = [float(t) for t in np.arange(start + dt, stop + dt / 2, dt)]
            else:
                times = [float(t) for t in grid_spec]
            for t in times:
                network.advance(float(t))
                if _scope_recorder is not None:
                    _scope_recorder.record(float(t))
        elif kind == "micro_step":
            t_total = float(solver["t_total"])
            chunk_dt = float(solver["chunk_dt"])
            max_dt = float(solver.get("max_dt", chunk_dt / 10))
            reinit = bool(solver.get("reinitialize_between_chunks", False))
            t = float(solver.get("start", 0.0))
            while t < t_total:
                t_end = min(t + chunk_dt, t_total)
                # Fire any schedule callbacks before each chunk, then
                # reinitialize *immediately* -- CVODES caches the RHS's
                # external parameters (e.g. a plasma's electron energy
                # distribution) internally and won't notice a callback's
                # mutation until reinitialize() runs. Reinitializing only
                # after the advance loop below (the previous order) meant
                # every chunk's advance() calls integrated with the *stale*
                # field from before this callback, silently freezing out an
                # entire pulse's worth of dynamics.
                self._fire_schedule_callbacks(network, t, t_end, stage_id)
                if reinit:
                    network.reinitialize()
                while network.time < t_end:
                    network.advance(network.time + max_dt)
                if _scope_recorder is not None:
                    _scope_recorder.record(t_end)
                t = t_end
        else:
            raise ValueError(
                f"Stage '{stage_id}': _run_transient_solver called with unknown kind '{kind}'."
            )

    def _fire_schedule_callbacks(
        self,
        network: "ct.ReactorNet",
        t_start: float,
        t_end: float,
        stage_id: str,
    ) -> None:
        """Call any registered schedule callbacks before a micro-step chunk.

        Each callback in ``self._schedule_callbacks`` is invoked with
        ``(network, t_start, t_end)``.  Phase-B wires MFC / plasma-field
        schedules into this list during :meth:`build_sub_network`.
        """
        for cb in getattr(self, "_schedule_callbacks", []):
            cb(network, t_start, t_end)

    def _unique_non_reservoir_reactors(self) -> List[ct.ReactorBase]:
        """Non-reservoir reactors, deduplicated by object identity.

        Plugin post-build hooks (e.g. ``TubeFurnace`` outlet aliases) may
        register the same :class:`~cantera.Reactor` under multiple dict keys.
        A :class:`~cantera.ReactorNet` must list each reactor once.
        """
        seen: set[int] = set()
        unique: List[ct.ReactorBase] = []
        for reactor in self.reactors.values():
            if isinstance(reactor, ct.Reservoir):
                continue
            obj_id = id(reactor)
            if obj_id in seen:
                continue
            seen.add(obj_id)
            unique.append(reactor)
        return unique

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

        # Re-enqueue MFCs resolved to 0 during a partial-topology stage pass.
        # Inter-stage MFCs are materialised during the stage solve itself, so
        # the full topology is already visible and this second pass is a no-op.
        # Kept for safety in case a partial build leaves zero-flow devices.
        for cid in list(self._originally_unspecified_mfc_ids):
            if self._mfc_flow_rates.get(cid, -1.0) == 0.0:
                self._unresolved_mfc_ids.add(cid)
                self._mfc_flow_rates.pop(cid, None)

        # Build PressureControllers deferred during stage builds because their
        # master MFC was a virtual inter-stage connection not yet registered.
        # All inter-stage MFCs are real and exist from stage-solve time.
        for conn in self._deferred_pc_conn_dicts:
            cid = conn["id"]
            if cid in self.connections:
                continue  # already built via all_connections loop
            src = conn["source"]
            tgt = conn["target"]
            if src not in self.reactors or tgt not in self.reactors:
                logger.warning(
                    "Viz network: cannot build deferred PC '%s' — reactor not found.",
                    cid,
                )
                continue
            try:
                self.build_connection(conn)
            except Exception as exc:
                logger.warning(
                    "Viz network: failed to build deferred PressureController '%s': %s",
                    cid,
                    exc,
                )

        # Resolve any MFC mass flow rates that were still pending once all
        # inter-stage devices are in place.  Until now intra-stage passes only
        # saw a sub-topology; mixers on stage boundaries or
        # inter-stage MFCs without explicit mass_flow_rate would otherwise
        # stay at 0 kg/s and make Sankey bands collapse.
        self.apply_flow_conservation()

        non_res = self._unique_non_reservoir_reactors()
        try:
            viz_net = ct.ReactorNet(cast(Sequence[ct.Reactor], non_res))
            viz_net.advance(0.0)
        except ct.CanteraError:
            # Cantera >= 4 forbids adding a reactor to a second ReactorNet (the
            # per-stage solver network still owns it).  Reuse the most recent
            # stage network for visualization instead of rebuilding one; for
            # multi-stage configs only the last stage is then drawn.
            if self.last_network is None:
                raise
            logger.info(
                "Viz network: reactors already belong to a stage ReactorNet "
                "(Cantera >= 4); reusing the last stage network."
            )
            viz_net = self.last_network
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
        import copy

        if not config.get("groups"):
            raise ValueError(
                "build_network requires a config with a 'groups' section. "
                "Call normalize_config() first — it synthesises a single "
                "'default' group when the YAML has none."
            )

        # Work on a deep copy so the caller's config dict is never mutated.
        # _sync_streams_into_config (called inside solve_staged) replaces inter-stage
        # connection dicts in-place; without the copy, module-level test fixtures and
        # any caller that re-uses a config object would see a corrupted topology.
        config = copy.deepcopy(config)
        self._last_config = config
        # Snapshot the pre-sync config for the --download script before
        # solve_staged mutates `config` via _sync_streams_into_config.
        self._download_config = copy.deepcopy(config)

        from .staged_solver import build_stage_graph, solve_staged

        # Transient solve with no declared checkpoints: inject a default linspace
        # grid so the recorder still yields a trajectory ("do whatever" when no
        # required grid is given). Required checkpoints, when present, are left
        # untouched and advanced through exactly. Config-prep only — not a solver
        # change.
        _settings = config.get("settings") or {}
        _default_end = float(_settings.get("end_time") or 1.0)
        for _group in (config.get("groups") or {}).values():
            _solver = _group.get("solver") or {}
            if _solver.get("kind") == "advance_grid" and not _solver.get("grid"):
                _solver["grid"] = {
                    "start": 0.0,
                    "stop": _default_end,
                    "dt": _default_end / 50.0,
                }
                _group["solver"] = _solver

        # Install a full-state trajectory recorder so a transient (advance_grid)
        # solve also yields the per-step T(t) — captured during the *single*
        # staged solve via the existing record() hook, never a re-integration.
        # Skip if a real scopes recorder is already installed (don't clobber it).
        self._trajectory_recorder = None
        if getattr(self, "_scope_recorder", None) is None:
            self._scope_recorder = _TrajectoryRecorder(self)
            self._trajectory_recorder = self._scope_recorder

        plan = build_stage_graph(config)
        trajectory = solve_staged(
            self,
            plan,
            config,
            progress_callback=progress_callback,
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

        # Determine whether any stage used a transient solver kind.
        _has_transient_stage = False
        _last_cfg = getattr(self, "_last_config", None)
        if _last_cfg:
            for _gcfg in (_last_cfg.get("groups") or {}).values():
                _solver_blk = _gcfg.get("solver") or {}
                if (
                    _solver_blk.get("kind", "advance_to_steady_state")
                    in TRANSIENT_SOLVER_KINDS
                ):
                    _has_transient_stage = True
                    break

        self.code_lines.append("")
        self.code_lines.append("# ===== SIMULATION EXECUTION =====")
        if already_solved:
            if _has_transient_stage:
                self.code_lines.append(
                    "# solve_stage() ran transient integration; network holds the final state."
                )
            else:
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
        reactor_list = self._unique_non_reservoir_reactors()

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
                    cast(
                        List[float], reactors_series[reactor_id]["X"][species_name]
                    ).append(float(x_value))
                for species_name, y_value in zip(reactor_species_names, Y_vec):
                    cast(
                        List[float], reactors_series[reactor_id]["Y"][species_name]
                    ).append(float(y_value))

                # Spatial reactors: if the plugin registered a spatial_series_fn
                # on reactor_meta, call it to replace the single-point snapshot
                # with the full converged spatial profile.
                _spatial_fn = self.reactor_meta.get(reactor_id, {}).get(
                    "spatial_series_fn"
                )
                _series: Optional[Dict[str, Any]] = None
                if _spatial_fn is not None:
                    _series = _spatial_fn()
                if _series is None:
                    _series = try_infer_spatial_reactor_series(self, reactor_id)
                if _series is not None:
                    reactors_series[reactor_id] = _series
                    # If this reactor is the representative of a composite group
                    # (e.g. CGR placeholder), also register under the group/stage
                    # id so clicking the compound box shows the full profile.
                    _group_series_id = self.reactor_meta.get(reactor_id, {}).get(
                        "group_series_id"
                    )
                    if _group_series_id:
                        reactors_series[_group_series_id] = _series

                # PSR reactors: if the plugin flagged this reactor as a PSR,
                # propagate the flag so the frontend can adapt its visualisation.
                elif self.reactor_meta.get(reactor_id, {}).get("is_psr"):
                    reactors_series[reactor_id]["is_psr"] = True

            # Transient solve: replace the converged single-point snapshot with the
            # T(t) trajectory captured *during* the (single) staged solve by the
            # recorder. No re-integration; reports/Sankey/code from finalize are
            # kept; only the series is swapped. Spatial profiles are left untouched.
            _recorder = getattr(self, "_trajectory_recorder", None)
            _traj = _recorder.series() if _recorder is not None else {}
            for _rid, _series in _traj.items():
                if _rid in reactors_series and not reactors_series[_rid].get(
                    "is_spatial"
                ):
                    reactors_series[_rid] = _series
                    times[:] = _series["t"]

            # CustomStageNetwork trajectory: a stage network that integrates its
            # whole stage internally (one ``advance`` call over its own grid)
            # records the real profile in ``.states`` — the per-step recorder
            # above cannot capture it. Surface it as the reactor series so the
            # built-in plots and plugin panes show the full trajectory.
            _staged = getattr(self, "_staged_trajectory", None)
            for _net in getattr(_staged, "networks", {}).values() if _staged else ():
                _net_states = getattr(_net, "states", None)
                _flat = _series_from_stage_states(
                    _net_states, getattr(_net, "scalars", None)
                )
                if _flat is None:
                    continue
                _states_species = list(getattr(_net_states, "species_names", []))
                for _r in getattr(_net, "reactors", []):
                    if isinstance(_r, ct.Reservoir):
                        continue
                    # The stage records ONE profile: attach it only to the
                    # reactor(s) whose phase it describes (matched by species
                    # set), never to co-staged reactors on other mechanisms.
                    _r_species = list(
                        getattr(getattr(_r, "phase", None), "species_names", [])
                    )
                    if _states_species and _r_species != _states_species:
                        continue
                    _rid = getattr(_r, "name", "") or str(id(_r))
                    _existing = reactors_series.get(_rid)
                    if _existing is not None and _existing.get("is_spatial"):
                        continue
                    _cur_len = len((_existing or {}).get("t", []) or [])
                    if len(_flat["t"]) > _cur_len:
                        reactors_series[_rid] = _flat
                        if len(_flat["t"]) > len(times):
                            times[:] = _flat["t"]

            if progress_callback:
                progress_callback(
                    {
                        "time": times.copy(),
                        "reactors": reactors_series,
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
                    raise RuntimeError(
                        "Cantera integration failed before any successful time step "
                        f"at t={current_time}s: {last_error_message}. "
                        "Refusing to fabricate reactor state trajectories."
                    ) from e
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
                        X_vec = np.array(X_vec_list)
                        Y_vec_list = [
                            reactors_series[reactor_id]["Y"][s][-1]
                            for s in reactor_species_names
                        ]
                        Y_vec = np.array(Y_vec_list)
                    else:
                        raise ValueError(
                            f"Reactor {reactor_id!r}: non-finite thermochemical state "
                            f"(T/P/X/Y) at t={current_time}s and no prior trajectory "
                            "samples to reuse."
                        )

                sol_arrays[reactor_id].append(T=T, P=P, X=X_vec)
                reactors_series[reactor_id]["T"].append(T)
                reactors_series[reactor_id]["P"].append(P)
                for species_name, x_value in zip(reactor_species_names, X_vec):
                    cast(
                        List[float], reactors_series[reactor_id]["X"][species_name]
                    ).append(float(x_value))
                for species_name, y_value in zip(reactor_species_names, Y_vec):
                    cast(
                        List[float], reactors_series[reactor_id]["Y"][species_name]
                    ).append(float(y_value))

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
        # Apply spatial_series_fn overrides and group_series_id aliases.
        # These may not have been applied yet when called from the streaming
        # simulation path.
        for reactor_id in list(reactors_series.keys()):
            _meta = self.reactor_meta.get(reactor_id, {})
            _spatial_fn = _meta.get("spatial_series_fn")
            if _spatial_fn is not None:
                try:
                    _series = _spatial_fn()
                    if _series is not None:
                        reactors_series[reactor_id] = _series
                        _group_series_id = _meta.get("group_series_id")
                        if _group_series_id:
                            reactors_series[_group_series_id] = _series
                except Exception:
                    pass

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
                    mechanism=self.mechanism,
                    if_no_species="ignore",
                )

            logger.info(
                f"Sankey generation result: links={type(links)}, nodes={type(nodes)}"
            )
            if links:
                logger.info(f"Links has {len(links.get('source', []))} connections")
            if nodes:
                logger.info(f"Nodes has {len(nodes)} entries")

            results["sankey_links"] = sankey_links_for_api(links, plugins=self.plugins)
            results["sankey_nodes"] = nodes
        except Exception as e:
            logger.error(f"Error generating Sankey diagram: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            results["sankey_links"] = None
            results["sankey_nodes"] = None
            # Sankey is optional post-processing; do not fail an otherwise successful solve.

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
