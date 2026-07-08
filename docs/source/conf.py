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
release = "0.2.2"
# -- General configuration ---------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "sphinx_copybutton",
    "sphinx_llms_txt",
]

# -- sphinx-llms-txt configuration -------------------------------------------
# Emits llms.txt (a Markdown index of every page) and llms-full.txt (the whole
# corpus in one file) into the HTML build output. The URLs inside llms.txt are
# built from html_baseurl, so it must point at the published docs root.
html_baseurl = "https://pygigevision.readthedocs.io/en/latest/"
llms_txt_title = "pyGigEVision Documentation"
llms_txt_summary = (
    "pyGigEVision is a pure-Python implementation of the GigE Vision protocol "
    "(GVCP control and GVSP streaming), with no vendor SDK and no GenTL producers. "
    "It provides the protocol primitives that vendor-specific camera drivers build "
    "on: device discovery, control-register read/write, streaming reception, and "
    "GenICam descriptor download."
)

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
html_css_files = ["ai-buttons.css"]
html_js_files = ["ai-buttons.js"]
html_theme_options = {
    "repository_url": "https://github.com/ladisk/pyGigEVision",
    "use_repository_button": True,
    "use_issues_button": True,
    "path_to_docs": "docs/source",
}
