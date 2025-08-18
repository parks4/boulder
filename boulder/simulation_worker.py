"""Background simulation worker for streaming updates."""

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import cantera as ct  # type: ignore

from .verbose_utils import get_verbose_logger

logger = get_verbose_logger(__name__)


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

    # Status flags
    is_running: bool = False
    is_complete: bool = False
    error_message: Optional[str] = None


class SimulationWorker:
    """Background worker for running Cantera simulations with streaming updates."""

    def __init__(self):
        self.progress = SimulationProgress()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

    def start_simulation(
        self,
        converter: Any,
        config: Dict[str, Any],
        simulation_time: float = 10.0,
        time_step: float = 1.0,
    ) -> None:
        """Start a background simulation."""
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
                reactors_series={
                    k: {
                        "T": v["T"].copy(),
                        "P": v["P"].copy(),
                        "X": {s: v["X"][s].copy() for s in v["X"]},
                    }
                    for k, v in self.progress.reactors_series.items()
                },
                code_str=self.progress.code_str,
                reactor_reports=self.progress.reactor_reports.copy(),
                is_running=self.progress.is_running,
                is_complete=self.progress.is_complete,
                error_message=self.progress.error_message,
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
            # Build network using the unified converter
            logger.info("Building Cantera network in background...")

            # Build the network first
            network = converter.build_network(config)
            logger.info("Network built successfully, starting streaming simulation...")

            # Define progress callback for streaming updates
            def progress_callback(progress_data, current_time, total_time):
                """Update progress during simulation."""
                if self._stop_event.is_set():
                    return  # Don't update if stopping

                with self._lock:
                    self.progress.times = progress_data["time"]
                    self.progress.reactors_series = progress_data["reactors"]
                    # Calculate progress percentage
                    progress_pct = (
                        (current_time / total_time) * 100 if total_time > 0 else 0
                    )
                    logger.debug(
                        f"Simulation progress: {progress_pct:.1f}% (t={current_time:.1f}s)"
                    )

            # Initialize progress
            with self._lock:
                self.progress.network = network
                self.progress.reactors_dict = converter.reactors
                self.progress.mechanism = converter.mechanism
                self.progress.times = []
                self.progress.reactors_series = {}
                self.progress.code_str = ""
                self.progress.reactor_reports = {}
                self.progress.is_running = True
                self.progress.is_complete = False
                self.progress.error_message = None

            logger.info(
                f"Starting streaming simulation: {simulation_time}s with {time_step}s steps"
            )

            # Run the streaming simulation using the converter's method
            results, code_str = converter.run_streaming_simulation(
                simulation_time=simulation_time,
                time_step=time_step,
                progress_callback=progress_callback,
            )

            # Finalize results
            logger.info(f"Simulation completed: {len(results['time'])} time points")
            with self._lock:
                self.progress.times = results["time"]
                self.progress.reactors_series = results["reactors"]
                self.progress.code_str = code_str
                # Generate reactor reports for thermo analysis
                self.progress.reactor_reports = self._generate_reactor_reports(
                    converter, results
                )
                self.progress.is_running = False
                self.progress.is_complete = True

        except Exception as e:
            logger.error(f"Simulation failed: {e}", exc_info=True)
            with self._lock:
                self.progress.error_message = str(e)
                self.progress.is_running = False
                self.progress.is_complete = False

    def _generate_reactor_reports(
        self, converter: Any, results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate reactor reports for thermo analysis."""
        reactor_reports = {}

        try:
            # Generate reports for each reactor
            for reactor_id, reactor in converter.reactors.items():
                if isinstance(reactor, ct.Reservoir):
                    continue  # Skip reservoirs

                # Get final state data
                if reactor_id in results["reactors"]:
                    reactor_data = results["reactors"][reactor_id]
                    if reactor_data["T"] and reactor_data["P"]:
                        # Use final state
                        final_T = reactor_data["T"][-1]
                        final_P = reactor_data["P"][-1]
                        final_X = {
                            s: reactor_data["X"][s][-1] for s in reactor_data["X"]
                        }

                        # Set gas state to final conditions
                        converter.gas.TPX = final_T, final_P, list(final_X.values())

                        # Generate thermo report
                        reactor_reports[reactor_id] = {
                            "T": final_T,
                            "P": final_P,
                            "X": final_X,
                            "species_names": converter.gas.species_names,
                            "molecular_weights": converter.gas.molecular_weights,
                            "mass_fractions": converter.gas.Y.copy(),
                        }

        except Exception as e:
            logger.warning(f"Failed to generate reactor reports: {e}")

        return reactor_reports


# Global worker instance
_global_worker: Optional[SimulationWorker] = None


def get_simulation_worker() -> SimulationWorker:
    """Get the global simulation worker instance."""
    global _global_worker
    if _global_worker is None:
        _global_worker = SimulationWorker()
    return _global_worker
