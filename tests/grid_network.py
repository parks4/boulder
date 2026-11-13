"""Generate a large cyclic STONE network on a regular grid (test helper).

``grid_network(nx, ny)`` returns the STONE config of an ``nx`` x ``ny`` grid of
well-mixed reactors, the shape of a compartment network derived from a flow
field: every reactor carries an absolute canvas position
(``metadata.layout_position``), flow runs along x, each row recirculates from
its last column back to its first (cycles), and neighbours exchange mass
through pairs of equal and opposite ``MassFlowController`` s. Every rate is
explicit and each reactor is mass-balanced, so the network needs no flow
resolution.

Run as a script to write the YAML::

    python tests/grid_network.py 30 40 grid_30x40.yaml [--no-positions]
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List

from boulder.config import STONE_FORMAT_VERSION

FEED_PER_ROW = 1.0e-3  # kg/s entering each row
RECIRCULATION = 0.5e-3  # kg/s sent back from the last column to the first
EXCHANGE = 0.2e-3  # kg/s each way between neighbours
SPACING = 160  # canvas units between grid points


def _rid(i: int, j: int) -> str:
    return f"r_{i}_{j}"


def _mfc(cid: str, source: str, target: str, rate: float) -> Dict[str, Any]:
    return {
        "id": cid,
        "MassFlowController": {"mass_flow_rate": rate},
        "source": source,
        "target": target,
    }


def grid_network(nx: int, ny: int, positions: bool = True) -> Dict[str, Any]:
    """Return the STONE config of an ``nx`` x ``ny`` cyclic grid network on gri30.

    ``positions=False`` leaves out ``metadata.layout_position`` (automatic layout).
    """
    network: List[Dict[str, Any]] = [
        {
            "id": "feed",
            "Reservoir": {
                "temperature": 300.0,
                "pressure": 101325.0,
                "composition": "O2:0.21, N2:0.79",
            },
            "metadata": {
                "layout_position": {"x": -SPACING, "y": (ny - 1) * SPACING / 2}
            },
        }
    ]
    for i in range(nx):
        for j in range(ny):
            network.append(
                {
                    "id": _rid(i, j),
                    "IdealGasConstPressureMoleReactor": {
                        "energy": "off",
                        "clone": False,
                        "volume": 1.0e-4,
                        "initial": {
                            "temperature": 300.0 + 5.0 * i,
                            "pressure": 101325.0,
                            "composition": "O2:0.21, N2:0.79",
                        },
                    },
                    "metadata": {
                        "layout_position": {"x": i * SPACING, "y": j * SPACING}
                    },
                }
            )
    network.append(
        {
            "id": "exhaust",
            "OutletSink": {},
            "metadata": {
                "layout_position": {"x": nx * SPACING, "y": (ny - 1) * SPACING / 2}
            },
        }
    )
    through = FEED_PER_ROW + RECIRCULATION
    for j in range(ny):
        network.append(_mfc(f"feed_{j}", "feed", _rid(0, j), FEED_PER_ROW))
        for i in range(nx - 1):
            network.append(_mfc(f"fwd_{i}_{j}", _rid(i, j), _rid(i + 1, j), through))
        network.append(_mfc(f"recirc_{j}", _rid(nx - 1, j), _rid(0, j), RECIRCULATION))
        network.append(_mfc(f"exit_{j}", _rid(nx - 1, j), "exhaust", FEED_PER_ROW))
    for i in range(nx):
        for j in range(ny):
            for di, dj in ((1, 0), (0, 1)):
                if i + di >= nx or j + dj >= ny:
                    continue
                a, b = _rid(i, j), _rid(i + di, j + dj)
                network.append(_mfc(f"x_{a}_{b}", a, b, EXCHANGE))
                network.append(_mfc(f"x_{b}_{a}", b, a, EXCHANGE))
    if not positions:
        for item in network:
            item.pop("metadata", None)
    return {
        "metadata": {
            "stone_version": STONE_FORMAT_VERSION,
            "title": f"Cyclic grid network {nx}x{ny}",
        },
        "phases": {"gas": {"mechanism": "gri30.yaml"}},
        "settings": {
            "solver": {
                "kind": "advance",
                "advance_time": 1.0e-3,
                "use_preconditioner": True,
            }
        },
        "network": network,
    }


if __name__ == "__main__":
    from ruamel.yaml import YAML

    nx, ny, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    with open(out, "w", encoding="utf-8") as f:
        YAML().dump(grid_network(nx, ny, positions="--no-positions" not in sys.argv), f)
