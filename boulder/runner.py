"""BoulderRunner — orchestrator for the YAML → network → result pipeline.

Provides a single class that subclasses can override to inject custom
converters (e.g. ``MyRunner`` with ``MyConverter``).  The Boulder CLI uses
the base class; other entrypoints may pass ``runner_class=MyRunner``.
"""

from __future__ import annotations

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
        signals are declared or if :meth:`build` has not been called yet.

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
        cfg = cls.validate(cls.normalize(cls.load(path)))
        return cls(config=cfg, config_path=path)

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
        from .cantera_converter import DualCanteraConverter

        converter_cls = self.__class__.converter_class or DualCanteraConverter
        c = converter_cls(
            mechanism=self._default_mechanism_name(),
            plugins=self.plugins,
        )
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

    def solve_stage(
        self,
        plan: "StageExecutionPlan",
        stage: "Stage",
        inlet_states: Dict[str, Any],
        trajectory: "LagrangianTrajectory",
    ) -> None:
        """Build and solve one stage, updating *inlet_states* and *trajectory* in place.

        This is exactly one iteration of the :func:`~boulder.staged_solver.solve_staged`
        loop body.  Calling it once per stage in topological order is equivalent
        to calling :func:`~boulder.staged_solver.solve_staged` on the full plan.

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

        Examples
        --------
        .. minigallery:: boulder.runner.BoulderRunner.solve_stage
           :add-heading: Examples using solve_stage
        """
        from .staged_solver import (
            _apply_mechanism_switch,
            _collect_stage_states,
            _extract_gas_state,
            _flow_order_within_stage,
        )

        converter = self._ensure_converter()

        stage_nodes = [
            n
            for n in (self.config.get("nodes") or [])
            if n["id"] in set(stage.node_ids)
        ]
        network, stage_reactors = converter.build_sub_network(
            stage_nodes=stage_nodes,
            stage_connections=stage.intra_connections,
            stage_mechanism=stage.mechanism,
            inlet_states=inlet_states,
            stage_id=stage.id,
            stage=stage,
        )
        trajectory.networks[stage.id] = network

        flow_order = _flow_order_within_stage(stage)
        states = _collect_stage_states(
            stage, stage_reactors, flow_order, converter, network=network
        )
        mapping_losses = None

        for ic in stage.inter_connections_out:
            source_reactor = stage_reactors.get(ic.source_node)
            if source_reactor is None:
                logger.warning(
                    "Inter-stage connection '%s': source reactor '%s' not found.",
                    ic.id,
                    ic.source_node,
                )
                continue
            outlet_gas = _extract_gas_state(source_reactor, stage.mechanism, converter)
            if ic.mechanism_switch is not None:
                target_stage = next(
                    (s for s in plan.ordered_stages if s.id == ic.target_stage),
                    None,
                )
                if target_stage is None:
                    raise ValueError(
                        f"Inter-stage connection '{ic.id}' targets unknown stage "
                        f"'{ic.target_stage}'."
                    )
                outlet_gas, mapping_losses = _apply_mechanism_switch(
                    outlet_gas,
                    target_stage.mechanism,
                    ic.mechanism_switch,
                    converter,
                )
            inlet_states[ic.target_node] = outlet_gas

        trajectory.add_segment(
            stage_id=stage.id,
            mechanism=stage.mechanism,
            states=states,
            mapping_losses=mapping_losses,
        )

    def build_viz_network(
        self,
        plan: "StageExecutionPlan",
        trajectory: "LagrangianTrajectory",
    ) -> None:
        """Assemble the full visualization :class:`~cantera.ReactorNet` from all converged states.

        Connects all inter-stage connections into one ReactorNet (not solved
        again — just for visualization and Sankey generation).  Sets
        ``self.network`` and ``trajectory.viz_network``.

        Parameters
        ----------
        plan :
            Execution plan (provides inter-stage connection list).
        trajectory :
            Updated in place: ``trajectory.viz_network`` is set.

        Examples
        --------
        .. minigallery:: boulder.runner.BoulderRunner.build_viz_network
           :add-heading: Examples using build_viz_network
        """
        converter = self._ensure_converter()
        viz_net = converter.build_viz_network(
            all_connections=self.config.get("connections") or [],
            built_conn_ids=(
                set(converter.connections.keys()) | set(converter.walls.keys())
            ),
        )
        trajectory.viz_network = viz_net
        self.network = viz_net

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

        # Build the network for the first iteration
        if self.network is None:
            self.build()

        converter = self._ensure_converter()

        def _get_param(path: str) -> float:
            """Resolve dotted parameter path to current float value."""
            parts = path.split(".")
            if parts[0] == "connections" and len(parts) >= 3:
                conn_id = parts[1]
                attr = ".".join(parts[2:])
                device = converter.connections.get(conn_id)
                if device is None:
                    raise ValueError(
                        f"run_continuation: connection '{conn_id}' not found."
                    )
                return float(getattr(device, attr))
            if parts[0] == "nodes" and len(parts) >= 3:
                node_id = parts[1]
                attr = ".".join(parts[2:])
                reactor = converter.reactors.get(node_id)
                if reactor is None:
                    raise ValueError(f"run_continuation: node '{node_id}' not found.")
                return float(getattr(reactor, attr))
            raise ValueError(
                f"run_continuation: unsupported parameter path '{path}'. "
                "Supported: connections.<id>.<attr> or nodes.<id>.<attr>."
            )

        def _set_param(path: str, value: float) -> None:
            """Set parameter at dotted path to *value*."""
            parts = path.split(".")
            if parts[0] == "connections" and len(parts) >= 3:
                conn_id = parts[1]
                attr = ".".join(parts[2:])
                device = converter.connections.get(conn_id)
                if device is None:
                    raise ValueError(
                        f"run_continuation: connection '{conn_id}' not found."
                    )
                setattr(device, attr, value)
                return
            if parts[0] == "nodes" and len(parts) >= 3:
                node_id = parts[1]
                attr = ".".join(parts[2:])
                reactor = converter.reactors.get(node_id)
                if reactor is None:
                    raise ValueError(f"run_continuation: node '{node_id}' not found.")
                setattr(reactor, attr, value)
                return
            raise ValueError(f"run_continuation: unsupported parameter path '{path}'.")

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

        plan = self.build_stage_graph()
        trajectory = self.new_trajectory()
        inlet_states: Dict[str, Any] = {}

        for step_idx in range(max_iters):
            # Re-solve all stages with the current parameter value
            inlet_states = {}
            trajectory = self.new_trajectory()
            for stage in plan.ordered_stages:
                self.solve_stage(plan, stage, inlet_states, trajectory)

            # Record current parameter value + reactor temperatures
            try:
                param_val = _get_param(parameter_path)
            except Exception:
                param_val = float("nan")

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

        self.build_viz_network(plan, trajectory)
        converter._staged_trajectory = trajectory
        self._continuation_rows = continuation_rows
        return self

    # ------------------------------------------------------------------
    # High-level convenience methods
    # ------------------------------------------------------------------

    def build(self) -> "BoulderRunner":
        """Instantiate the converter, build and solve the staged network.

        Internally calls :meth:`build_stage_graph`, :meth:`solve_stage` for
        each stage, and :meth:`build_viz_network` — the same sequence emitted
        in the downloadable Python script.

        Returns ``self`` for chaining.  After this call:

        - ``self.converter`` is the :class:`~boulder.cantera_converter.DualCanteraConverter`.
        - ``self.network`` is a raw visualization :class:`~cantera.ReactorNet`
          (upgraded to the :class:`~boulder.staged_network.StagedReactorNet`
          facade after :meth:`solve` is called).
        - ``self.code`` is the generated standalone Python script string.
        """
        converter = self._ensure_converter()

        plan = self.build_stage_graph()
        trajectory = self.new_trajectory()
        inlet_states: Dict[str, Any] = {}

        for stage in plan.ordered_stages:
            self.solve_stage(plan, stage, inlet_states, trajectory)

        self.build_viz_network(plan, trajectory)

        # Mark the converter as staged-solved so run_streaming_simulation
        # knows to emit the steady-state report instead of a time loop.
        converter._staged_trajectory = trajectory

        # Generate the downloadable script now that stage names are known.
        config_path = self.config_path or "config.yaml"
        script_lines = [
            "# Load configuration from YAML and build Cantera network",
            "import cantera as ct",
            *converter.script_load_lines(config_path, plan),
        ]
        converter.code_lines = script_lines
        self.code = "\n".join(script_lines)

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
            converter._scope_recorder = self._scope_recorder  # type: ignore[attr-defined]
            # Take an initial snapshot at t=0 (or the final time if a trajectory is available)
            last_t = 0.0
            for _stage_traj in trajectory.networks.values():
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
        end_time: Optional[float] = None,
        dt: Optional[float] = None,
    ) -> "BoulderRunner":
        """Solve the network and optionally write a downloadable Python script.

        This is the single source of truth for the ``--headless --download``
        CLI flow.  Custom ``BoulderRunner`` subclasses use the same method so the
        generated scripts stay on one code path (same converter wiring).

        Parameters
        ----------
        download_path :
            Path to write the standalone Python script.  Skipped when ``None``.
        simulate :
            When ``True`` and ``end_time`` is set, run ``run_streaming_simulation``
            to append the time-advance section to the generated code.
        end_time :
            Simulation end time in seconds (from ``settings.end_time`` in the YAML).
        dt :
            Simulation time step in seconds (from ``settings.dt`` in the YAML).
        """
        self.solve()
        if simulate:
            # Always call run_streaming_simulation so the downloadable script
            # contains the full reactor-state reporting section.  When the YAML
            # has no end_time we use a dummy 0.0 so only the steady-state report
            # is emitted (no time-stepping), which mirrors the old headless path.
            converter = self._ensure_converter()
            converter.run_streaming_simulation(
                simulation_time=float(end_time) if end_time is not None else 0.0,
                time_step=(dt or 1.0),
                config=self.config,
            )
            self.code = "\n".join(converter.code_lines)
        if download_path is not None:
            with open(download_path, "w", encoding="utf-8") as fh:
                fh.write(self.code or "")
        return self
