"""Marks ``configs/`` as a real package purely so setuptools ships it.

``boulder.config.get_initial_config()``/``get_initial_config_with_comments()``
look for the built-in default config at a fixed path *sibling* to the
installed ``boulder`` package (``dirname(dirname(__file__)) / "configs" /
"default.yaml"``). Without this file, setuptools has no way to know this
top-level directory should be copied into site-packages alongside ``boulder``
when building the wheel — ``[tool.setuptools] packages`` only ships packages
it recognises, and a plain data directory with no ``__init__.py`` isn't one.
"""
