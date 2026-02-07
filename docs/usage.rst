Usage
=====

From Python
-----------

Run Boulder programmatically (as in ``run.py``)::

    import uvicorn
    if __name__ == "__main__":
        uvicorn.run("boulder.api.main:app", host="0.0.0.0", port=8050, reload=True)

From the CLI
------------

After installation, use the ``boulder`` command::

    boulder                 # launches the server & opens the interface
    boulder some_file.yaml  # launches the server preloading a YAML config

Optional flags::

    boulder --host 0.0.0.0 --port 8050 --debug
    boulder some_file.yaml --no-open

Environment variables
---------------------

You can set ``BOULDER_CONFIG_PATH`` (or ``BOULDER_CONFIG``) to preload a YAML file::

    BOULDER_CONFIG_PATH=path/to/config.yaml boulder
