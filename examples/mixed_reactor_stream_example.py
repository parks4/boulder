"""Mixing two streams example - Boulder conversion.

Boulder context
---------------

This example demonstrates how to use Boulder's sim2stone functionality to convert
a Cantera reactor network simulation to a 🪨 STONE serialized .yaml format.

The Cantera simulation setup is imported from mix1.py, which implements the
mixing example from https://cantera.org/3.1/examples/python/reactors/mix1.html.
This file focuses on the Boulder-specific functionality for serialization and
regeneration of reactor networks.
"""

# Import the Cantera simulation setup from mix1.py
import sys
from pathlib import Path

# For regeneration and Boulder functionality
from boulder.cantera_converter import DualCanteraConverter
from boulder.config import load_config_file, normalize_config, validate_config
from boulder.sim2stone import write_sim_as_yaml

# Add the examples directory to the path to import mix1
examples_dir = Path(__file__).parent
sys.path.insert(0, str(examples_dir))

import mix1  # import any file where there is a simulation object `sim`  # noqa: E402

# %%
# Boulder functionality: Serialize to STONE YAML
# -----------------------------------------------

# Serialize the network to a STONE YAML file
output_yaml = "mixed_reactor_stream.yaml"
write_sim_as_yaml(mix1.sim, output_yaml)
print(f"Wrote STONE YAML to {output_yaml}")

# ✨ We now have a STONE YAML representation of the simulation!


"""
All of this can be ran from command line with

```bash
sim2stone mix1.py
```
"""


# %%
# Boulder functionality: Regenerate from STONE YAML
# --------------------------------------------------
# Regenerate the simulation from the STONE YAML file and verify it works

# Load and validate the STONE YAML file
loaded = load_config_file("mixed_reactor_stream.yaml")
normalized = normalize_config(loaded)
validated = validate_config(normalized)

# Get mechanism from phases.gas.mechanism (STONE standard)
phases = validated.get("phases", {})
gas = phases.get("gas", {}) if isinstance(phases, dict) else {}
mechanism = gas.get("mechanism")

# Build the network from the STONE YAML
converter = DualCanteraConverter(mechanism=mechanism)
network = converter.build_network(validated)
print(
    f"Rebuilt network with {len(converter.reactors)} nodes and "
    f"{len(converter.connections)} connections."
)

# %%
# Verify the regenerated network matches the original
# ---------------------------------------------------
expected_nodes = {
    mix1.res_a.name,
    mix1.res_b.name,
    mix1.mixer.name,
    mix1.downstream.name,
}
assert set(converter.reactors.keys()) == expected_nodes
assert len(converter.connections) == 3
print("✅ Network regeneration successful - all assertions passed!")
