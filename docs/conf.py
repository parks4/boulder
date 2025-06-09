# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Import and path setup ---------------------------------------------------

import os
import sys

import boulder

sys.path.insert(0, os.path.abspath("../"))

# -- Project information -----------------------------------------------------

project = "boulder"
copyright = "2025, Copyright (C) Spark Cleantech SAS (SIREN 909736068)"
author = "Erwan Pannier"
version = boulder.__version__
release = boulder.__version__

# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "autoapi.extension",
    "myst_parser",
    "sphinx.ext.autodoc",  # Core library for html generation from docstrings.
    "sphinx.ext.autosummary",  # Create neat summary tables.
    "sphinx.ext.napoleon",  # Support for NumPy and Google style docstrings.
    "sphinx.ext.intersphinx",
    "sphinx_gallery.gen_gallery",
]

# Intersphinx: Reference other packages
intersphinx_mapping = {
    "cantera": ("https://www.cantera.org/documentation/docs-2.6/sphinx/html/", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "matplotlib": ("https://matplotlib.org/stable/", None),
    "pandas": ("https://pandas.pydata.org/pandas-docs/stable/", None),
    "scipy": ("https://docs.scipy.org/doc/scipy/", None),
    "sklearn": ("http://scikit-learn.org/stable", None),
    # see https://stackoverflow.com/questions/46080681/scikit-learn-intersphinx-link-inventory-object
}

# autodoc configuration
autodoc_typehints = "none"

# autoapi configuration
autoapi_dirs = ["../boulder"]
autoapi_ignore = ["*/version.py"]
autoapi_options = [
    "members",
    "inherited-members",
    "undoc-members",
    "show-inheritance",
    "show-module-summary",
    "imported-members",
]
autoapi_root = "_api"

# napoleon configuration
napoleon_google_docstring = False
napoleon_numpy_docstring = True
napoleon_preprocess_types = True

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]


# %% Options for Sphinx Gallery

sphinx_gallery_conf = {
    "examples_dirs": "../examples",  # path to your example scripts
    "gallery_dirs": "auto_examples",  # path to where to save gallery generated output
    # to make references clickable
    "reference_url": {
        "boulder": None,
    },
    # directory where function/class granular galleries are stored
    "backreferences_dir": "source/backreferences",
    # Modules for which function/class level galleries are created. In
    # this case boulder, in a tuple of strings:
    "doc_module": ("boulder",),
    "inspect_global_variables": True,
    "show_signature": False,
}

# used for mini-galleries : https://sphinx-gallery.github.io/stable/configuration.html#add-mini-galleries-for-api-documentation
autosummary_generate = True


# %%

# -- Options for HTML output -------------------------------------------------

html_show_sourcelink = False  # remove 'view source code' from top of page

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "pydata_sphinx_theme"

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]
html_css_files = [
    "custom.css",
]

html_logo = "boulder_logo_small.png"
