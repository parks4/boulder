"""Background simulation worker for streaming updates."""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
    for rid, v in series.items():
        entry: Dict[str, Any] = {}
        for key, val in v.items():
            if key in ("T", "P") and isinstance(val, list):
                entry[key] = val.copy()
            elif key in ("X", "Y") and isinstance(val, dict):
                entry[key] = {
                    s: arr.copy() if isinstance(arr, list) else arr
                    for s, arr in val.items()
                }
            elif isinstance(val, list):
                entry[key] = val.copy()
            else:
                entry[key] = val
        out[rid] = entry
    return out


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

    # Status flags
    is_running: bool = False
    is_complete: bool = False
    error_message: Optional[str] = None

    # Timing information
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    total_time: Optional[float] = None  # simulation end time (s), for progress %

    def get_elapsed_time(self) -> Optional[float]:
        """Get elapsed time in seconds. Returns None if not started."""
        if self.start_time is None:
            return None
        end_time = self.end_time if self.end_time is not None else time.time()
        return end_time - self.start_time

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
        #: Optional reference to FastAPI app.state; updated with cache result on
        #: successful solve so GUI actions see the new cache without server restart.
        self._app_state: Optional[Any] = None

    def start_simulation(
        self,
        converter: Any,
        config: Dict[str, Any],
        simulation_time: float = 10.0,
        time_step: float = 1.0,
        app_state: Optional[Any] = None,
    ) -> None:
        """Start a background simulation."""
        if self._worker_thread and self._worker_thread.is_alive():
            logger.warning("Simulation already running, stopping previous simulation")
            self.stop_simulation()

        # Reset state
        self._stop_event.clear()
        self._app_state = app_state
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
        """Stop the current simulation."""
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=5.0)
            if self._worker_thread.is_alive():
                logger.warning("Worker thread did not stop gracefully")

        with self._lock:
            self.progress.is_running = False
        logger.info("Simulation stopped")

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
                is_running=self.progress.is_running,
                is_complete=self.progress.is_complete,
                error_message=self.progress.error_message,
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

            # Snapshot nodes/connections before build_network mutates the config
            # in-place (staged solver adds outlet/interface nodes).  The pre-build
            # snapshot is used for fingerprinting so the startup fingerprint—
            # computed from the un-enriched validated config—matches the cache entry.
            import copy as _copy

            pre_build_config: Dict[str, Any] = {
                **config,
                "nodes": _copy.deepcopy(config.get("nodes") or []),
                "connections": _copy.deepcopy(config.get("connections") or []),
            }

            # Callback fired by solve_staged after each stage completes.
            # n_total is passed by the solver on each call, so n_stages stays
            # current without a separate pre-parse.
            def _build_stage_callback(stage_id: str, n_done: int, n_total: int) -> None:
                with self._lock:
                    self.progress.stages_done = n_done
                    self.progress.n_stages = n_total

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
            # (e.g. interface-reservoir nodes, programmatic edges) so the client
            # receives a single source of truth for the visual graph.
            with self._lock:
                self.progress.updated_nodes = list(config.get("nodes") or [])
                self.progress.updated_connections = list(
                    config.get("connections") or []
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
                        self.progress.reactor_reports = self._generate_reactor_reports(
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

            logger.info(
                f"Starting streaming simulation: {simulation_time}s with {time_step}s steps"
            )

            # Run the streaming simulation using the converter's method
            results, code_str = converter.run_streaming_simulation(
                simulation_time=simulation_time,
                time_step=time_step,
                progress_callback=progress_callback,
                config=config,
            )

            # Finalize results
            logger.info(f"Simulation completed: {len(results['time'])} time points")
            reactor_reports = self._generate_reactor_reports(converter, results)
            connection_reports = self._generate_connection_reports(converter)
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

            # Persist results to disk cache (best-effort: never aborts the solve).
            # Pass pre_build_config so the fingerprint matches the startup fingerprint.
            self._persist_to_cache(
                converter,
                config,
                results,
                reactor_reports,
                connection_reports,
                code_str,
                pre_build_config=pre_build_config,
            )

        except Exception as e:
            logger.error(f"Simulation failed: {e}", exc_info=True)
            with self._lock:
                self.progress.error_message = str(e)
                self.progress.is_running = False
                self.progress.is_complete = False
                self.progress.end_time = time.time()

    def _persist_to_cache(
        self,
        converter: Any,
        config: Dict[str, Any],
        results: Dict[str, Any],
        reactor_reports: Dict[str, Any],
        connection_reports: Dict[str, Any],
        code_str: str,
        pre_build_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist GUI payload + SimulationResult to disk cache (best-effort).

        Parameters
        ----------
        pre_build_config:
            Config snapshot taken *before* ``build_network`` enriched it with
            outlet/interface nodes.  When provided, the fingerprint is computed
            from this snapshot so it matches the fingerprint computed from the
            validated config at startup (which is also pre-build).  The
            post-build ``config`` is still stored as the config_snapshot.

        Failures are logged at WARNING level and never propagate to the caller.
        """
        try:
            from .result_cache import (
                cache_dir_for,
                compute_fingerprint,
                load_result,
                run_contributors,
                save_alias,
                save_result,
            )
            from .simulation_result import make_simulation_result

            mechanism_raw = getattr(converter, "mechanism", None) or "gri30.yaml"
            mechanism = converter.resolve_mechanism(mechanism_raw)
            config_path = getattr(converter, "_download_config_path", None)
            cache_root = cache_dir_for(config_path)
            if cache_root is None:
                logger.debug(
                    "No cache root available (no config path); skipping cache."
                )
                return

            progress = self.get_progress()
            # Use pre-build snapshot for fingerprinting when available so the hash
            # matches the startup fingerprint (computed from the un-enriched config).
            fp_config = pre_build_config if pre_build_config is not None else config
            fingerprint = compute_fingerprint(fp_config, mechanism=mechanism)

            # Expose the fingerprint immediately so GUI actions can detect this
            # cache entry before contributors finish writing artifacts.
            if self._app_state is not None:
                try:
                    self._app_state.preloaded_fingerprint = fingerprint
                except Exception:  # noqa: BLE001
                    pass

            gui_payload: Dict[str, Any] = {
                "status": "complete",
                "is_complete": True,
                "error_message": None,
                "times": progress.times,
                "reactors_series": progress.reactors_series,
                "reactor_reports": reactor_reports,
                "connection_reports": connection_reports,
                "code_str": code_str,
                "summary": progress.summary,
                "sankey_links": progress.sankey_links,
                "sankey_nodes": progress.sankey_nodes,
                "elapsed_time": progress.get_calculation_time(),
                "updated_nodes": progress.updated_nodes,
                "updated_connections": progress.updated_connections,
            }

            from .api.sse import _serialise_reports

            gui_payload["reactor_reports"] = _serialise_reports(reactor_reports)

            simulation_result = make_simulation_result(converter, config)

            entry = save_result(
                cache_root=cache_root,
                fingerprint=fingerprint,
                gui_payload=gui_payload,
                config_snapshot=config,
                mechanism=mechanism,
            )

            # Write an alias from the post-build fingerprint → canonical entry.
            # After a solve, the frontend stores the post-build config (with
            # stream-point nodes added by the staged solver).  On the next
            # "Run Simulation" click, check-cache fingerprints the post-build
            # config, which differs from the pre-build fingerprint used here.
            # The alias lets load_result_flexible find the entry via either key.
            post_build_fp = compute_fingerprint(config, mechanism=mechanism)
            if post_build_fp != fingerprint:
                save_alias(cache_root, post_build_fp, fingerprint)
                logger.debug(
                    "Cache post-build alias written: %s → %s",
                    post_build_fp[:12],
                    fingerprint[:12],
                )

            artifacts_dir = entry / "artifacts"

            # Update app.state immediately after save_result so the frontend
            # detects the cache hit and Export can poll for the bundle instead
            # of triggering a full re-solve.  Contributors write their artifacts
            # next (potentially slow), but the cache entry is already addressable.
            cached = load_result(cache_root, fingerprint)
            if cached is not None and self._app_state is not None:
                try:
                    self._app_state.preloaded_result = cached
                    logger.debug(
                        "app.state.preloaded_result updated (pre-contributors, %s…)",
                        fingerprint[:12],
                    )
                except Exception as state_exc:  # noqa: BLE001
                    logger.debug(
                        "Could not update app.state (pre-contrib): %s", state_exc
                    )

            contributors = getattr(
                getattr(converter, "plugins", None), "cache_contributors", []
            )
            if contributors:
                run_contributors(
                    contributors,
                    config,
                    converter,
                    simulation_result,
                    fingerprint,
                    artifacts_dir,
                )

        except OSError as exc:
            logger.warning("Cache persistence failed (OSError): %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache persistence failed: %s", exc)

    def _generate_reactor_reports(
        self, converter: Any, results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate reactor reports for thermo analysis."""
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
                            name: phase.X[i]
                            for i, name in enumerate(phase.species_names)
                        },
                        "species_names": phase.species_names,
                        "molecular_weights": phase.molecular_weights,
                        "mass_fractions": phase.Y.copy(),
                        # Generate formatted reports for UI display
                        "reactor_report": f"Temperature: {current_T_c:.2f} °C (Fixed)\nPressure: "
                        f"{current_P:.2e} Pa (Fixed)\nType: Reservoir (Infinite Capacity)",
                        # Use the reactor's own phase to ensure mechanism matches reactor
                        "thermo_report": phase.report(),
                    }
                    continue

                # Get final state data for regular reactors
                if reactor_id in results["reactors"]:
                    reactor_data = results["reactors"][reactor_id]
                    if reactor_data["T"] and reactor_data["P"]:
                        # Use final state
                        final_T = reactor_data["T"][-1]
                        final_P = reactor_data["P"][-1]
                        final_X = {
                            s: reactor_data["X"][s][-1] for s in reactor_data["X"]
                        }

                        # Generate thermo report (display temperature in °C)
                        final_T_c = final_T - 273.15
                        reactor_reports[reactor_id] = {
                            "T": final_T,
                            "P": final_P,
                            "X": final_X,
                            "species_names": phase.species_names,
                            "molecular_weights": phase.molecular_weights,
                            "mass_fractions": phase.Y.copy(),
                            # Generate formatted reports for UI display
                            "reactor_report": f"Temperature: {final_T_c:.2f} °C\nPressure: "
                            f"{final_P:.2e} Pa\nVolume: {reactor.volume:.2e} m³",
                            # Use the reactor's own phase to ensure mechanism matches reactor
                            "thermo_report": phase.report(),
                        }

        except Exception as e:
            logger.warning(f"Failed to generate reactor reports: {e}")

        return reactor_reports

    def _generate_connection_reports(self, converter: Any) -> Dict[str, Any]:
        """Generate connection (MFC) reports with mass and volumetric flow rates.

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


# Global worker instance
_global_worker: Optional[SimulationWorker] = None


def get_simulation_worker() -> SimulationWorker:
    """Get the global simulation worker instance."""
    global _global_worker
    if _global_worker is None:
        _global_worker = SimulationWorker()
    return _global_worker
