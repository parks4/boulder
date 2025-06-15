import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import cantera as ct  # type: ignore

from .config import CANTERA_MECHANISM
from .sankey import generate_sankey_input_from_sim

logger = logging.getLogger(__name__)


class CanteraConverter:
    def __init__(self, mechanism: Optional[str] = None) -> None:
        # Use provided mechanism or fall back to config default
        self.mechanism = mechanism or CANTERA_MECHANISM
        try:
            self.gas = ct.Solution(self.mechanism)
            print(f"[INFO] Successfully loaded mechanism: {self.mechanism}")
        except Exception as e:
            raise ValueError(f"Failed to load mechanism '{self.mechanism}': {e}")
        self.reactors: Dict[str, ct.Reactor] = {}
        self.connections: Dict[str, ct.FlowDevice] = {}
        self.network: ct.ReactorNet = None
        self.last_network: ct.ReactorNet = (
            None  # Store the last successfully built network
        )

    def parse_composition(self, comp_str: str) -> Dict[str, float]:
        """Convert composition string to dictionary of species and mole fractions."""
        comp_dict = {}
        for pair in comp_str.split(","):
            species, value = pair.split(":")
            comp_dict[species] = float(value)
        return comp_dict

    def create_reactor(self, reactor_config: Dict[str, Any]) -> ct.Reactor:
        """Create a Cantera reactor from configuration."""
        reactor_type = reactor_config["type"]
        props = reactor_config["properties"]

        # Set gas state
        self.gas.TPX = (
            props.get("temperature", 300),
            props.get("pressure", 101325),
            self.parse_composition(props.get("composition", "N2:1")),
        )

        if reactor_type == "IdealGasReactor":
            reactor = ct.IdealGasReactor(self.gas)
        elif reactor_type == "Reservoir":
            reactor = ct.Reservoir(self.gas)
        else:
            raise ValueError(f"Unsupported reactor type: {reactor_type}")

        # Set the reactor name to match the config ID
        reactor.name = reactor_config["id"]

        return reactor

    def create_connection(self, conn_config: Dict[str, Any]) -> ct.FlowDevice:
        """Create a Cantera flow device from configuration."""
        conn_type = conn_config["type"]
        props = conn_config["properties"]

        source = self.reactors[conn_config["source"]]
        target = self.reactors[conn_config["target"]]

        if conn_type == "MassFlowController":
            device = ct.MassFlowController(source, target)
            device.mass_flow_rate = props.get("mass_flow_rate", 0.1)
        elif conn_type == "Valve":
            device = ct.Valve(source, target)
            device.valve_coeff = props.get("valve_coeff", 1.0)
        else:
            raise ValueError(f"Unsupported connection type: {conn_type}")

        return device

    def build_network(
        self, config: Dict[str, Any]
    ) -> Tuple[ct.ReactorNet, Dict[str, Any]]:
        """Build a ReactorNet from configuration and return network and results."""
        # Clear previous state
        self.reactors.clear()
        self.connections.clear()

        # Create reactors
        for comp in config["components"]:
            if comp["type"] == "IdealGasReactor" or comp["type"] == "Reservoir":
                self.reactors[comp["id"]] = self.create_reactor(comp)

        # Create connections
        for conn in config["connections"]:
            if conn["type"] == "MassFlowController" or conn["type"] == "Valve":
                self.connections[conn["id"]] = self.create_connection(conn)

        # Create network - only include IdealGasReactors, not Reservoirs
        reactor_list = [
            r for r in self.reactors.values() if isinstance(r, ct.IdealGasReactor)
        ]
        if not reactor_list:
            raise ValueError("No IdealGasReactors found in the network")

        self.network = ct.ReactorNet(reactor_list)

        # Configure solver for better stability
        self.network.rtol = 1e-6  # Relaxed relative tolerance
        self.network.atol = 1e-8  # Relaxed absolute tolerance
        self.network.max_steps = 10000  # Increase maximum steps

        # Run simulation with smaller time steps
        times = []
        temperatures = []
        pressures = []
        species: Dict[str, List[float]] = {
            species: [] for species in self.gas.species_names
        }

        # Use smaller time steps and shorter simulation time
        for t in range(0, 10, 1):  # Simulate for 10 seconds with 1-second steps
            try:
                self.network.advance(t)
                times.append(t)
                # Get results from the first reactor
                first_reactor = reactor_list[0]
                temperatures.append(first_reactor.thermo.T)
                pressures.append(first_reactor.thermo.P)

                for species_name in self.gas.species_names:
                    species[species_name].append(
                        first_reactor.thermo[species_name].X[0]
                    )
            except Exception as e:
                logger.warning(f"Warning at t={t}: {str(e)}")
                # If we hit an error, use the last successful values
                if times:
                    times.append(t)
                    temperatures.append(temperatures[-1])
                    pressures.append(pressures[-1])
                    for species_name in self.gas.species_names:
                        species[species_name].append(species[species_name][-1])

        results: Dict[str, Any] = {
            "time": times,
            "temperature": temperatures,
            "pressure": pressures,
            "species": species,
        }

        # Store the successful network for later use (e.g., Sankey diagrams)
        self.last_network = self.network

        # Generate Sankey data
        try:
            links, nodes = generate_sankey_input_from_sim(
                self.last_network,
                show_species=["H2", "CH4"],
                verbose=False,
                mechanism=self.mechanism,
            )
            results["sankey_links"] = links
            results["sankey_nodes"] = nodes
        except Exception as e:
            logger.error(f"Error generating Sankey diagram: {e}")
            results["sankey_links"] = None
            results["sankey_nodes"] = None

        return self.network, results

    def load_config(self, filepath: str) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        with open(filepath, "r") as f:
            return json.load(f)


class DualCanteraConverter:
    def __init__(self, mechanism: Optional[str] = None) -> None:
        """Initialize DualCanteraConverter.

        Executes the Cantera network as before.
        Simultaneously builds a string of Python code that, if run, will produce the same objects and results.
        Returns (network, results, code_str) from build_network_and_code(config).
        """
        # Use provided mechanism or fall back to config default
        self.mechanism = mechanism or CANTERA_MECHANISM
        try:
            self.gas = ct.Solution(self.mechanism)
            print(f"[INFO] Successfully loaded mechanism: {self.mechanism}")
        except Exception as e:
            raise ValueError(f"Failed to load mechanism '{self.mechanism}': {e}")
        self.reactors: Dict[str, ct.Reactor] = {}
        self.connections: Dict[str, ct.FlowDevice] = {}
        self.network: ct.ReactorNet = None
        self.code_lines: List[str] = []
        self.last_network: ct.ReactorNet = (
            None  # Store the last successfully built network
        )

    def parse_composition(self, comp_str: str) -> Dict[str, float]:
        comp_dict = {}
        for pair in comp_str.split(","):
            species, value = pair.split(":")
            comp_dict[species] = float(value)
        return comp_dict

    def build_network_and_code(
        self, config: Dict[str, Any]
    ) -> Tuple[Any, Dict[str, Any], str]:
        self.code_lines = []
        self.code_lines.append("import cantera as ct")
        self.code_lines.append(f"gas = ct.Solution('{self.mechanism}')")
        try:
            self.gas = ct.Solution(self.mechanism)
        except Exception as e:
            print(
                f"[ERROR] Failed to reload mechanism '{self.mechanism}' in build_network_and_code: {e}"
            )
            # Note: self.gas should already be set from __init__, so this is just for consistency
        self.reactors = {}
        self.connections = {}
        self.network = None

        # Reactors
        for comp in config["components"]:
            rid = comp["id"]
            typ = comp["type"]
            props = comp["properties"]
            temp = props.get("temperature", 300)
            pres = props.get("pressure", 101325)
            compo = props.get("composition", "N2:1")
            self.code_lines.append(f"gas.TPX = ({temp}, {pres}, '{compo}')")
            self.gas.TPX = (temp, pres, self.parse_composition(compo))
            if typ == "IdealGasReactor":
                self.code_lines.append(f"{rid} = ct.IdealGasReactor(gas)")
                self.code_lines.append(f"{rid}.name = '{rid}'")
                self.reactors[rid] = ct.IdealGasReactor(self.gas)
                self.reactors[rid].name = rid
            elif typ == "Reservoir":
                self.code_lines.append(f"{rid} = ct.Reservoir(gas)")
                self.code_lines.append(f"{rid}.name = '{rid}'")
                self.reactors[rid] = ct.Reservoir(self.gas)
                self.reactors[rid].name = rid
            else:
                self.code_lines.append(f"# Unsupported reactor type: {typ}")
                raise ValueError(f"Unsupported reactor type: {typ}")

        # Connections
        for conn in config["connections"]:
            cid = conn["id"]
            typ = conn["type"]
            src = conn["source"]
            tgt = conn["target"]
            props = conn["properties"]
            if typ == "MassFlowController":
                mfr = props.get("mass_flow_rate", 0.1)
                self.code_lines.append(f"{cid} = ct.MassFlowController({src}, {tgt})")
                self.code_lines.append(f"{cid}.mass_flow_rate = {mfr}")
                self.connections[cid] = ct.MassFlowController(
                    self.reactors[src], self.reactors[tgt]
                )
                self.connections[cid].mass_flow_rate = mfr
            elif typ == "Valve":
                coeff = props.get("valve_coeff", 1.0)
                self.code_lines.append(f"{cid} = ct.Valve({src}, {tgt})")
                self.code_lines.append(f"{cid}.valve_coeff = {coeff}")
                self.connections[cid] = ct.Valve(self.reactors[src], self.reactors[tgt])
                self.connections[cid].valve_coeff = coeff
            else:
                self.code_lines.append(f"# Unsupported connection type: {typ}")
                raise ValueError(f"Unsupported connection type: {typ}")

        # ReactorNet
        reactor_ids = [
            comp["id"]
            for comp in config["components"]
            if comp["type"] == "IdealGasReactor"
        ]
        self.code_lines.append(f"network = ct.ReactorNet([{', '.join(reactor_ids)}])")
        self.network = ct.ReactorNet([self.reactors[rid] for rid in reactor_ids])
        self.code_lines.append("network.rtol = 1e-6")
        self.code_lines.append("network.atol = 1e-8")
        self.code_lines.append("network.max_steps = 10000")
        self.network.rtol = 1e-6
        self.network.atol = 1e-8
        self.network.max_steps = 10000

        # Simulation loop (example)
        self.code_lines.append(
            """# Run the simulation\nfor t in range(0, 10, 1):\n    network.advance(t)\n    """
            + """print(f\"t={t}, T={[r.thermo.T for r in network.reactors]}\")"""
        )
        # TOOD: add dual code directly in the simulation loop too.

        # Run simulation (same as CanteraConverter)
        times = []
        temperatures = []
        pressures = []
        species: Dict[str, List[float]] = {
            species: [] for species in self.gas.species_names
        }
        reactor_list = [self.reactors[rid] for rid in reactor_ids]
        for t in range(0, 10, 1):
            try:
                self.network.advance(t)
                times.append(t)
                first_reactor = reactor_list[0]
                temperatures.append(first_reactor.thermo.T)
                pressures.append(first_reactor.thermo.P)
                for species_name in self.gas.species_names:
                    species[species_name].append(
                        first_reactor.thermo[species_name].X[0]
                    )
            except Exception as e:
                logger.warning(f"Warning at t={t}: {str(e)}")
                if times:
                    times.append(t)
                    temperatures.append(temperatures[-1])
                    pressures.append(pressures[-1])
                    for species_name in self.gas.species_names:
                        species[species_name].append(species[species_name][-1])
        results: Dict[str, Any] = {
            "time": times,
            "temperature": temperatures,
            "pressure": pressures,
            "species": species,
        }

        # Store the successful network for later use (e.g., Sankey diagrams)
        self.last_network = self.network

        # Generate Sankey data
        try:
            links, nodes = generate_sankey_input_from_sim(
                self.last_network,
                show_species=["H2", "CH4"],
                verbose=False,
                mechanism=self.mechanism,
            )
            results["sankey_links"] = links
            results["sankey_nodes"] = nodes
        except Exception as e:
            logger.error(f"Error generating Sankey diagram: {e}")
            results["sankey_links"] = None
            results["sankey_nodes"] = None

        return self.network, results, "\n".join(self.code_lines)
