Gallery of Boulder Examples
==========================

This section contains examples demonstrating how to use Boulder to set up and run
chemical reactor network simulations.

Quick start
-----------

From Python (as in ``run.py``)::

    from boulder.app import run_server
    if __name__ == "__main__":
        run_server(debug=True)

From the CLI::

    boulder                 # launches the server & opens the interface
    boulder some_file.yaml  # launches the server preloading a YAML config

Each example provides a complete working demonstration with explanations and results,
showing different aspects of reactor modeling and simulation with Boulder.
