# Cantera ReactorNet Visualizer

![logo](docs/boulder_logo_small.png)

A web-based tool for visually constructing and simulating Cantera ReactorNet systems using Dash and Cytoscape.

## Features

- Interactive graph editor for creating reactor networks
- Support for various reactor types (IdealGasReactor, Reservoir)
- Support for flow devices (MassFlowController, Valve)
- Real-time property editing
- Simulation capabilities with time-series plots
- YAML configuration files with 🪨 STONE standard (elegant format)

![screenshot](docs/mix_streams_example.png)

## Installation

It is recommended to install this package in a dedicated environment. Clone the repository and create
an isolated environment :

```
git clone https://github.com/parks4/boulder.git
cd boulder
conda env create -n boulder -f environment.yml
conda activate boulder
pip install -e .         # install in editable mode
```

## Usage

### From Python

Start the application programmatically (as in `run.py`):

```python
from boulder.app import run_server

if __name__ == "__main__":
    run_server(debug=True)
```

### From the CLI

After installation, use the `boulder` command:

```bash
boulder                 # launches the server & opens the interface
boulder some_file.yaml  # launches the server & preloads the YAML into the UI
```

Optional flags:

```bash
boulder --host 0.0.0.0 --port 8050 --debug  # customize host/port and enable debug
boulder some_file.yaml --no-open            # do not auto-open the browser
```

Notes:

- You can also set `BOULDER_CONFIG_PATH` (or `BOULDER_CONFIG`) to preload a YAML file.
- Default address is `http://127.0.0.1:8050`.

Once running, use the interface to:

- Upload existing configurations
- Create new reactor networks
- Edit properties
- Run simulations
- View results

## YAML Configuration with 🪨 STONE Standard

Boulder uses **YAML format with 🪨 STONE standard** (**Structured Type-Oriented Network Expressions**) - an elegant configuration format where component types become keys containing their properties:

```yaml
metadata:
  name: "Reactor Configuration"
  version: "1.0"

simulation:
  mechanism: "gri30.yaml"
  time_step: 0.001
  max_time: 10.0

components:
  - id: reactor1
    IdealGasReactor:
      temperature: 1000      # K
      pressure: 101325       # Pa
      composition: "CH4:1,O2:2,N2:7.52"

connections:
  - id: mfc1
    MassFlowController:
      mass_flow_rate: 0.1    # kg/s
    source: res1
    target: reactor1
```

See [`configs/README.md`](configs/README.md) for comprehensive YAML with 🪨 STONE standard documentation and examples.

## Supported Components

### Reactors

- IdealGasReactor
- Reservoir

### Flow Devices

- MassFlowController
- Valve

## Contributing / Developers

Feel free to submit issues and enhancement requests!
Before pushing to GitHub, run the following commands:

1. Update conda environment: `make conda-env-update`
1. Install this package in editable mode: `pip install -e .`
1. (optional) Sync with the latest [template](https://github.com/spark-cleantech/package-template) : `make template-update`
1. (optional) Run quality assurance checks (code linting): `make qa`
1. (optional) Run tests: `make unit-tests`
1. (optional) Run the static type checker: `make type-check`
1. (optional) Build the documentation (see [Sphinx tutorial](https://www.sphinx-doc.org/en/master/tutorial/)): `make docs-build`

If using Windows, `make` is not available by default. Either install it
([for instance with Chocolatey](https://stackoverflow.com/questions/32127524/how-to-install-and-use-make-in-windows)),
or open the [Makefile](./Makefile) and execute the lines therein manually.

## License

```
Copyright (C) Spark Cleantech SAS (SIREN 909736068) - All Rights Reserved
Unauthorized copying of this file, via any medium is strictly prohibited
Proprietary and confidential
Written by Erwan Pannier <erwan.pannier@spark-cleantech.eu>, June2025
```
