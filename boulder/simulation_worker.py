"""Background simulation worker for streaming results."""

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import cantera as ct

from .verbose_utils import get_verbose_logger

logger = get_verbose_logger(__name__)


@dataclass
class SimulationProgress:
    """Container for simulation progress and partial results."""

    # Simulation state
    is_running: bool = False
    is_complete: bool = False
    current_time: float = 0.0
    total_time: float = 10.0
    error_message: Optional[str] = None

    # Results data
    times: List[float] = field(default_factory=list)
    reactors_series: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    sol_arrays: Dict[str, ct.SolutionArray] = field(default_factory=dict)

    # Network info
    network: Optional[ct.ReactorNet] = None
    reactors_dict: Dict[str, ct.Reactor] = field(default_factory=dict)

    # Metadata
    mechanism: str = ""
    code_str: str = ""
    reactor_reports: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class SimulationWorker:
    """Background worker for running Cantera simulations with streaming updates."""

    def __init__(self):
        self.progress = SimulationProgress()
        self._lock = threading.RLock()  # Reentrant lock for nested access
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start_simulation(
        self,
        converter,
        config: Dict[str, Any],
        simulation_time: float = 10.0,
        time_step: float = 1.0,
    ) -> None:
        """Start background simulation with streaming updates."""
        # Stop any existing simulation
        self.stop_simulation()

        # Reset progress
        with self._lock:
            self.progress = SimulationProgress()
            self.progress.total_time = simulation_time
            self.progress.is_running = True

        # Start worker thread
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._run_simulation_worker,
            args=(converter, config, simulation_time, time_step),
            daemon=True,
        )
        self._worker_thread.start()

    def stop_simulation(self) -> None:
        """Stop the background simulation."""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)  # Wait up to 2 seconds

    def get_progress(self) -> SimulationProgress:
        """Get current simulation progress (thread-safe)."""
        with self._lock:
            # Return a copy to avoid race conditions
            return SimulationProgress(
                is_running=self.progress.is_running,
                is_complete=self.progress.is_complete,
                current_time=self.progress.current_time,
                total_time=self.progress.total_time,
                error_message=self.progress.error_message,
                times=self.progress.times.copy(),
                reactors_series={
                    rid: {
                        "T": series["T"].copy(),
                        "P": series["P"].copy(),
                        "X": {s: conc.copy() for s, conc in series["X"].items()},
                    }
                    for rid, series in self.progress.reactors_series.items()
                },
                network=self.progress.network,
                reactors_dict=self.progress.reactors_dict,
                mechanism=self.progress.mechanism,
                code_str=self.progress.code_str,
                reactor_reports=self.progress.reactor_reports.copy(),
            )

    def _run_simulation_worker(
        self,
        converter,
        config: Dict[str, Any],
        simulation_time: float,
        time_step: float,
    ) -> None:
        """Background worker function that runs the actual simulation."""
        try:
            # Build network
            logger.info("Building Cantera network in background...")

            if hasattr(converter, "build_network_and_code"):
                # DualCanteraConverter
                network, initial_results, code_str = converter.build_network_and_code(
                    config
                )
            else:
                # Regular CanteraConverter
                network, initial_results = converter.build_network(config)
                code_str = ""

            # Update progress with initial setup
            with self._lock:
                self.progress.network = network
                self.progress.reactors_dict = converter.reactors
                self.progress.mechanism = converter.mechanism
                self.progress.code_str = code_str

                # Initialize reactor series
                reactor_list = [
                    r
                    for r in converter.reactors.values()
                    if not isinstance(r, ct.Reservoir)
                ]

                for reactor in reactor_list:
                    reactor_id = getattr(reactor, "name", "") or str(id(reactor))
                    self.progress.sol_arrays[reactor_id] = ct.SolutionArray(
                        converter.gas, shape=(0,)
                    )
                    self.progress.reactors_series[reactor_id] = {
                        "T": [],
                        "P": [],
                        "X": {s: [] for s in converter.gas.species_names},
                    }

            logger.info(
                f"Starting simulation loop (0 to {simulation_time}s, step={time_step}s)"
            )

            # Run simulation with streaming updates
            num_steps = int(simulation_time / time_step)
            for step in range(num_steps):
                if self._stop_event.is_set():
                    logger.info("Simulation stopped by user")
                    break

                t = step * time_step

                try:
                    # Advance simulation
                    network.advance(t)

                    # Update progress with new data
                    with self._lock:
                        self.progress.current_time = t
                        self.progress.times.append(t)

                        # Capture reactor states
                        for reactor in reactor_list:
                            reactor_id = getattr(reactor, "name", "") or str(
                                id(reactor)
                            )
                            T = reactor.thermo.T
                            P = reactor.thermo.P
                            X_vec = reactor.thermo.X

                            # Check for non-finite states
                            if not (
                                math.isfinite(T)
                                and math.isfinite(P)
                                and all(math.isfinite(float(x)) for x in X_vec)
                            ):
                                logger.warning(
                                    f"Non-finite state at t={t}s for reactor '{reactor_id}'"
                                )
                                # Use last valid state or defaults
                                if self.progress.reactors_series[reactor_id]["T"]:
                                    T = self.progress.reactors_series[reactor_id]["T"][
                                        -1
                                    ]
                                    P = self.progress.reactors_series[reactor_id]["P"][
                                        -1
                                    ]
                                    X_vec = [
                                        self.progress.reactors_series[reactor_id]["X"][
                                            s
                                        ][-1]
                                        for s in converter.gas.species_names
                                    ]
                                else:
                                    T, P = 300.0, 101325.0
                                    X_vec = [0.0] * len(converter.gas.species_names)

                            # Store data
                            self.progress.sol_arrays[reactor_id].append(
                                T=T, P=P, X=X_vec
                            )
                            self.progress.reactors_series[reactor_id]["T"].append(T)
                            self.progress.reactors_series[reactor_id]["P"].append(P)

                            for species_name, x_value in zip(
                                converter.gas.species_names, X_vec
                            ):
                                self.progress.reactors_series[reactor_id]["X"][
                                    species_name
                                ].append(float(x_value))

                    logger.debug(f"Completed time step t={t}s")

                except Exception as e:
                    logger.warning(f"Error at t={t}s: {e}")

                    with self._lock:
                        self.progress.error_message = f"Error at t={t}s: {str(e)}"
                        self.progress.current_time = t

                        # Still add the time point with last valid data
                        if self.progress.times:
                            self.progress.times.append(t)
                            # Duplicate last successful values for all reactors
                            for reactor in reactor_list:
                                reactor_id = getattr(reactor, "name", "") or str(
                                    id(reactor)
                                )
                                if self.progress.reactors_series[reactor_id]["T"]:
                                    last_T = self.progress.reactors_series[reactor_id][
                                        "T"
                                    ][-1]
                                    last_P = self.progress.reactors_series[reactor_id][
                                        "P"
                                    ][-1]
                                    last_X = [
                                        self.progress.reactors_series[reactor_id]["X"][
                                            s
                                        ][-1]
                                        for s in converter.gas.species_names
                                    ]

                                    self.progress.sol_arrays[reactor_id].append(
                                        T=last_T, P=last_P, X=last_X
                                    )
                                    self.progress.reactors_series[reactor_id][
                                        "T"
                                    ].append(last_T)
                                    self.progress.reactors_series[reactor_id][
                                        "P"
                                    ].append(last_P)

                                    for species_name, x_value in zip(
                                        converter.gas.species_names, last_X
                                    ):
                                        self.progress.reactors_series[reactor_id]["X"][
                                            species_name
                                        ].append(float(x_value))

                    # Continue simulation despite error
                    continue

                # Small delay to prevent overwhelming the UI
                time.sleep(0.01)

            # Generate reactor reports
            try:
                reactor_reports = {}
                for reactor_id, reactor in converter.reactors.items():
                    try:
                        thermo_report = reactor.thermo.report(threshold=1e-7)
                    except Exception:
                        thermo_report = ""

                    reactor_reports[reactor_id] = {
                        "reactor_report": str(reactor),
                        "thermo_report": thermo_report,
                    }

                with self._lock:
                    self.progress.reactor_reports = reactor_reports
            except Exception as e:
                logger.warning(f"Error generating reactor reports: {e}")

            # Mark completion
            with self._lock:
                self.progress.is_complete = True
                self.progress.is_running = False

            logger.info("Background simulation completed successfully")

        except Exception as e:
            logger.error(f"Fatal error in simulation worker: {e}", exc_info=True)
            with self._lock:
                self.progress.error_message = f"Fatal error: {str(e)}"
                self.progress.is_running = False
                self.progress.is_complete = True


# Global worker instance
_global_worker: Optional[SimulationWorker] = None


def get_simulation_worker() -> SimulationWorker:
    """Get the global simulation worker instance."""
    global _global_worker
    if _global_worker is None:
        _global_worker = SimulationWorker()
    return _global_worker
