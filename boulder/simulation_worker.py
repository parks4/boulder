"""Background simulation worker for streaming updates."""

import dataclasses
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

import cantera as ct  # type: ignore

from .verbose_utils import get_verbose_logger

logger = get_verbose_logger(__name__)


def _copy_reactors_series(
    series: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Deep-copy reactors_series while preserving all extra flags and arrays.

    Copies ``T``, ``P``, ``X``, ``Y`` lists and passes through any additional
    keys (``is_spatial``, ``is_psr``, ``x``, ``t``, ``fbs_convergence``, …)
    by shallow-copying their values so the thread-safe snapshot remains
    independent of the worker's live state.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for rid, v in list(series.items()):  # snapshot: a solver thread keeps writing
        entry: Dict[str, Any] = {}
        for key, val in list(v.items()):
            if key in ("T", "P") and isinstance(val, list):
                entry[key] = val.copy()
            elif key in ("X", "Y") and isinstance(val, dict):
                entry[key] = {
                    s: arr.copy() if isinstance(arr, list) else arr
                    for s, arr in list(val.items())
                }
            elif isinstance(val, list):
                entry[key] = val.copy()
            else:
                entry[key] = val
        out[rid] = entry
    return out


def design_warnings_of(reactor: Any) -> List[str]:
    """Return the reactor's own design warnings, ``[]`` when it has none.

    A reactor class may expose ``design_warnings() -> list[str]``: one line
    per design check its solved state violates (an inlet temperature above
    the equipment's rating, say). Boulder does not know the checks; it only
    carries the lines to the GUI, where they show in the Thermo Report tab,
    the Properties panel and as the node's warning badge. Failures inside
    the method are logged and yield ``[]`` so a report is never lost.
    """
    fn = getattr(reactor, "design_warnings", None)
    if not callable(fn):
        return []
    try:
        return [str(line) for line in (fn() or [])]
    except Exception as e:  # noqa: BLE001 - a host method must not sink the report
        logger.warning(f"design_warnings() failed on {type(reactor).__name__}: {e}")
        return []


def generate_reactor_reports(converter: Any, results: Dict[str, Any]) -> Dict[str, Any]:
    """Generate reactor reports for thermo analysis.

    Each report carries a ``warnings`` list, see :func:`design_warnings_of`.

    Free function (not a method — reads only *converter*/*results*) so any
    solve path can populate ``reactor_reports`` the same way the live GUI
    solve does, e.g. :func:`boulder.sweep_runner._solve`.
    """
    reactor_reports = {}

    try:
        # Generate reports for each reactor
        for reactor_id, reactor in converter.reactors.items():
            phase = reactor.phase
            if isinstance(reactor, ct.Reservoir):
                # Handle Reservoirs - they maintain fixed thermodynamic conditions
                current_T = phase.T
                current_P = phase.P
                current_T_c = current_T - 273.15

                reactor_reports[reactor_id] = {
                    "T": current_T,
                    "P": current_P,
                    "X": {
                        name: phase.X[i] for i, name in enumerate(phase.species_names)
                    },
                    "species_names": phase.species_names,
                    "molecular_weights": phase.molecular_weights.tolist(),
                    "mass_fractions": phase.Y.tolist(),
                    # Generate formatted reports for UI display
                    "reactor_report": f"Temperature: {current_T_c:.2f} °C (Fixed)\nPressure: "
                    f"{current_P:.2e} Pa (Fixed)\nType: Reservoir (Infinite Capacity)",
                    # Use the reactor's own phase to ensure mechanism matches reactor
                    "thermo_report": phase.report(),
                    "warnings": design_warnings_of(reactor),
                }
                continue

            # Get final state data for regular reactors
            if reactor_id in results["reactors"]:
                reactor_data = results["reactors"][reactor_id]
                if reactor_data["T"] and reactor_data["P"]:
                    # Use final state
                    final_T = reactor_data["T"][-1]
                    final_P = reactor_data["P"][-1]
                    final_X = {s: reactor_data["X"][s][-1] for s in reactor_data["X"]}

                    # Generate thermo report (display temperature in °C)
                    final_T_c = final_T - 273.15
                    reactor_reports[reactor_id] = {
                        "T": final_T,
                        "P": final_P,
                        "X": final_X,
                        "species_names": phase.species_names,
                        "molecular_weights": phase.molecular_weights.tolist(),
                        "mass_fractions": phase.Y.tolist(),
                        # Generate formatted reports for UI display
                        "reactor_report": f"Temperature: {final_T_c:.2f} °C\nPressure: "
                        f"{final_P:.2e} Pa\nVolume: {reactor.volume:.2e} m³",
                        # Use the reactor's own phase to ensure mechanism matches reactor
                        "thermo_report": phase.report(),
                        "warnings": design_warnings_of(reactor),
                    }

    except Exception as e:
        logger.warning(f"Failed to generate reactor reports: {e}")

    return reactor_reports


def generate_connection_reports(converter: Any) -> Dict[str, Any]:
    """Generate connection (MFC) reports with mass and volumetric flow rates.

    Free function (not a method — reads only *converter*) so any solve path
    can populate ``connection_reports`` the same way the live GUI solve does,
    e.g. :func:`boulder.sweep_runner._solve`.

    Volumetric flow real: at source T, P. Normal: DIN 1343 (0 °C, 101325 Pa).
    """
    R_GAS = 8.314462618  # J/(mol·K)
    T_NORMAL_K = 273.15
    P_NORMAL_PA = 101325.0

    connection_reports: Dict[str, Any] = {}
    try:
        reactor_id_by_obj = {r: rid for rid, r in converter.reactors.items()}
        for conn_id, device in converter.connections.items():
            if not isinstance(device, ct.MassFlowController):
                continue
            upstream = device.upstream
            thermo = upstream.phase
            T = float(thermo.T)
            P = float(thermo.P)
            # Cantera molecular_weights in kg/kmol; X is mole fractions
            M_kg_kmol = sum(
                float(thermo.X[i]) * float(thermo.molecular_weights[i])
                for i in range(thermo.n_species)
            )
            M_kg_mol = M_kg_kmol / 1000.0
            rho = (P * M_kg_mol) / (R_GAS * T)
            rho_normal = (P_NORMAL_PA * M_kg_mol) / (R_GAS * T_NORMAL_K)
            mfr = float(device.mass_flow_rate)
            if rho > 0:
                Q_real = mfr / rho
            else:
                Q_real = 0.0
            if rho_normal > 0:
                Q_normal = mfr / rho_normal
            else:
                Q_normal = 0.0
            connection_reports[conn_id] = {
                "mass_flow_rate": mfr,
                "volumetric_flow_real_m3_s": Q_real,
                "volumetric_flow_normal_m3_s": Q_normal,
                "source_id": reactor_id_by_obj.get(upstream),
                "target_id": reactor_id_by_obj.get(device.downstream),
            }
    except Exception as e:
        logger.warning(f"Failed to generate connection reports: {e}")

    return connection_reports


@dataclass
class SimulationProgress:
    """Thread-safe container for simulation progress data."""

    # Network and converter state
    network: Optional[ct.ReactorNet] = None
    reactors_dict: Dict[str, ct.Reactor] = field(default_factory=dict)
    mechanism: str = ""

    # Simulation data
    times: List[float] = field(default_factory=list)
    reactors_series: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    code_str: str = ""
    reactor_reports: Dict[str, Any] = field(default_factory=dict)
    connection_reports: Dict[str, Any] = field(default_factory=dict)
    summary: List[Dict[str, Any]] = field(default_factory=list)
    sankey_links: Optional[Dict[str, Any]] = None
    sankey_nodes: Optional[List[str]] = None

    # Nodes and connections added programmatically during network build
    # (e.g. interface-reservoir nodes synthesised by the staged solver, or
    # edges added by post-build hooks).  Both are sent to the client in the
    # SSE "complete" event so the visual graph stays in sync with the solver.
    updated_nodes: Optional[List[Dict[str, Any]]] = None
    updated_connections: Optional[List[Dict[str, Any]]] = None

    # Build-phase progress counters.  Updated after each staged-solver stage.
    # The UI uses these directly so it can show "Stage 2 / 3" etc.
    stages_done: int = 0
    n_stages: int = 0

    # Stage ids that have finished solving, in completion order (append-only,
    # reset per run via a fresh SimulationProgress()). Lets the client map a
    # node's ``group`` (== stage id) to a live per-node status on the graph
    # (calculating / resolved) without needing a separate "stage started"
    # event -- stages solve strictly sequentially, so the first stage id not
    # yet in this list is the one currently running.
    completed_stage_ids: List[str] = field(default_factory=list)

    # Status flags
    is_running: bool = False
    is_complete: bool = False
    error_message: Optional[str] = None
    #: A stop has been requested (``stop_simulation()`` was called) but the
    #: worker thread hasn't exited yet -- cooperative, so it can lag behind
    #: the request by up to one stage. "Stopped" (as opposed to "stopping")
    #: is derived, not tracked separately: ``is_stopping and not is_running``.
    is_stopping: bool = False

    # Timing information
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    total_time: Optional[float] = None  # simulation end time (s), for progress %

    def get_calculation_time(self) -> Optional[float]:
        """Get total calculation time in seconds. Returns None if not completed."""
        if self.start_time is None or self.end_time is None:
            return None
        return self.end_time - self.start_time


class SimulationWorker:
    """Background worker for running Cantera simulations with streaming updates."""

    def __init__(self) -> None:
        self.progress = SimulationProgress()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

    def start_simulation(
        self,
        converter: Any,
        config: Dict[str, Any],
        simulation_time: float,
        time_step: float,
    ) -> None:
        """Start a background simulation.

        The worker only solves. Storing the result is the run-set pipeline's job
        (:func:`boulder.sweep_runner.run_set`), the one writer every entry point
        shares.
        """
        if self._worker_thread and self._worker_thread.is_alive():
            logger.warning("Simulation already running, stopping previous simulation")
            self.stop_simulation()

        # Reset state
        self._stop_event.clear()
        with self._lock:
            self.progress = SimulationProgress()

        # Start worker thread
        self._worker_thread = threading.Thread(
            target=self._run_simulation,
            args=(converter, config, simulation_time, time_step),
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("Background simulation started")

    def stop_simulation(self) -> None:
        """Request that the current simulation stop, without blocking.

        Cooperative, not immediate: it sets the flag ``_run_simulation``'s
        cancellation checkpoints (via ``cancel_token``) and its own finalize
        guard check, then returns right away. The caller learns the worker
        thread actually exited from ``is_running`` turning ``False`` in a
        later :meth:`get_progress` poll -- never by blocking here, which used
        to stall the FastAPI event loop for up to 5 s per stop request.
        """
        self._stop_event.set()
        with self._lock:
            # Only meaningful for a run that's actually in flight -- guards
            # against a late/duplicate stop request marking an already
            # finished (or already-stopped) run as "stopping" again.
            if self.progress.is_running:
                self.progress.is_stopping = True
        logger.info("Simulation stop requested")

    def get_progress(self) -> SimulationProgress:
        """Get current simulation progress (thread-safe copy)."""
        with self._lock:
            # Return a copy to avoid race conditions
            return SimulationProgress(
                network=self.progress.network,
                reactors_dict=self.progress.reactors_dict.copy(),
                mechanism=self.progress.mechanism,
                times=self.progress.times.copy(),
                reactors_series=_copy_reactors_series(self.progress.reactors_series),
                code_str=self.progress.code_str,
                reactor_reports=self.progress.reactor_reports.copy(),
                connection_reports=self.progress.connection_reports.copy(),
                summary=self.progress.summary.copy(),
                sankey_links=self.progress.sankey_links,
                sankey_nodes=self.progress.sankey_nodes,
                updated_nodes=(
                    list(self.progress.updated_nodes)
                    if self.progress.updated_nodes is not None
                    else None
                ),
                updated_connections=(
                    list(self.progress.updated_connections)
                    if self.progress.updated_connections is not None
                    else None
                ),
                stages_done=self.progress.stages_done,
                n_stages=self.progress.n_stages,
                completed_stage_ids=list(self.progress.completed_stage_ids),
                is_running=self.progress.is_running,
                is_complete=self.progress.is_complete,
                error_message=self.progress.error_message,
                is_stopping=self.progress.is_stopping,
                start_time=self.progress.start_time,
                end_time=self.progress.end_time,
                total_time=self.progress.total_time,
            )

    def _run_simulation(
        self,
        converter: Any,
        config: Dict[str, Any],
        simulation_time: float,
        time_step: float,
    ) -> None:
        """Background worker function that runs the actual simulation."""
        try:
            # Mark running immediately so the UI overlay appears.
            # n_stages starts at 0 and is updated on the first stage-complete
            # callback below (avoiding a redundant build_stage_graph call).
            with self._lock:
                self.progress.is_running = True
                self.progress.is_complete = False
                self.progress.error_message = None
                self.progress.start_time = time.time()
                self.progress.end_time = None
                self.progress.total_time = simulation_time
                self.progress.stages_done = 0
                self.progress.n_stages = 0

            logger.info("Building Cantera network in background...")

            # Callback fired by solve_staged after each stage completes.
            # n_total is passed by the solver on each call, so n_stages stays
            # current without a separate pre-parse.
            def _build_stage_callback(stage_id: str, n_done: int, n_total: int) -> None:
                with self._lock:
                    self.progress.stages_done = n_done
                    self.progress.n_stages = n_total
                    self.progress.completed_stage_ids.append(stage_id)

            # Cooperative-cancellation token: staged_solver/cantera_converter
            # check this at each stage/transient-step boundary and raise
            # SolveCancelled if it's set. An attribute, not a build_network
            # kwarg, so a host converter subclass that overrides build_network
            # doesn't need to know about it to keep working.
            converter.cancel_token = self._stop_event

            # Build the network first
            network = converter.build_network(
                config, progress_callback=_build_stage_callback
            )
            logger.info("Network built successfully, starting streaming simulation...")

            # Mark build fully complete using the stage count from the callback.
            with self._lock:
                self.progress.stages_done = self.progress.n_stages

            # Capture the full nodes + connections lists after post-build hooks
            # and the staged solver have run.  Both may grow during the build
            # (e.g. stream-point reservoirs, programmatic edges) so the client
            # receives a single source of truth for the visual graph.
            #
            # Read them off the converter, not off the local ``config``:
            # ``build_network`` deep-copies the config it is handed so a
            # caller's dict is never corrupted, and it is that copy the staged
            # solver enriches with stream-point nodes and their converged
            # thermo (T, P, mdot, h_mass). This local dict never sees them.
            post_config = getattr(converter, "_last_config", None) or config
            with self._lock:
                self.progress.updated_nodes = list(post_config.get("nodes") or [])
                self.progress.updated_connections = list(
                    post_config.get("connections") or []
                )

            # Track last logged % for verbose throttle (log at 0, 25, 50, 75, 100)
            last_logged_pct: List[float] = [-1]

            # Define progress callback for streaming updates
            def progress_callback(
                progress_data: Dict[str, Any], current_time: float, total_time: float
            ) -> None:
                """Update progress during simulation."""
                if self._stop_event.is_set():
                    return  # Don't update if stopping

                with self._lock:
                    self.progress.times = progress_data["time"]
                    self.progress.reactors_series = progress_data["reactors"]
                    # Forward error messages if present (so UI can display immediately)
                    self.progress.error_message = progress_data.get("error_message")
                    # Calculate progress percentage
                    progress_pct = (
                        (current_time / total_time) * 100 if total_time > 0 else 0
                    )
                    # Log every 10% to avoid flooding console (always shown)
                    pct_floor = int(progress_pct // 10) * 10
                    if pct_floor > last_logged_pct[0] or (
                        progress_pct >= 99.9 and last_logged_pct[0] < 100
                    ):
                        last_logged_pct[0] = 100 if progress_pct >= 99.9 else pct_floor
                        logger.info(
                            f"Simulation progress: {progress_pct:.1f}% "
                            f"(t={current_time:.1f}s / {total_time:.1f}s)"
                        )
                    # Stream updated thermo reports so Thermo tab reflects latest state
                    try:
                        interim_results = {
                            "time": self.progress.times,
                            "reactors": self.progress.reactors_series,
                        }
                        self.progress.reactor_reports = generate_reactor_reports(
                            converter, interim_results
                        )
                    except Exception as stream_err:
                        logger.debug(
                            f"Streaming reactor report generation failed: {stream_err}"
                        )

            # Register network on progress now that build is complete
            with self._lock:
                self.progress.network = network
                self.progress.reactors_dict = converter.reactors
                self.progress.mechanism = converter.mechanism
                self.progress.times = []
                self.progress.reactors_series = {}
                self.progress.code_str = ""
                self.progress.reactor_reports = {}
                self.progress.connection_reports = {}

            # Update the live simulation singleton so plugins
            # (e.g. NetworkPlugin) can access the network
            from .live_simulation import update_live_simulation

            update_live_simulation(network, converter.reactors, converter.mechanism)

            # Collect the results of the staged solve that just ran
            results, code_str = converter.run_streaming_simulation(
                progress_callback=progress_callback,
                config=config,
            )

            # Finalize results -- skipped entirely if a stop was requested,
            # checked once here regardless of whether a SolveCancelled
            # checkpoint actually fired. A single-stage steady solve has no
            # checkpoint before this point (see staged_solver.py), so without
            # this explicit check a stop would silently do nothing for that
            # common case: the solve would run to completion and this whole
            # block -- the cache write and is_complete=True -- would fire
            # anyway. Also covers a SolveCancelled that *did* fire mid-stage
            # and unwound straight past this point into the except block below.
            if self._stop_event.is_set():
                with self._lock:
                    self.progress.is_running = False
                    # Set unconditionally here too (not just by
                    # stop_simulation()): that call and the background thread
                    # reaching this point race, so is_stopping could otherwise
                    # still read False for a run that very much did stop.
                    self.progress.is_stopping = True
                logger.info("Simulation stopped before finalizing results")
                return

            # Finalize results
            logger.info(f"Simulation completed: {len(results['time'])} time points")
            reactor_reports = generate_reactor_reports(converter, results)
            connection_reports = generate_connection_reports(converter)
            with self._lock:
                self.progress.times = results["time"]
                self.progress.reactors_series = results["reactors"]
                self.progress.code_str = code_str
                # Store summary if present
                self.progress.summary = results.get("summary", [])
                # Store Sankey data if present
                self.progress.sankey_links = results.get("sankey_links")
                self.progress.sankey_nodes = results.get("sankey_nodes")
                self.progress.reactor_reports = reactor_reports
                self.progress.connection_reports = connection_reports
                self.progress.is_running = False
                self.progress.is_complete = True
                self.progress.end_time = time.time()
                # Carry through final error message if present in results
                if isinstance(results, dict) and results.get("error_message"):
                    self.progress.error_message = results.get("error_message")

        except Exception as e:
            if self._stop_event.is_set():
                # A cancellation checkpoint raised SolveCancelled (or some
                # other exception surfaced while a stop was in flight) --
                # either way this is an intentional stop, not a failure: no
                # error_message, no is_complete.
                logger.info("Simulation stopped: %s", e)
                with self._lock:
                    self.progress.is_running = False
                    self.progress.is_stopping = True
                    self.progress.end_time = time.time()
                return
            logger.error(f"Simulation failed: {e}", exc_info=True)
            with self._lock:
                self.progress.error_message = str(e)
                self.progress.is_running = False
                self.progress.is_complete = False
                self.progress.end_time = time.time()


class RunHandle:
    """Progress of a GUI run, which :func:`boulder.sweep_runner.run_set` executes.

    The run-set pipeline solves, stores, then returns; this object is what
    ``/api/simulations/{id}`` serves meanwhile. It mirrors the solve's progress
    but reports *complete* only once the entry is stored (:meth:`finish`):
    the frontend re-lists the GUI actions on completion, which asks the store
    whether a result exists.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._progress = SimulationProgress(is_running=True, start_time=time.time())
        #: Set by :meth:`stop_simulation`; handed to ``run_set`` as its ``stop_event``.
        self.stop_event = threading.Event()

    def get_progress(self) -> SimulationProgress:
        """Latest snapshot (published snapshots are never mutated, so a shallow copy)."""
        with self._lock:
            return dataclasses.replace(self._progress)

    def stop_simulation(self) -> None:
        """Request that the run stop, without waiting (cooperative)."""
        self.stop_event.set()
        with self._lock:
            if self._progress.is_running:
                self._progress.is_stopping = True

    def publish(self, progress: SimulationProgress) -> None:
        """Record a running solve's snapshot, never as complete."""
        with self._lock:
            self._progress = dataclasses.replace(
                progress,
                is_running=True,
                is_complete=False,
                is_stopping=self._progress.is_stopping,
                start_time=self._progress.start_time,
            )

    def finish(self, gui: Mapping[str, Any]) -> None:
        """Mark the run complete, serving the stored payload *gui*."""
        with self._lock:
            self._progress = dataclasses.replace(
                self._progress,
                times=list(gui.get("times") or []),
                reactors_series=dict(gui.get("reactors_series") or {}),
                reactor_reports=dict(gui.get("reactor_reports") or {}),
                connection_reports=dict(gui.get("connection_reports") or {}),
                code_str=gui.get("code_str") or "",
                summary=list(gui.get("summary") or []),
                sankey_links=gui.get("sankey_links"),
                sankey_nodes=gui.get("sankey_nodes"),
                updated_nodes=gui.get("updated_nodes"),
                updated_connections=gui.get("updated_connections"),
                error_message=None,
                is_running=False,
                is_complete=True,
                end_time=time.time(),
            )

    def fail(self, message: str) -> None:
        """Mark the run failed."""
        with self._lock:
            self._progress = dataclasses.replace(
                self._progress,
                error_message=message,
                is_running=False,
                is_complete=False,
                end_time=time.time(),
            )

    def stopped(self) -> None:
        """Mark the run stopped on request (not an error, not complete)."""
        with self._lock:
            self._progress = dataclasses.replace(
                self._progress,
                is_running=False,
                is_stopping=True,
                end_time=time.time(),
            )
