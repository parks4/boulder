import cantera as ct
import json
from typing import Dict, List, Tuple

class CanteraConverter:
    def __init__(self):
        self.gas = ct.Solution('gri30.yaml')
        self.reactors = {}
        self.connections = {}
        self.network = None

    def parse_composition(self, comp_str: str) -> Dict[str, float]:
        """Convert composition string to dictionary of species and mole fractions."""
        comp_dict = {}
        for pair in comp_str.split(','):
            species, value = pair.split(':')
            comp_dict[species] = float(value)
        return comp_dict

    def create_reactor(self, reactor_config: Dict) -> ct.Reactor:
        """Create a Cantera reactor from configuration."""
        reactor_type = reactor_config['type']
        props = reactor_config['properties']
        
        # Set gas state
        self.gas.TPX = (
            props.get('temperature', 300),
            props.get('pressure', 101325),
            self.parse_composition(props.get('composition', 'N2:1'))
        )

        if reactor_type == 'IdealGasReactor':
            reactor = ct.IdealGasReactor(self.gas)
        elif reactor_type == 'Reservoir':
            reactor = ct.Reservoir(self.gas)
        else:
            raise ValueError(f"Unsupported reactor type: {reactor_type}")

        return reactor

    def create_connection(self, conn_config: Dict) -> ct.FlowDevice:
        """Create a Cantera flow device from configuration."""
        conn_type = conn_config['type']
        props = conn_config['properties']
        
        source = self.reactors[conn_config['source']]
        target = self.reactors[conn_config['target']]

        if conn_type == 'MassFlowController':
            device = ct.MassFlowController(source, target)
            device.mass_flow_rate = props.get('mass_flow_rate', 0.1)
        elif conn_type == 'Valve':
            device = ct.Valve(source, target)
            device.valve_coeff = props.get('valve_coeff', 1.0)
        else:
            raise ValueError(f"Unsupported connection type: {conn_type}")

        return device

    def build_network(self, config: Dict) -> Tuple[ct.ReactorNet, Dict[str, List[float]]]:
        """Build a ReactorNet from configuration and return network and results."""
        # Clear previous state
        self.reactors.clear()
        self.connections.clear()

        # Create reactors
        for comp in config['components']:
            self.reactors[comp['id']] = self.create_reactor(comp)

        # Create connections
        for conn in config['connections']:
            self.connections[conn['id']] = self.create_connection(conn)

        # Create network
        self.network = ct.ReactorNet(list(self.reactors.values()))
        
        # Run simulation
        times = []
        temperatures = []
        pressures = []
        species = {species: [] for species in self.gas.species_names}

        for t in range(0, 100, 1):
            self.network.advance(t)
            times.append(t)
            temperatures.append(self.reactors['reactor1'].thermo.T)
            pressures.append(self.reactors['reactor1'].thermo.P)
            
            for species_name in self.gas.species_names:
                species[species_name].append(
                    self.reactors['reactor1'].thermo[species_name].X[0]
                )

        results = {
            'time': times,
            'temperature': temperatures,
            'pressure': pressures,
            'species': species
        }

        return self.network, results

    def load_config(self, filepath: str) -> Dict:
        """Load configuration from JSON file."""
        with open(filepath, 'r') as f:
            return json.load(f) 