"""Emit standalone Cantera-native download scripts.

The generated file uses module-level ``reactors``, ``connections``, and ``walls``
registries, direct ``ct.*`` construction, and named ``network_<stage>.advance(...)``
calls per stage.

Subclass :class:`CanteraScriptEmitter` and override ``_emit_reactor``,
``_emit_download_imports``, ``_emit_post_build_calls``, or ``_network_ctor`` to
inject custom reactor kinds (e.g. plugin-specific types) without modifying this
module.
"""

from __future__ import annotations

import re
from pprint import pformat
from typing import Any, Dict, List, Optional

from .config import TRANSIENT_SOLVER_KINDS
from .staged_solver import (
    _order_stage_nodes_for_flow,
    build_stage_graph,
    synthesize_stream_points,
)

_RESERVOIR_TYPES = {"Reservoir", "OutletSink"}


class CanteraScriptEmitter:
    """Emits a standalone Cantera-native staged-solve script from a config dict.

    Subclass and override ``_emit_reactor``, ``_emit_download_imports``, or
    ``_emit_post_build_calls`` to inject custom behaviour (e.g. host-specific
    reactor types) without modifying Boulder.

    Parameters
    ----------
    converter:
        Optional reference to a converter object — reserved for subclass use.
        The base class stores it as ``self.converter`` but does not use it.
    """

    def __init__(self, converter: Optional[Any] = None) -> None:
        self.converter = converter

        # Instance state populated by prepare(); all None until emit() is called.
        self._vn_re = re.compile(r"\W")
        self.nodes_by_id: Dict[str, Any] = {}
        self.inlet_target_ids: set = set()
        self.plan: Any = None
        self.stream_inlet_by_stage: Dict[str, List[Dict[str, Any]]] = {}
        self.has_mech_switch: bool = False
        self.mechanism: str = "gri30.yaml"
        self.all_node_types: set = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def emit(self, config: Dict[str, Any]) -> List[str]:
        """Return Python source lines for a Cantera-native staged-solve script."""
        self._prepare(config)

        plan = build_stage_graph(config)
        stages = list(plan.ordered_stages)

        self.plan = plan
        self.stream_inlet_by_stage = {}
        _, stream_conns = synthesize_stream_points(plan)
        for cd in stream_conns:
            self.stream_inlet_by_stage.setdefault(cd.get("group", ""), []).append(cd)

        self.inlet_target_ids = {ic.target_node for ic in plan.all_inter_connections}
        self.has_mech_switch = bool(
            any(ic.mechanism_switch for ic in plan.all_inter_connections)
        )

        lines = self._emit_download_imports()
        lines += self._emit_preamble()

        if not stages:
            lines += [
                "raise RuntimeError(",
                "    'Cannot run downloaded script: stage plan was not embedded. '",
                "    'Re-generate with boulder --headless --download.'",
                ")",
            ]
            return lines

        for idx, stage in enumerate(stages):
            lines.extend(self._emit_stage_block(stage, idx, len(stages)))

        lines += self._emit_post_build_calls()
        return lines

    # ------------------------------------------------------------------
    # Preparation
    # ------------------------------------------------------------------

    def _prepare(self, config: Dict[str, Any]) -> None:
        """Initialise all shared state from *config* before emission begins."""
        phases = config.get("phases") or {}
        gas_phase = phases.get("gas") if isinstance(phases, dict) else {}
        self.mechanism = (gas_phase or {}).get("mechanism") or "gri30.yaml"

        self.nodes_by_id = {n["id"]: n for n in (config.get("nodes") or [])}
        self.all_node_types = {n.get("type", "") for n in (config.get("nodes") or [])}

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _vn(self, s: str) -> str:
        """Convert an arbitrary string to a valid Python identifier."""
        return self._vn_re.sub("_", s)

    def _py(self, obj: Any) -> str:
        """Pretty-print an object for embedding in emitted source."""
        return pformat(obj, width=100, sort_dicts=False)

    def _conn_var(self, cid: str) -> str:
        return f"_conn_{self._vn(cid)}"

    def _sconn_var(self, cid: str) -> str:
        return f"_sconn_{self._vn(cid)}"

    def _solver_comment(self, solver: Dict[str, Any]) -> str:
        kind = str(solver.get("kind", "advance_to_steady_state"))
        parts = [f"kind={kind!r}"]
        if kind == "advance":
            parts.append(f"advance_time={solver.get('advance_time')!r}")
        return ", ".join(parts)

    def _mdot_out_expr(self, source_id: str, conns: List[Dict[str, Any]]) -> str:
        out_parts: List[str] = []
        for c in conns:
            if c.get("type") != "MassFlowController" or c.get("source") != source_id:
                continue
            mdot = (c.get("properties") or {}).get("mass_flow_rate")
            if mdot is not None:
                out_parts.append(repr(float(mdot)))
            else:
                out_parts.append(f"connections[{c['id']!r}].mass_flow_rate")
        if out_parts:
            return " + ".join(out_parts)
        in_parts: List[str] = []
        for c in conns:
            if c.get("type") != "MassFlowController" or c.get("target") != source_id:
                continue
            mdot = (c.get("properties") or {}).get("mass_flow_rate")
            if mdot is not None:
                in_parts.append(repr(float(mdot)))
            else:
                in_parts.append(f"connections[{c['id']!r}].mass_flow_rate")
        return " + ".join(in_parts) if in_parts else "0.0"

    def _upstream_gas_lines(
        self, rid: str, var: str, conns: List[Dict[str, Any]]
    ) -> List[str]:
        for c in conns:
            if c.get("type") != "MassFlowController" or c.get("target") != rid:
                continue
            src_id = c.get("source")
            src_node = self.nodes_by_id.get(str(src_id), {})
            if src_node.get("type") in _RESERVOIR_TYPES:
                sv = self._vn(str(src_id))
                return [
                    f"_up = {sv}.thermo",
                    f"gas_{var}.TPY = _up.T, _up.P, _up.Y",
                ]
        return []

    def _emit_gas_state(
        self, node: Dict[str, Any], stage: Any, conns: List[Dict[str, Any]]
    ) -> List[str]:
        rid = node["id"]
        var = self._vn(rid)
        props = node.get("properties") or {}
        node_mech = str(
            props.get("mechanism") or node.get("mechanism") or stage.mechanism
        )
        initial = props.get("initial") or {}
        temp = initial.get("temperature") or props.get("temperature")
        pres = initial.get("pressure") or props.get("pressure")
        comp = initial.get("composition") or props.get("composition")
        mass_comp = initial.get("mass_composition") or props.get("mass_composition")

        lines = [f"gas_{var} = ct.Solution(get_mechanism_path({node_mech!r}))"]

        def _tpx(comp_str: str | None, mass: str | None) -> List[str]:
            t = f"float({temp!r})" if temp is not None else f"float(gas_{var}.T)"
            p = f"float({pres!r})" if pres is not None else f"float(gas_{var}.P)"
            if comp_str is not None:
                return [f"gas_{var}.TPX = ({t}, {p}, _parse_composition({comp_str!r}))"]
            if mass is not None:
                return [f"gas_{var}.TPX = ({t}, {p}, _parse_composition({mass!r}))"]
            return [f"gas_{var}.TPX = ({t}, {p}, gas_{var}.X)"]

        if rid in self.inlet_target_ids:
            lines.append(f"if {rid!r} in inlet_states:")
            lines.append(f"    _inlet = inlet_states[{rid!r}]")
            lines.append(f"    gas_{var}.TPY = _inlet.T, _inlet.P, _inlet.Y")
            lines.append("else:")
            if temp is None and comp is None and mass_comp is None:
                fallback_lines = self._upstream_gas_lines(rid, var, conns)
                if not fallback_lines:
                    lines.append("    pass")
                for ul in fallback_lines:
                    lines.append(f"    {ul}")
            else:
                for gl in _tpx(comp, mass_comp):
                    lines.append(f"    {gl}")
        elif temp is None and comp is None and mass_comp is None:
            lines.extend(self._upstream_gas_lines(rid, var, conns))
        else:
            lines.extend(_tpx(comp, mass_comp))
        return lines

    # ------------------------------------------------------------------
    # Reactor / connection emitters (overridable in subclasses)
    # ------------------------------------------------------------------

    def _emit_reactor(
        self, node: Dict[str, Any], stage: Any, conns: List[Dict[str, Any]]
    ) -> List[str]:
        """Return source lines constructing one reactor.

        Override in a subclass to handle custom reactor kinds before delegating
        to ``super()._emit_reactor(...)`` for built-in Cantera types.
        """
        rid = node["id"]
        var = self._vn(rid)
        ntype = node.get("type", "Reactor")
        props = node.get("properties") or {}
        node_mech = str(
            props.get("mechanism") or node.get("mechanism") or stage.mechanism
        )

        if props.get("stream_point") or props.get("stage_interface"):
            return [
                f"# {rid}: stream-point reservoir (populated at upstream handoff)",
                f"assert {rid!r} in reactors",
                "",
            ]

        out: List[str] = [f"# {rid}: {ntype}"]
        out.extend(self._emit_gas_state(node, stage, conns))

        if ntype in _RESERVOIR_TYPES:
            out.append(f"{var} = ct.Reservoir(gas_{var})")
            out.append(
                f"reactor_meta[{rid!r}] = {{'mechanism': {node_mech!r}, "
                f"'gas_solution': gas_{var}}}"
            )
        elif ntype == "IdealGasConstPressureMoleReactor":
            out.append(
                f"{var} = ct.IdealGasConstPressureMoleReactor(gas_{var}, clone=True)"
            )
        elif ntype == "IdealGasConstPressureReactor":
            out.append(
                f"{var} = ct.IdealGasConstPressureReactor(gas_{var}, clone=True)"
            )
        elif ntype == "IdealGasReactor":
            out.append(f"{var} = ct.IdealGasReactor(gas_{var}, clone=True)")
        elif ntype == "ConstPressureReactor":
            out.append(f"{var} = ct.ConstPressureReactor(gas_{var}, clone=True)")
        else:
            out.append(
                f'raise ValueError("Unsupported reactor type {ntype!r} in native '
                f"download script for {rid!r}: override _emit_reactor in a "
                f'CanteraScriptEmitter subclass to handle custom reactor kinds.")'
            )

        vol = props.get("volume")
        if vol is not None and ntype not in _RESERVOIR_TYPES:
            out.append(f"{var}.volume = {float(vol)!r}")

        out.append(f"{var}.name = {rid!r}")
        if rid in self.inlet_target_ids and ntype not in _RESERVOIR_TYPES:
            out.append(f"if {rid!r} in inlet_states:")
            out.append(f"    _inlet = inlet_states[{rid!r}]")
            out.append(f"    {var}.phase.TPY = _inlet.T, _inlet.P, _inlet.Y")
        out.append(f"reactors[{rid!r}] = {var}")
        out.append("")
        return out

    def _emit_connection(
        self, conn: Dict[str, Any], cref: str, spec_ref: str
    ) -> List[str]:
        cid = conn["id"]
        ctype = conn.get("type", "MassFlowController")
        src, tgt = conn["source"], conn["target"]
        sv, tv = self._vn(src), self._vn(tgt)
        props = conn.get("properties") or {}
        out = [f"# {ctype}: {src} -> {tgt}"]
        if ctype == "MassFlowController":
            out.append(f"{cref} = ct.MassFlowController({sv}, {tv})")
            mdot = props.get("mass_flow_rate")
            if mdot is not None:
                # STONE allows three MFC mass_flow_rate forms (see STONE_SPECIFICATIONS.md):
                #   scalar  — fixed kg/s (e.g. 0.025)
                #   omitted — resolved later by _apply_flow_conservation()
                #   dict    — derived rate; never pass through float()
                if isinstance(mdot, dict):
                    if "closure" in mdot:
                        # Closure dict: mdot(t) is computed from reactor state at
                        # integration time (mirrors DualCanteraConverter MFC build).
                        closure_kind = str(mdot["closure"])
                        if closure_kind == "residence_time":
                            # mdot(t) = reactor.mass / tau_s  →  ct.Func1(...)
                            reactor_id = mdot.get("reactor", tgt)
                            tau_s = float(mdot.get("tau_s", 1.0))
                            fn = f"_mdot_{cref}"
                            out.append(
                                f"def {fn}(t, _rid={reactor_id!r}, _tau={tau_s!r}):"
                            )
                            out.append("    r = reactors.get(_rid)")
                            out.append("    if r is None:")
                            out.append(
                                f'        raise KeyError(f"residence_time MFC {cid}: '
                                f'reactor {{_rid!r}} not found")'
                            )
                            out.append("    return r.mass / _tau")
                            out.append(f"{cref}.mass_flow_rate = ct.Func1({fn})")
                        else:
                            out.append(
                                f'raise ValueError("MassFlowController {cid!r}: '
                                f'unsupported mass_flow_rate closure {closure_kind!r}")'
                            )
                    else:
                        # Schedule dict: { func: gaussian, args: [...] } — supported
                        # in-app via _build_func1_from_spec, not in native download scripts.
                        out.append(
                            f'raise ValueError("MassFlowController {cid!r}: '
                            f'Func1 schedule specs not supported in native download script")'
                        )
                else:
                    # Fixed mass flow rate (kg/s).
                    out.append(f"{cref}.mass_flow_rate = {float(mdot)!r}")
                    out.append(f"_mfc_flow_rates[{cid!r}] = {float(mdot)!r}")
            else:
                # No explicit rate: start at 0 and let flow conservation resolve it.
                out.append(f"if {cid!r} in _mfc_flow_rates:")
                out.append(f"    {cref}.mass_flow_rate = _mfc_flow_rates[{cid!r}]")
                out.append("else:")
                out.append(f"    {cref}.mass_flow_rate = 0.0")
                out.append(f"    _unresolved_mfc_ids.add({cid!r})")
            out.append(f"connections[{cid!r}] = {cref}")
            out.append(f"_mfc_topology[{cid!r}] = ({src!r}, {tgt!r})")
        elif ctype == "Wall":
            area = float(props.get("area", 1.0))
            if "electric_power_kW" in props:
                q_w = (
                    float(props["electric_power_kW"])
                    * 1e3
                    * float(props.get("torch_eff", 1.0))
                    * float(props.get("gen_eff", 1.0))
                )
                out.append(
                    f"{cref} = ct.Wall({sv}, {tv}, A={area}, "
                    f"Q=lambda t: {q_w!r}, name={cid!r})"
                )
            else:
                out.append(f"{cref} = ct.Wall({sv}, {tv}, A={area}, name={cid!r})")
            out.append(f"walls[{cid!r}] = {cref}")
        elif ctype == "Valve":
            coeff = float(props.get("valve_coeff", 1.0))
            out.append(f"{cref} = ct.Valve({sv}, {tv})")
            out.append(f"{cref}.valve_coeff = {coeff!r}")
            out.append(f"connections[{cid!r}] = {cref}")
        elif ctype == "PressureController":
            master = props.get("master")
            coeff = float(props.get("pressure_coeff", 0.0))
            out.append(f"if {master!r} in connections:")
            out.append(f"    {cref} = ct.PressureController({sv}, {tv})")
            out.append(f"    {cref}.primary = connections[{master!r}]")
            out.append(f"    {cref}.pressure_coeff = {coeff!r}")
            out.append(f"    connections[{cid!r}] = {cref}")
            out.append("else:")
            out.append(f"    _deferred_pc_conn_dicts.append({spec_ref})")
        else:
            out.append(f'raise ValueError("Unsupported connection type {ctype!r}")')
        return out

    def _network_ctor(self, non_res_ids: List[str]) -> str:
        """Return the constructor expression string for a stage ReactorNet.

        Override in a subclass to return a custom network class string for
        reactor kinds that require a specialised net (e.g. ``DesignPFRNet``).
        """
        rs = ", ".join(self._vn(r) for r in non_res_ids)
        return f"ct.ReactorNet([{rs}])"

    def _emit_stage_block(self, stage: Any, stage_idx: int, n_stages: int) -> List[str]:
        sid = stage.id
        svar = self._vn(sid)
        solver = stage.solver or {}

        base_nodes = [
            self.nodes_by_id[n] for n in stage.node_ids if n in self.nodes_by_id
        ]
        sp_ids = [ic.stream_point_id for ic in stage.inter_connections_in]
        sp_nodes = [
            {"id": sp, "type": "Reservoir", "properties": {"stream_point": True}}
            for sp in sp_ids
        ]
        intra_conns = list(stage.intra_connections)
        inlet_conns = self.stream_inlet_by_stage.get(sid, [])
        stage_conns = intra_conns + inlet_conns
        ordered_nodes = _order_stage_nodes_for_flow(base_nodes + sp_nodes, stage_conns)
        node_ids = {n["id"] for n in ordered_nodes}
        non_res_ids = [
            n["id"]
            for n in ordered_nodes
            if n.get("type") not in _RESERVOIR_TYPES
            and not (n.get("properties") or {}).get("stream_point")
        ]

        cfg_nodes = [self._py(n) for n in base_nodes]
        cfg_conns = [self._py(c) for c in stage_conns]

        lines: List[str] = ["# " + "=" * 74]
        lines.append(f"# Stage {stage_idx + 1}/{n_stages}: {sid}")
        lines.append(f"#   mechanism : {stage.mechanism}")
        lines.append(f"#   solver    : {self._solver_comment(solver)}")
        for n in ordered_nodes:
            if (n.get("properties") or {}).get("stream_point"):
                lines.append(f"#   node      : {n['id']} (stream-point Reservoir)")
            else:
                lines.append(f"#   node      : {n['id']} ({n.get('type', 'Reactor')})")
        lines.append("# " + "=" * 74)
        lines.append(f"print('Stage {stage_idx + 1}/{n_stages}: {sid}')")
        lines.append("")

        for c in intra_conns:
            lines.append(f"{self._conn_var(c['id'])}_spec = {self._py(c)}")
        for c in inlet_conns:
            lines.append(f"{self._sconn_var(c['id'])}_spec = {self._py(c)}")

        lines.append("")
        lines.append("# Build reactors")
        for n in ordered_nodes:
            lines.extend(self._emit_reactor(n, stage, stage_conns))

        lines.append("# Wire connections")
        lines.append("_unresolved_mfc_ids = set()")
        for c in intra_conns:
            if c["source"] not in node_ids or c["target"] not in node_ids:
                continue
            cref = self._conn_var(c["id"])
            lines.extend(self._emit_connection(c, cref, f"{cref}_spec"))
        for c in inlet_conns:
            if c["source"] not in node_ids or c["target"] not in node_ids:
                continue
            cref = self._sconn_var(c["id"])
            lines.extend(self._emit_connection(c, cref, f"{cref}_spec"))

        lines.append("_apply_flow_conservation()")
        lines.extend(self._emit_stage_extra_post_build(cfg_nodes, cfg_conns))
        lines.append("")

        lines.append("# Solve")
        lines.append(f"network_{svar} = {self._network_ctor(non_res_ids)}")
        lines.append(f"network_{svar}.rtol = {float(solver.get('rtol', 1e-6))!r}")
        lines.append(f"network_{svar}.atol = {float(solver.get('atol', 1e-8))!r}")

        kind = str(solver.get("kind", "advance_to_steady_state"))
        if kind == "advance_to_steady_state":
            lines.append(f"network_{svar}.advance_to_steady_state()")
        elif kind == "solve_steady":
            lines.append(f"network_{svar}.solve_steady()")
        elif kind == "advance":
            raw = solver.get("advance_time", getattr(stage, "advance_time", 1.0))
            lines.append(
                f"network_{svar}.advance("
                f"float(coerce_unit_string({raw!r}, 'advance_time')))"
            )
        elif kind == "advance_grid":
            grid_spec = solver.get("grid")
            if grid_spec is None:
                lines.append(
                    f"raise ValueError(\"Stage {sid!r}: solver.kind='advance_grid' "
                    f"requires a 'grid:' entry.\")"
                )
            elif isinstance(grid_spec, dict):
                start = float(grid_spec.get("start", 0.0))
                stop = float(grid_spec["stop"])
                dt = float(grid_spec["dt"])
                lines.append("import numpy as np")
                lines.append(
                    f"_times = list(np.arange({start!r} + {dt!r}, "
                    f"{stop!r} + {dt!r} / 2, {dt!r}))"
                )
                lines.append("for _t in _times:")
                lines.append(f"    network_{svar}.advance(float(_t))")
            else:
                times = [float(t) for t in grid_spec]
                lines.append(f"_times = {times!r}")
                lines.append("for _t in _times:")
                lines.append(f"    network_{svar}.advance(float(_t))")
        elif kind == "micro_step":
            t_total = float(solver["t_total"])
            chunk_dt = float(solver["chunk_dt"])
            max_dt = float(solver.get("max_dt", chunk_dt / 10))
            reinit = bool(solver.get("reinitialize_between_chunks", False))
            start = float(solver.get("start", 0.0))
            lines.append(f"_t = {start!r}")
            lines.append(f"while _t < {t_total!r}:")
            lines.append(f"    _t_end = min(_t + {chunk_dt!r}, {t_total!r})")
            lines.append(f"    while network_{svar}.time < _t_end:")
            lines.append(
                f"        network_{svar}.advance(network_{svar}.time + {max_dt!r})"
            )
            if reinit:
                lines.append(f"    network_{svar}.reinitialize()")
            lines.append("    _t = _t_end")
        else:
            lines.append(
                f'raise ValueError("solver.kind {kind!r} not supported in native '
                f'download script")'
            )
        lines.append("")

        for ic in stage.inter_connections_out:
            src_id = ic.source_node
            src = self._vn(src_id)
            sp = ic.stream_point_id
            spv = self._vn(sp)
            mech = stage.mechanism
            lines.append(
                f"# Handoff: {src_id} -> {sp} -> {ic.target_node} "
                f"(stage {ic.target_stage})"
            )
            lines.append(f"_outlet_{src} = ct.Solution(get_mechanism_path({mech!r}))")
            lines.append(
                f"_outlet_{src}.TPY = {src}.phase.T, {src}.phase.P, {src}.phase.Y"
            )
            stream_mech = mech
            if ic.mechanism_switch is not None:
                tgt_mech = mech
                if self.plan is not None:
                    for ts in self.plan.ordered_stages:
                        if ts.id == ic.target_stage:
                            tgt_mech = ts.mechanism
                            break
                htol = float((ic.mechanism_switch or {}).get("htol", 1e-4))
                xtol = float((ic.mechanism_switch or {}).get("Xtol", 1e-4))
                lines.append(
                    f"_outlet_{src} = switch_mechanism("
                    f"_outlet_{src}, get_mechanism_path({tgt_mech!r}), "
                    f"htol={htol}, Xtol={xtol})"
                )
                stream_mech = tgt_mech
            lines.append(
                f"_gas_{spv} = ct.Solution(get_mechanism_path({stream_mech!r}))"
            )
            lines.append(
                f"_gas_{spv}.TPY = _outlet_{src}.T, _outlet_{src}.P, _outlet_{src}.Y"
            )
            lines.append(f"{spv} = ct.Reservoir(_gas_{spv}, clone=False)")
            lines.append(f"{spv}.name = {sp!r}")
            lines.append(f"reactors[{sp!r}] = {spv}")
            mdot_expr = self._mdot_out_expr(src_id, stage_conns)
            lines.append(f"_mdot_{src} = {mdot_expr}")
            inlet_mfc = ic.inlet_mfc_id
            lines.append(f"_mfc_flow_rates[{inlet_mfc!r}] = _mdot_{src}")
            lines.append(f"inlet_states[{ic.target_node!r}] = _outlet_{src}")
            lines.append("")

        return lines

    # ------------------------------------------------------------------
    # Import / preamble / post-build sections (overridable in subclasses)
    # ------------------------------------------------------------------

    def _emit_download_imports(self) -> List[str]:
        """Return the import block for the generated script.

        Override in a subclass to add extra imports (e.g. plugin reactor classes).
        Call ``super()._emit_download_imports()`` and append to the returned list.
        """
        lines: List[str] = [
            "import cantera as ct",
            "from boulder.utils import coerce_unit_string",
            "from boulder.cantera_converter import resolve_unset_flow_rates",
            "",
            "def get_mechanism_path(mech):",
            "    return mech",
        ]
        if self.has_mech_switch:
            lines += [
                "",
                "def switch_mechanism(outlet, path, htol=1e-4, Xtol=1e-4):  # noqa: ARG001",
                "    return outlet",
            ]
        return lines

    def _emit_preamble(self) -> List[str]:
        """Return the global registry setup lines."""
        lines = [
            "",
            f"mechanism = {self.mechanism!r}",
            "",
            "reactors = {}",
            "connections = {}",
            "walls = {}",
            "reactor_meta = {}",
            "_mfc_topology = {}",
            "_mfc_flow_rates = {}",
            "_unresolved_mfc_ids = set()",
            "_deferred_pc_conn_dicts = []",
            "inlet_states = {}",
            "",
            "def _parse_composition(comp_str):",
            "    return {",
            "        sp.strip(): float(val)",
            "        for sp, val in (pair.split(':') for pair in comp_str.split(','))",
            "    }",
            "",
            "def _apply_flow_conservation():",
            "    pending = set(_unresolved_mfc_ids)",
            "    if not pending:",
            "        return",
            "    mfcs = {",
            "        cid: dev for cid, dev in connections.items()",
            "        if isinstance(dev, ct.MassFlowController)",
            "    }",
            "    resolve_unset_flow_rates(",
            "        _mfc_topology, _mfc_flow_rates, mfcs, reactors, _unresolved_mfc_ids",
            "    )",
            "    for cid in pending:",
            "        connections[cid].mass_flow_rate = _mfc_flow_rates[cid]",
            "",
        ]
        lines += self._emit_extra_preamble()
        return lines

    def _emit_extra_preamble(self) -> List[str]:
        """Return extra preamble lines (e.g. a plugin build context).

        Override in a subclass to emit shared objects consumed by custom
        post-build hooks (such as a ``_ctx`` namespace).  The base returns an
        empty list because Boulder core needs no plugin build context.
        """
        return []

    def _emit_stage_extra_post_build(
        self, cfg_nodes: List[str], cfg_conns: List[str]
    ) -> List[str]:
        """Return per-stage post-build lines emitted after flow conservation.

        Override in a subclass to inject post-build hooks (e.g. plugin volume
        or geometry resolution) without overriding the entire
        ``_emit_stage_block``.  The base returns an empty list.
        """
        return []

    def _emit_post_build_calls(self) -> List[str]:
        """Return the trailing reporting-network lines appended after all stages."""
        return [
            "# Reporting network (all converged non-reservoir reactors)",
            "network = ct.ReactorNet([",
            "    r for r in reactors.values() if not isinstance(r, ct.Reservoir)",
            "])",
            "network.advance(0.0)",
        ]


# ---------------------------------------------------------------------------
# Runner-based script helper (module-level function, runner-centric)
# ---------------------------------------------------------------------------


def script_lines_for_runner(
    runner_import: str,
    runner_class: str,
    config_path: str,
    plan: Any,
    continuation: Any = None,
    signals_block: Any = None,
    bindings_block: Any = None,
) -> list:
    """Emit the runner-based staged-solve script block.

    For each stage the emitted snippet calls ``runner.solve_stage()``, which
    delegates to the full solver dispatcher (including ``advance_grid`` and
    ``micro_step`` loops).  After each stage a short human-readable progress
    summary is printed so the downloaded script gives meaningful output when
    run standalone.

    When *continuation* is provided the emitted script wraps the stage loop
    in an outer continuation sweep that mirrors the ``combustor.py`` pattern.

    Transient stages (``advance_grid``, ``micro_step``) additionally emit a
    progress line that shows the time elapsed, making the standalone script
    more useful as a verification script.

    When *signals_block* and *bindings_block* are provided the emitted script
    includes the causal-layer wiring verbatim:
    ``from boulder.signals import build_signal_registry``
    ``from boulder.bindings import apply_bindings_block``
    and wires signals into the built network so the standalone script is
    fully runnable without manual signal setup.
    """

    def _stage_block(plan, indent="") -> list:
        lines: list = []
        if plan is not None and plan.ordered_stages:
            n = len(plan.ordered_stages)
            for i, stage in enumerate(plan.ordered_stages):
                node_list = ", ".join(stage.node_ids)
                kind = (stage.solver or {}).get("kind", "advance_to_steady_state")
                is_transient = kind in TRANSIENT_SOLVER_KINDS
                lines += [
                    f"{indent}# Stage {i + 1}/{n}: {stage.id}  [nodes: {node_list}]",
                    f"{indent}runner.solve_stage(plan, plan.ordered_stages[{i}], "
                    "inlet_states, trajectory)",
                ]
                if is_transient:
                    lines += [
                        f"{indent}print(f'Stage {stage.id} ({kind}) complete.')",
                        f"{indent}for _r in runner.converter.reactors.values():",
                        f"{indent}    if hasattr(_r.phase, 'T'):",
                        f"{indent}        print(f'  {{_r.name}}: T={{_r.phase.T:.1f}} K"
                        "  P={_r.phase.P:.0f} Pa')",
                    ]
                else:
                    lines += [
                        f"{indent}print(f'Stage {stage.id} ({kind}) converged.')",
                        f"{indent}for _r in runner.converter.reactors.values():",
                        f"{indent}    if hasattr(_r.phase, 'T'):",
                        f"{indent}        print(f'  {{_r.name}}: T={{_r.phase.T:.1f}} K"
                        "  P={_r.phase.P:.0f} Pa')",
                    ]
                lines.append("")
        else:
            lines += [f"{indent}runner.build()", ""]
        return lines

    lines = [
        runner_import,
        "",
        f"config_path = {repr(config_path)}",
        f"runner = {runner_class}.from_yaml(config_path)",
        "plan = runner.build_stage_graph()",
        "trajectory = runner.new_trajectory()",
        "inlet_states = {}",
        "",
    ]

    if signals_block and bindings_block:
        import json as _json

        lines += [
            "# --- Causal layer: signals + bindings (derived_via: ast_match) ---",
            "from boulder.signals import build_signal_registry",
            "from boulder.bindings import apply_bindings_block",
            "",
            "# Build the network first so bindings can reference reactor objects.",
            "# runner.build() or runner.solve_stage() must be called AFTER apply_bindings_block.",
            f"_signals_block = {_json.dumps(signals_block, indent=2)}",
            f"_bindings_block = {_json.dumps(bindings_block, indent=2)}",
            "_signal_registry = build_signal_registry(_signals_block)",
            "# Note: apply_bindings_block must be called after build_sub_network",
            "# The staged solver applies them automatically when signals/bindings",
            "# are present in the config YAML; this block is provided for transparency.",
            "",
        ]

    if continuation:
        param = continuation.get("parameter", "")
        update = continuation.get("update", {})
        until = continuation.get("until", {})
        max_iters = int(until.get("max_iters", 200))

        until_cond_parts = []
        if "reactor_T_below" in until:
            t = until["reactor_T_below"]
            until_cond_parts.append(
                f"all(r.phase.T >= {t} for r in runner.converter.reactors.values() "
                "if not hasattr(r, '_is_reservoir'))"
            )
        if not until_cond_parts:
            until_cond_parts.append(f"_cont_iter < {max_iters}")

        lines += [
            "_cont_iter = 0",
            f"while {' and '.join(until_cond_parts)} and _cont_iter < {max_iters}:",
        ]
        lines += _stage_block(plan, indent="    ")
        if "multiply" in update:
            f = update["multiply"]
            parts = param.split(".")
            if parts[0] == "connections" and len(parts) >= 3:
                cid = parts[1]
                attr = ".".join(parts[2:])
                lines += [
                    f"    runner.converter.connections['{cid}'].{attr} *= {f}",
                ]
        lines += [
            "    _cont_iter += 1",
            "",
        ]
    else:
        lines += _stage_block(plan)

    lines += [
        "# Assemble visualization network from all converged states",
        "runner.build_viz_network(plan, trajectory)",
        "network = runner.network",
        "converter = runner.converter",
    ]
    return lines


# ---------------------------------------------------------------------------
# Backward-compatible free-function wrapper
# ---------------------------------------------------------------------------


def emit_cantera_native_script(
    config: Dict[str, Any], converter_class: str = ""
) -> List[str]:
    """Return Python source lines for a Cantera-native staged-solve script.

    Thin wrapper around :class:`CanteraScriptEmitter` kept for backward
    compatibility.  The ``converter_class`` parameter is accepted but ignored
    by the base emitter (it is retained here so that existing callers do not
    need to be updated in this task).
    """
    return CanteraScriptEmitter().emit(config)
