"""Tests for the resolve_unset_flow_rates mass-conservation utility."""

import cantera as ct
import pytest

from boulder.cantera_converter import resolve_unset_flow_rates


def _simple_gas() -> ct.Solution:
    gas = ct.Solution("gri30.yaml")
    gas.TPX = 300.0, 101325.0, "N2:1"
    return gas


# ---------------------------------------------------------------------------
# Helpers to build minimal Cantera networks without advancing them
# ---------------------------------------------------------------------------


def _build_series_network(mdot_inlet: float, n_reactors: int = 2):
    """Build: Reservoir --[inlet:mdot_inlet]--> R1 --> ... --> Rn --> Reservoir.

    Returns (mfc_topology, flow_rates, mfc_objects, reactors, unresolved_ids).
    The single inlet MFC has mass_flow_rate set; all others are unresolved.
    """
    gas = _simple_gas()
    res_in = ct.Reservoir(gas, name="res_in")
    res_out = ct.Reservoir(gas, name="res_out")
    reactors: dict = {"res_in": res_in, "res_out": res_out}
    for i in range(1, n_reactors + 1):
        r = ct.IdealGasReactor(gas, name=f"R{i}")
        reactors[f"R{i}"] = r

    mfc_topology: dict = {}
    flow_rates: dict = {}
    mfc_objects: dict = {}
    unresolved_ids: set = set()

    # Inlet MFC (known flow)
    mfc_in = ct.MassFlowController(res_in, reactors["R1"])
    mfc_in.mass_flow_rate = mdot_inlet
    mfc_topology["inlet"] = ("res_in", "R1")
    flow_rates["inlet"] = mdot_inlet
    mfc_objects["inlet"] = mfc_in

    # Internal and outlet MFCs (unresolved)
    for i in range(1, n_reactors + 1):
        src = f"R{i}"
        tgt = f"R{i + 1}" if i < n_reactors else "res_out"
        cid = f"mfc_{i}"
        mfc = ct.MassFlowController(reactors[src], reactors[tgt])
        mfc.mass_flow_rate = 0.0  # placeholder; will be resolved
        mfc_topology[cid] = (src, tgt)
        mfc_objects[cid] = mfc
        unresolved_ids.add(cid)

    return mfc_topology, flow_rates, mfc_objects, reactors, unresolved_ids


class TestResolveUnsetFlowRates:
    """Unit tests for resolve_unset_flow_rates."""

    @pytest.mark.unit
    def test_series_single_reactor(self):
        """Propagate a known inlet flow through one unset downstream MFC.

        Asserts:
        1. The resolved entry in flow_rates equals the inlet flow rate.
        2. unresolved_ids is empty after the call.
        """
        mdot = 5.0
        topology, flow_rates, mfcs, reactors, unresolved = _build_series_network(
            mdot, n_reactors=1
        )

        resolve_unset_flow_rates(topology, flow_rates, mfcs, reactors, unresolved)

        assert flow_rates["mfc_1"] == pytest.approx(mdot)
        assert len(unresolved) == 0

    @pytest.mark.unit
    def test_series_two_reactors(self):
        """Propagate inlet flow through two consecutive unset MFCs.

        Asserts:
        1. Both downstream MFCs receive exactly the inlet flow rate in flow_rates.
        2. unresolved_ids is empty after the call.
        """
        mdot = 3.7
        topology, flow_rates, mfcs, reactors, unresolved = _build_series_network(
            mdot, n_reactors=2
        )

        resolve_unset_flow_rates(topology, flow_rates, mfcs, reactors, unresolved)

        assert flow_rates["mfc_1"] == pytest.approx(mdot)
        assert flow_rates["mfc_2"] == pytest.approx(mdot)
        assert len(unresolved) == 0

    @pytest.mark.unit
    def test_junction_merging_two_inlets(self):
        """Two known inlets merge into one reactor; single unset outlet resolved.

        Asserts:
        1. flow_rates['out'] equals the sum of the two inlet flows.
        2. unresolved_ids is empty after the call.
        """
        gas = _simple_gas()
        res_a = ct.Reservoir(gas, name="res_a")
        res_b = ct.Reservoir(gas, name="res_b")
        res_out = ct.Reservoir(gas, name="res_out")
        r1 = ct.IdealGasReactor(gas, name="R1")

        reactors = {"res_a": res_a, "res_b": res_b, "res_out": res_out, "R1": r1}

        mfc_a = ct.MassFlowController(res_a, r1)
        mfc_a.mass_flow_rate = 4.0
        mfc_b = ct.MassFlowController(res_b, r1)
        mfc_b.mass_flow_rate = 6.0
        mfc_out = ct.MassFlowController(r1, res_out)
        mfc_out.mass_flow_rate = 0.0  # unresolved

        topology = {
            "a": ("res_a", "R1"),
            "b": ("res_b", "R1"),
            "out": ("R1", "res_out"),
        }
        flow_rates = {"a": 4.0, "b": 6.0}
        mfcs = {"a": mfc_a, "b": mfc_b, "out": mfc_out}
        unresolved = {"out"}

        resolve_unset_flow_rates(topology, flow_rates, mfcs, reactors, unresolved)

        assert flow_rates["out"] == pytest.approx(10.0)
        assert len(unresolved) == 0

    @pytest.mark.unit
    def test_ambiguous_split_raises_error(self):
        """Two unset outlet MFCs on the same reactor cannot be resolved.

        Asserts:
        ValueError is raised when the system is underdetermined (two unknowns
        at one node, with no other nodes that can break the symmetry).
        """
        gas = _simple_gas()
        res_in = ct.Reservoir(gas, name="res_in")
        res_a = ct.Reservoir(gas, name="res_a")
        res_b = ct.Reservoir(gas, name="res_b")
        r1 = ct.IdealGasReactor(gas, name="R1")

        reactors = {"res_in": res_in, "res_a": res_a, "res_b": res_b, "R1": r1}

        mfc_in = ct.MassFlowController(res_in, r1)
        mfc_in.mass_flow_rate = 10.0
        mfc_out_a = ct.MassFlowController(r1, res_a)
        mfc_out_a.mass_flow_rate = 0.0
        mfc_out_b = ct.MassFlowController(r1, res_b)
        mfc_out_b.mass_flow_rate = 0.0

        topology = {
            "in": ("res_in", "R1"),
            "out_a": ("R1", "res_a"),
            "out_b": ("R1", "res_b"),
        }
        flow_rates = {"in": 10.0}
        mfcs = {"in": mfc_in, "out_a": mfc_out_a, "out_b": mfc_out_b}
        unresolved = {"out_a", "out_b"}

        with pytest.raises(ValueError, match="Cannot determine mass flow rate"):
            resolve_unset_flow_rates(topology, flow_rates, mfcs, reactors, unresolved)

    @pytest.mark.unit
    def test_negative_resolved_flow_raises_error(self):
        """Conservation that yields a negative flow raises a clear ValueError.

        Asserts:
        ValueError is raised and its message mentions 'negative flow rate'
        when the sum of known outgoing flows (8.0) exceeds the sum of known
        incoming flows (3.0), leaving the one unset outgoing MFC with a
        required rate of 3.0 - 8.0 = -5.0 kg/s.
        """
        gas = _simple_gas()
        res_in = ct.Reservoir(gas, name="res_in")
        res_out_a = ct.Reservoir(gas, name="res_out_a")
        res_out_b = ct.Reservoir(gas, name="res_out_b")
        r1 = ct.IdealGasReactor(gas, name="R1")

        reactors = {
            "res_in": res_in,
            "res_out_a": res_out_a,
            "res_out_b": res_out_b,
            "R1": r1,
        }

        # Known inlet: 3 kg/s — known outlet_a: 8 kg/s — unresolved outlet_b
        # Conservation: outlet_b = 3 - 8 = -5  →  must raise
        mfc_in = ct.MassFlowController(res_in, r1)
        mfc_in.mass_flow_rate = 3.0
        mfc_out_a = ct.MassFlowController(r1, res_out_a)
        mfc_out_a.mass_flow_rate = 8.0
        mfc_out_b = ct.MassFlowController(r1, res_out_b)
        mfc_out_b.mass_flow_rate = 0.0  # unresolved

        topology = {
            "in": ("res_in", "R1"),
            "out_a": ("R1", "res_out_a"),
            "out_b": ("R1", "res_out_b"),
        }
        flow_rates = {"in": 3.0, "out_a": 8.0}
        mfcs = {"in": mfc_in, "out_a": mfc_out_a, "out_b": mfc_out_b}
        unresolved = {"out_b"}

        with pytest.raises(ValueError, match="negative flow rate"):
            resolve_unset_flow_rates(topology, flow_rates, mfcs, reactors, unresolved)

    @pytest.mark.unit
    def test_all_flows_known_noop(self):
        """Calling with an empty unresolved set performs no modifications.

        Asserts:
        1. No exception is raised.
        2. flow_rates dict is unchanged.
        """
        gas = _simple_gas()
        res_in = ct.Reservoir(gas, name="res_in")
        res_out = ct.Reservoir(gas, name="res_out")
        r1 = ct.IdealGasReactor(gas, name="R1")

        reactors = {"res_in": res_in, "res_out": res_out, "R1": r1}

        mfc = ct.MassFlowController(res_in, r1)
        mfc.mass_flow_rate = 7.5
        mfc2 = ct.MassFlowController(r1, res_out)
        mfc2.mass_flow_rate = 7.5

        topology = {"mfc": ("res_in", "R1"), "mfc2": ("R1", "res_out")}
        flow_rates = {"mfc": 7.5, "mfc2": 7.5}
        mfcs = {"mfc": mfc, "mfc2": mfc2}
        unresolved: set = set()

        resolve_unset_flow_rates(topology, flow_rates, mfcs, reactors, unresolved)

        assert flow_rates == {"mfc": 7.5, "mfc2": 7.5}
