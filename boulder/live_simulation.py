"""Global singleton for storing live Cantera simulation objects.

This module provides a simple way to store and access live Cantera objects
without serialization issues in Dash callbacks.
"""

from threading import RLock
from typing import Dict, Optional

import cantera as ct


class LiveSimulation:
    """Singleton to store live Cantera simulation objects."""

    def __init__(self):
        self._lock = RLock()
        self._network: Optional[ct.ReactorNet] = None
        self._reactors: Dict[str, ct.Reactor] = {}
        self._mechanism: str = ""
        self._available: bool = False

    def update(
        self, network: ct.ReactorNet, reactors: Dict[str, ct.Reactor], mechanism: str
    ) -> None:
        """Update the stored simulation objects."""
        with self._lock:
            self._network = network
            self._reactors = reactors.copy()
            self._mechanism = mechanism
            self._available = True

    def clear(self) -> None:
        """Clear stored objects."""
        with self._lock:
            self._network = None
            self._reactors = {}
            self._mechanism = ""
            self._available = False

    def get_network(self) -> Optional[ct.ReactorNet]:
        """Get the stored network."""
        with self._lock:
            return self._network

    def get_reactors(self) -> Dict[str, ct.Reactor]:
        """Get the stored reactors."""
        with self._lock:
            return self._reactors.copy()

    def get_mechanism(self) -> str:
        """Get the stored mechanism."""
        with self._lock:
            return self._mechanism

    def is_available(self) -> bool:
        """Check if live simulation data is available."""
        with self._lock:
            return self._available and self._network is not None


# Global singleton instance
_live_simulation = LiveSimulation()


def get_live_simulation() -> LiveSimulation:
    """Get the global live simulation instance."""
    return _live_simulation


def update_live_simulation(
    network: ct.ReactorNet, reactors: Dict[str, ct.Reactor], mechanism: str
) -> None:
    """Update the global live simulation objects."""
    _live_simulation.update(network, reactors, mechanism)


def clear_live_simulation() -> None:
    """Clear the global live simulation objects."""
    _live_simulation.clear()


def is_live_simulation_available() -> bool:
    """Check if live simulation data is available."""
    return _live_simulation.is_available()
