"""BoulderRunner — orchestrator for the YAML → network → result pipeline.

Provides a single class that subclasses can override to inject custom
converters (e.g. ``MyRunner`` with ``MyConverter``).  The Boulder CLI uses
the base class; other entrypoints may pass ``runner_class=MyRunner``.
"""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional, Type, Union

if TYPE_CHECKING:
    import cantera as ct

    from boulder.cantera_converter import BoulderPlugins, DualCanteraConverter
    from boulder.lagrangian import LagrangianTrajectory
    from boulder.simulation_result import SimulationResult
    from boulder.staged_network import StagedReactorNet
    from boulder.staged_solver import Stage, StageExecutionPlan

logger = logging.getLogger(__name__)


class BoulderRunner:
    """Orchestrates the full YAML-to-SimulationResult pipeline.

    Subclass and set ``converter_class`` to swap the converter without
    touching any other code.  All public attributes are documented; no private
    underscore fields are accessed by callers.

    Parameters
    ----------
    config :
        Normalised (and validated) config dict.
    plugins :
        Optional pre-built plugin container.  When ``None`` the converter
        will discover plugins via entry-points.
    config_path :
        Original path of the YAML file; propagated to the converter so the
        downloadable script references the correct file.
    """

    converter_class: Type["DualCanteraConverter"] = None  # type: ignore[assignment]
    #: The raw config :meth:`from_yaml` loaded; the download script embeds it.
    _raw_config: Optional[Dict[str, Any]] = None

    def __init__(
        self,
        config: Dict[str, Any],
        *,
        plugins: Optional["BoulderPlugins"] = None,
        config_path: Optional[str] = None,
    ) -> None:
        self.config = config
        self.config_path = config_path
        self.plugins = plugins
        self.converter: Optional["DualCanteraConverter"] = None
        self.network: Optional[Union["StagedReactorNet", "ct.ReactorNet"]] = None
        self.results: Optional[Dict[str, Any]] = None
        self.code: Optional[str] = None
        self.result: Optional["SimulationResult"] = None
        self._scope_recorder: Optional[Any] = None
        self._stream_cache: Optional[Any] = None  # (plan, node_dicts, conns_by_stage)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "converter_class" not in cls.__dict__:
            # Inherit from parent; no default assignment needed.
            pass

    # ------------------------------------------------------------------
    # Causal-layer public surface (Phase C / Phase E FMU prep)
    # ------------------------------------------------------------------

    @property
    def scopes(self) -> "Dict[str, Any]":
        """Return scope data as a ``dict[str, pandas.DataFrame]``.

        Each key is a scope variable path (e.g. ``nodes.r1.T``); each value
        is a DataFrame with columns ``t`` (seconds) and ``value``.

        Returns an empty dict if no scopes were declared or if
        :meth:`build` has not been called yet.
        """
        if self._scope_recorder is None:
            return {}
        return self._scope_recorder.to_dataframes()

    @property
    def exposed_inputs(self) -> "Dict[str, Any]":
        """Return signals that are not bound to any internal network target.

        These are the FMI-friendly *input variables* — signals that a co-
        simulation master (FMU) could override at each ``doStep``.

        A signal is considered *exposed* (unbound) if its ``id`` does not
        appear as a ``source`` in any entry of the ``bindings:`` block.

        Returns a ``dict[signal_id, signal_spec]`` where each value is the
        raw spec dict from the ``signals:`` block.  Returns an empty dict if no
        signals are declared.

        .. note::
            This is the Phase E FMU data-shape contract.  No FMU code is
            generated here; this property just exposes the data structure that
            :mod:`boulder.fmi` would use.  See ``FMI_FMU_EXPORT.md``.
        """
        cfg = getattr(self, "config", None)
        if cfg is None:
            return {}
        signals_block = cfg.get("signals") or []
        bindings_block = cfg.get("bindings") or []

        # Set of signal IDs that are already wired to internal targets
        bound_ids: set[str] = {
            b.get("source", "") for b in bindings_block if isinstance(b, dict)
        }

        exposed: Dict[str, Any] = {}
        for sig in signals_block:
            if not isinstance(sig, dict):
                continue
            sid = sig.get("id", "")
            if sid and sid not in bound_ids:
                exposed[sid] = sig
        return exposed

    @classmethod
    def from_yaml(cls, path: str) -> "BoulderRunner":
        """Load, normalise, and validate a YAML file, returning a runner instance."""
        raw = cls.load(path)
        cfg = cls.validate(cls.normalize(copy.deepcopy(raw)))
        runner = cls(config=cfg, config_path=path)
        runner._raw_config = raw
        return runner

    @staticmethod
    def load(path: str) -> Dict[str, Any]:
        """Load raw config dict from a YAML file."""
        from .config import load_config_file

        return load_config_file(path)

    @classmethod
    def normalize(cls, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Apply Boulder's structural normalisation to a raw config."""
        from .config import normalize_config

        return normalize_config(cfg)

    @classmethod
    def validate(cls, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a normalised config, raising on schema errors."""
        from .config import validate_config

        return validate_config(cfg)

    def _default_mechanism_name(self) -> str:
        """Return the raw top-level mechanism string (not path-resolved).

        Path resolution happens inside ``DualCanteraConverter.resolve_mechanism``,
        which is called during construction.
        """
        phases = self.config.get("phases") or {}
        gas = phases.get("gas") if isinstance(phases, dict) else {}
        return (gas or {}).get("mechanism") or "gri30.yaml"

    def _ensure_converter(self) -> "DualCanteraConverter":
        """Instantiate ``self.converter`` if not already done."""
        if self.converter is not None:
            return self.converter
        from .cantera_converter import select_converter_class

        converter_cls = select_converter_class(
            self.__class__.converter_class, self.plugins
        )
        c = converter_cls(
            mechanism=self._default_mechanism_name(),
            plugins=self.plugins,
        )
        c.runner_class = type(self)
        c._download_raw = self._raw_config
        if self.config_path is not None:
            c._download_config_path = self.config_path
        self.converter = c
        return c

    # ------------------------------------------------------------------
    # Staged-solve public API (mirrors the live simulation call chain)
    # ------------------------------------------------------------------

    def build_stage_graph(self) -> "StageExecutionPlan":
        """Parse the config into a topologically-sorted :class:`~boulder.staged_solver.StageExecutionPlan`.

        Pure config parsing — no Cantera objects are created.  Stage IDs and
        node lists are available immediately after this call.
        """
        from .staged_solver import build_stage_graph as _bsg

        return _bsg(self.config)

    def new_trajectory(self) -> "LagrangianTrajectory":
        """Return a fresh, empty :class:`~boulder.lagrangian.LagrangianTrajectory`."""
        from .lagrangian import LagrangianTrajectory

        return LagrangianTrajectory()

    def _stream_points(
        self, plan: "StageExecutionPlan"
    ) -> "tuple[Dict[str, Any], Dict[str, Any]]":
        """Return the stream-point dicts of *plan*, the same pair for every call.

        A stage must see the reservoir the stage before it filled, so the dicts
        are built once per plan and kept on the runner.
        """
        cached = self._stream_cache
        if cached is None or cached[0] is not plan:
            from .staged_solver import stream_points_for

            cached = (plan, *stream_points_for(plan))
            self._stream_cache = cached
        return cached[1], cached[2]

    def solve_stage(
        self,
        plan: "StageExecutionPlan",
        stage: "Stage",
        inlet_states: Dict[str, Any],
        trajectory: "LagrangianTrajectory",
        stream_reservoirs: bool = True,
        _stream_node_dicts: Optional[Dict[str, Any]] = None,
        _stream_conns_by_stage: Optional[Dict[str, Any]] = None,
        # Backward-compatible aliases
        interface_reservoirs: Optional[bool] = None,
        _iface_node_dicts: Optional[Dict[str, Any]] = None,
        _iface_conns_by_stage: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build and solve one stage, updating *inlet_states* and *trajectory* in place.

        Returns ``{node_id: reactor}``, the objects the stage built.

        A delegate to :func:`boulder.staged_solver.solve_one_stage`, the one
        per-stage solve every entry point runs (``solve_staged`` is a loop over
        it).  Kept with this signature for the downloaded scripts and
        :meth:`run_continuation`, which step the stages themselves.

        Parameters
        ----------
        plan :
            Full execution plan (needed for mechanism-switch target lookup).
        stage :
            The :class:`~boulder.staged_solver.Stage` to solve.
        inlet_states :
            Mutable ``{node_id: ct.Solution}`` dict.  Populated by upstream
            stages; consumed here to initialise inter-stage-inlet reactors.
            Updated in place with this stage's outlet states.
        trajectory :
            Accumulates per-stage :class:`~cantera.SolutionArray` segments.
        stream_reservoirs :
            When ``True`` (default), use synthesised stream-point reservoirs
            and real MFCs on the downstream side of each stage boundary.
        _stream_node_dicts, _stream_conns_by_stage :
            Stream-point dicts of *plan*; kept on the runner when omitted.
        interface_reservoirs, _iface_node_dicts, _iface_conns_by_stage :
            Deprecated aliases for *stream_reservoirs*, *_stream_node_dicts*
            and *_stream_conns_by_stage*.

        Examples
        --------
        .. minigallery:: boulder.runner.BoulderRunner.solve_stage
           :add-heading: Examples using solve_stage
        """
        if interface_reservoirs is not None and not stream_reservoirs:
            stream_reservoirs = interface_reservoirs
        if _iface_node_dicts is not None and _stream_node_dicts is None:
            _stream_node_dicts = _iface_node_dicts
        if _iface_conns_by_stage is not None and _stream_conns_by_stage is None:
            _stream_conns_by_stage = _iface_conns_by_stage
        if stream_reservoirs and (
            _stream_node_dicts is None or _stream_conns_by_stage is None
        ):
            _stream_node_dicts, _stream_conns_by_stage = self._stream_points(plan)

        from .staged_solver import solve_one_stage

        return solve_one_stage(
            self._ensure_converter(),
            plan,
            stage,
            self.config,
            inlet_states,
            trajectory,
            stream_reservoirs,
            _stream_node_dicts,
            _stream_conns_by_stage,
        )

    def build_viz_network(
        self,
        plan: "StageExecutionPlan",
        trajectory: "LagrangianTrajectory",
        stream_reservoirs: bool = True,
        # Backward-compatible alias
        interface_reservoirs: Optional[bool] = None,
    ) -> None:
        """Assemble the full visualization :class:`~cantera.ReactorNet` from all converged states.

        A delegate to :func:`boulder.staged_solver.build_stage_viz`, the one
        visualization step ``solve_staged`` ends with.  Not solved again: for
        visualization and Sankey generation.  Sets ``self.network`` and
        ``trajectory.viz_network``.

        Parameters
        ----------
        plan :
            Execution plan (provides inter-stage connection list).
        trajectory :
            Updated in place: ``trajectory.viz_network`` is set.
        stream_reservoirs :
            Whether the solve used stream-point reservoirs (default).
        interface_reservoirs :
            Deprecated alias for *stream_reservoirs*.

        Examples
        --------
        .. minigallery:: boulder.runner.BoulderRunner.build_viz_network
           :add-heading: Examples using build_viz_network
        """
        if interface_reservoirs is not None and not stream_reservoirs:
            stream_reservoirs = interface_reservoirs

        from .staged_solver import build_stage_viz

        node_dicts, conns_by_stage = (
            self._stream_points(plan) if stream_reservoirs else (None, None)
        )
        self.network = build_stage_viz(
            self._ensure_converter(),
            plan,
            self.config,
            trajectory,
            stream_reservoirs,
            node_dicts,
            conns_by_stage,
        )

    def run_continuation(
        self,
        continuation: Optional[Dict[str, Any]] = None,
    ) -> "BoulderRunner":
        """Execute a parameter continuation sweep as defined in ``continuation:`` STONE block.

        Wraps :meth:`solve_stage` in an outer loop, mutating the target parameter
        between solves and collecting the trajectory.  Equivalent to the manual
        loop in ``combustor.py``::

            while combustor.T > 500:
                sim.solve_steady()
                inlet.mass_flow_rate *= 0.9

        Parameters
        ----------
        continuation :
            Parsed ``continuation:`` dict from the STONE YAML.  When ``None``
            the method reads ``self.config.get("continuation")``.  Structure::

                parameter: connections.<id>.mass_flow_rate
                update:
                  multiply: 0.9          # or set: <val> or list: [...]
                until:
                  reactor_T_below: 500   # or reactor_T_above: <K>
                  max_iters: 200

        Returns
        -------
        self
            For chaining.  After this call ``self.network`` is the visualization
            network built from the last converged iteration.

        Raises
        ------
        ValueError
            If *continuation* is missing required keys or *parameter* path cannot
            be resolved.
        """
        if continuation is None:
            continuation = self.config.get("continuation") or {}
        if not continuation:
            raise ValueError(
                "run_continuation: no 'continuation:' block found in config or argument."
            )

        parameter_path = continuation.get("parameter")
        if not parameter_path:
            raise ValueError(
                "run_continuation: 'parameter:' is required in the continuation block."
            )

        update_spec = continuation.get("update") or {}
        until_spec = continuation.get("until") or {}
        max_iters = int(until_spec.get("max_iters", 200))
        t_below = until_spec.get("reactor_T_below")
        t_above = until_spec.get("reactor_T_above")

        # The plan comes from the config as given: a prior ``build()`` rewrites
        # the config with its stream points and drops the inter-stage
        # connections, so a plan taken after it would have none.  Every stage
        # is solved in the loop below; no build is needed first.
        from .staged_solver import alias_inter_connection_mfcs

        plan = self.build_stage_graph()
        converter = self._ensure_converter()

        def _properties(path: str) -> "tuple[Dict[str, Any], str]":
            """Return the config ``properties`` dict and attribute *path* names.

            The stage solve rebuilds every device from the config, so the config
            is what a parameter is read from and written to.
            """
            parts = path.split(".")
            if parts[0] not in ("connections", "nodes") or len(parts) < 3:
                raise ValueError(
                    f"run_continuation: unsupported parameter path '{path}'. "
                    "Supported: connections.<id>.<attr> or nodes.<id>.<attr>."
                )
            entry = next(
                (e for e in self.config.get(parts[0]) or [] if e.get("id") == parts[1]),
                None,
            )
            if entry is None:
                raise ValueError(
                    f"run_continuation: '{parts[0]}' entry '{parts[1]}' not found."
                )
            props = entry.setdefault("properties", {})
            attr = ".".join(parts[2:])
            if attr not in props:
                raise ValueError(
                    f"run_continuation: '{path}' is not a config property of "
                    f"'{parts[1]}' (it varies config properties only; declared: "
                    f"{sorted(props)})."
                )
            return props, attr

        def _get_param(path: str) -> float:
            """Return the parameter's current value in the config."""
            props, attr = _properties(path)
            return float(props[attr])

        def _set_param(path: str, value: float) -> None:
            """Write *value* into the config the next stage solve is built from."""
            props, attr = _properties(path)
            props[attr] = value

        def _check_until() -> bool:
            """Return True if the stopping predicate is satisfied."""
            if t_below is not None:
                import cantera as ct  # noqa: PLC0415

                for r in converter.reactors.values():
                    if isinstance(r, ct.Reservoir):
                        continue
                    try:
                        if r.phase.T < float(t_below):
                            return True
                    except Exception:
                        pass
            if t_above is not None:
                import cantera as ct  # noqa: PLC0415

                for r in converter.reactors.values():
                    if isinstance(r, ct.Reservoir):
                        continue
                    try:
                        if r.phase.T > float(t_above):
                            return True
                    except Exception:
                        pass
            return False

        def _next_value(current: float, step_idx: int) -> Optional[float]:
            """Compute next parameter value from the update spec.

            Returns ``None`` when the list is exhausted.
            """
            if "multiply" in update_spec:
                return current * float(update_spec["multiply"])
            if "set" in update_spec:
                return float(update_spec["set"])
            if "list" in update_spec:
                values_list = update_spec["list"]
                if step_idx < len(values_list):
                    return float(values_list[step_idx])
                return None
            raise ValueError(
                f"run_continuation: 'update:' must have 'multiply', 'set', or 'list' key. "
                f"Got: {sorted(update_spec.keys())}"
            )

        # Collect sweep trajectory rows
        continuation_rows: list = []

        trajectory = self.new_trajectory()
        inlet_states: Dict[str, Any] = {}

        _get_param(parameter_path)  # fail before any solve if the path is wrong
        if "list" in update_spec:
            # Step 0 solves list[0]; step n solves list[n].
            _set_param(parameter_path, float(update_spec["list"][0]))
            plan = self.build_stage_graph()

        for step_idx in range(max_iters):
            # Re-solve all stages with the current parameter value
            inlet_states = {}
            trajectory = self.new_trajectory()
            for stage in plan.ordered_stages:
                self.solve_stage(plan, stage, inlet_states, trajectory)
            # Let ``connections.<logical inter-stage id>`` name the inlet MFC.
            alias_inter_connection_mfcs(converter, plan)

            # Record current parameter value + reactor temperatures
            param_val = _get_param(parameter_path)

            row: Dict[str, Any] = {"step": step_idx, "parameter": param_val}
            import cantera as ct  # noqa: PLC0415

            for rid, r in converter.reactors.items():
                if not isinstance(r, ct.Reservoir):
                    try:
                        row[f"{rid}.T"] = r.phase.T
                    except Exception:
                        pass
            continuation_rows.append(row)

            # Check stopping condition
            if _check_until():
                logger.info(
                    "run_continuation: stopped at step %d (until predicate satisfied).",
                    step_idx,
                )
                break

            # Compute next parameter value
            next_val = _next_value(param_val, step_idx + 1)
            if next_val is None:
                logger.info(
                    "run_continuation: stopped at step %d (list exhausted).", step_idx
                )
                break

            _set_param(parameter_path, next_val)
            # The plan (and its stream points) is rebuilt from the updated config.
            plan = self.build_stage_graph()

        self.build_viz_network(plan, trajectory)
        converter._staged_trajectory = trajectory
        self._continuation_rows = continuation_rows
        return self

    # ------------------------------------------------------------------
    # High-level convenience methods
    # ------------------------------------------------------------------

    def build(self) -> "BoulderRunner":
        """Instantiate the converter, build and solve the staged network.

        Delegates to :meth:`~boulder.cantera_converter.DualCanteraConverter.build_network`
        (the staged solve every entry point uses), then takes its results:
        there is no second stage loop here.  :meth:`solve_stage` and
        :meth:`build_viz_network` stay public for the generated scripts and
        :meth:`run_continuation`, which step the stages themselves.

        Returns ``self`` for chaining.  After this call:

        - ``self.converter`` is the :class:`~boulder.cantera_converter.DualCanteraConverter`.
        - ``self.config`` carries the stream-point nodes and connections the
          staged solve added (updated in place).
        - ``self.network`` is a raw visualization :class:`~cantera.ReactorNet`
          (upgraded to the :class:`~boulder.staged_network.StagedReactorNet`
          facade after :meth:`solve` is called).
        - ``self.code`` is the generated Python script string (it needs Boulder and the host's plugins).
        """
        converter = self._ensure_converter()
        converter.build_network(self.config)

        # `build_network` solved a copy of the config; keep this runner's own
        # (the caller's) dict current with what the solve synthesised.
        built = converter._last_config
        assert built is not None  # set by build_network
        self.config.clear()
        self.config.update(built)
        self.network = converter.network
        self.code = "\n".join(converter.code_lines)

        # Initialize the scope recorder after the network is built so the
        # reactors/connections are populated.  The recorder captures state
        # at the end of the build (steady-state snapshot or final transient step).
        scopes_block = self.config.get("scopes")
        if scopes_block:
            from .scopes import ScopeRecorder

            self._scope_recorder = ScopeRecorder(scopes_block, converter)
            # Record one snapshot at the end of the steady-state build so that
            # BoulderRunner.scopes is non-empty even for steady-state cases.
            # Transient step-by-step recording is handled by _run_transient_solver
            # via converter._scope_recorder when set.
            converter._scope_recorder = self._scope_recorder  # type: ignore[attr-defined, assignment]
            # Take an initial snapshot at t=0 (or the final time if a trajectory is available)
            last_t = 0.0
            trajectory = converter._staged_trajectory
            for _stage_traj in (trajectory.networks if trajectory else {}).values():
                try:
                    last_t = float(_stage_traj.time)
                except Exception:
                    pass
            self._scope_recorder.record(last_t)

        return self

    def solve(self) -> "BoulderRunner":
        """Build (if not done) and produce a typed :class:`~boulder.SimulationResult`.

        After this call ``self.result`` is a :class:`~boulder.SimulationResult`
        and ``self.network`` is the same
        :class:`~boulder.staged_network.StagedReactorNet` facade as
        ``self.result.network`` — i.e. ``self.network is self.result.network``.

        Returns ``self`` for chaining.
        """
        if self.network is None or not hasattr(self.network, "visualization_network"):
            self.build()
        from .simulation_result import make_simulation_result

        converter = self._ensure_converter()
        self.result = make_simulation_result(converter, self.config)
        self.network = self.result.network
        return self

    def run_headless(
        self,
        *,
        download_path: Optional[str] = None,
        simulate: bool = True,
    ) -> "BoulderRunner":
        """Solve the network and optionally write a downloadable Python script.

        This is the single source of truth for the ``--headless --download``
        CLI flow.  Custom ``BoulderRunner`` subclasses use the same method so the
        generated scripts stay on one code path (same converter wiring). It
        only solves and writes code: storing a run is the run-set pipeline's job
        (:func:`boulder.sweep_runner.run_set`, what ``--run`` calls).

        Parameters
        ----------
        download_path :
            Path to write the Python script (needs Boulder to run).  Skipped when ``None``.
        simulate :
            When ``True``, run ``run_streaming_simulation`` to append the
            reactor-state reporting section to the generated code (the staged
            solve has already run).
        """
        self.solve()
        if simulate:
            converter = self._ensure_converter()
            converter.run_streaming_simulation(config=self.config)
            self.code = "\n".join(converter.code_lines)
        if download_path is not None:
            with open(download_path, "w", encoding="utf-8") as fh:
                fh.write(self.code or "")
        return self
