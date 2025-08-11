Welcome to Boulder's documentation!
================================

Boulder is a web-based tool for visually constructing and simulating Cantera ReactorNet systems.

Quick start
-----------

From Python (as in ``run.py``)::

    from boulder.app import run_server
    if __name__ == "__main__":
        run_server(debug=True)

From the CLI::

    boulder                 # launches the server & opens the interface
    boulder some_file.yaml  # launches the server preloading a YAML config

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   installation
   usage
   api

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
