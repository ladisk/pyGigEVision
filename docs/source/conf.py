# Configuration file for the Sphinx documentation builder.
#
# Full reference: https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

# -- Path setup --------------------------------------------------------------
sys.path.insert(0, os.path.abspath("../.."))

# -- Project information -----------------------------------------------------
project = "pyGigEVision"
author = "Jaša Šonc, Janko Slavič, Lorenzo Capponi"
copyright = "2026, Jaša Šonc and Ladisk group, University of Ljubljana"
release = "0.1.1"

# -- General configuration ---------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "sphinx_copybutton",
]

templates_path = ["_templates"]
exclude_patterns = []

autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
    "member-order": "bysource",
}

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
}

napoleon_google_docstring = False
napoleon_numpy_docstring = True
napoleon_use_param = True
napoleon_use_rtype = True

# -- HTML output -------------------------------------------------------------
html_theme = "sphinx_book_theme"
html_static_path = ["_static"]
html_title = "pyGigEVision"
html_theme_options = {
    "repository_url": "https://github.com/ladisk/pyGigEVision",
    "use_repository_button": True,
    "use_issues_button": True,
    "path_to_docs": "docs/source",
}
