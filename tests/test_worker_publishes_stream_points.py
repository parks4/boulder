"""What a solve synthesises, the client must receive.

``SimulationWorker`` publishes ``updated_nodes``/``updated_connections`` as the
single source of truth for the client's graph. A staged solve adds one
stream-point reservoir per stage boundary and fills it with converged thermo,
so those nodes must be in what the worker publishes -- otherwise every consumer
of that list (graph, properties panel, output panes) sees a network whose stage
boundaries do not exist.

The trap: ``build_network`` deep-copies the config it is handed, so the dict the
*caller* holds is never the one the staged solver enriches.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from boulder.cantera_converter import DualCanteraConverter
from boulder.config import normalize_config, validate_config
from boulder.export import points_from_streams
from boulder.simulation_worker import SimulationWorker

sys.path.insert(0, str(Path(__file__).parent))
from test_staged_viz_flow import _two_stage_linear_chain  # noqa: E402


@pytest.mark.slow
def test_updated_nodes_carry_the_stream_points_with_converged_thermo() -> None:
    """A two-stage solve must publish its stream point, not just the declared nodes."""
    cfg = validate_config(normalize_config(_two_stage_linear_chain()))
    declared_ids = {n["id"] for n in cfg["nodes"]}

    worker = SimulationWorker()
    worker.start_simulation(
        DualCanteraConverter(mechanism="gri30.yaml"),
        cfg,
        simulation_time=1e-4,
        time_step=1e-4,
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        if worker.get_progress().is_complete or worker.get_progress().error_message:
            break
        time.sleep(0.2)

    progress = worker.get_progress()
    assert not progress.error_message, progress.error_message
    assert progress.updated_nodes is not None

    published_ids = {n["id"] for n in progress.updated_nodes}
    assert declared_ids <= published_ids
    assert published_ids - declared_ids == {"r_a_outlet"}

    # The published node must carry the converged stream state, not a
    # build-time placeholder: this is what the client renders.
    points = points_from_streams({"nodes": progress.updated_nodes})
    assert [p["id"] for p in points] == ["r_a_outlet"]
    point = points[0]
    assert point["source_node"] == "r_a"
    assert point["target_nodes"] == ["r_b"]
    assert point["T_K"] > 0.0
    assert point["mdot_kg_s"] > 0.0
    assert point["h_mass_J_kg"] != 0.0
