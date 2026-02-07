Welcome to Boulder's documentation!
================================

Boulder is a web-based tool for visually constructing and simulating Cantera ReactorNet systems.

.. figure:: mix_streams_example.png
   :alt: Mixed reactor streams example in Boulder
   :align: center
   :width: 80%

   Mixed reactor streams example in Boulder.

Quick start
-----------

From Python (as in ``run.py``)::

    import uvicorn
    if __name__ == "__main__":
        uvicorn.run("boulder.api.main:app", host="0.0.0.0", port=8050, reload=True)

From the CLI::

    boulder                 # launches the server & opens the interface
    boulder some_file.yaml  # launches the server preloading a YAML config

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   installation
   usage
   auto_examples/index
   api

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
