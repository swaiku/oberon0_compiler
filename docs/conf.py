# SPDX-FileCopyrightText: 2026 Jérémy Prin
# SPDX-License-Identifier: MIT OR Apache-2.0

# Configuration file for the Sphinx documentation builder.
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import sys
from pathlib import Path

# Make the package importable without installing it first.
# The source tree lives one level above this file (docs/../src).
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# -- Project information -----------------------------------------------------
project = "oberon0-compiler"
copyright = "2026, Jérémy Prin"
author = "Jérémy Prin"
release = "0.2.2"

# -- General configuration ---------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",  # pull docstrings from Python source
    "sphinx.ext.napoleon",  # parse Google / NumPy-style docstrings
    "sphinx.ext.viewcode",  # add "[source]" links next to each symbol
    "sphinx.ext.intersphinx",  # cross-reference to external projects
    "sphinx_design",  # grid / card / tab directives
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Intersphinx -------------------------------------------------------------
# Allows :class:`pathlib.Path` etc. to link to the Python standard library.
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# -- Autodoc -----------------------------------------------------------------
# Preserve the order in which members are defined in the source file.
autodoc_member_order = "bysource"

# Render type annotations in the function/method signature only.
# Using "description" with @dataclass fields causes Sphinx to generate
# duplicate py:attribute entries when the same class is referenced from
# multiple module pages, which triggers duplicate-object warnings.
autodoc_typehints = "signature"

# For @dataclass classes, using "both" causes every field to be documented
# twice: once as a class attribute and once as an __init__ parameter.
# Using "class" avoids this duplication.
autoclass_content = "class"

# Show the full module path in the default value of :show-inheritance:.
autodoc_inherit_docstrings = True

# Suppress duplicate-object warnings that arise from @dataclass field
# annotations being picked up through both the module's own page and
# cross-references from other autodoc-processed modules.
suppress_warnings = ["autodoc.duplicate_object", "ref.duplicate"]

# -- Napoleon ----------------------------------------------------------------
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_preprocess_types = True

# -- Options for HTML output -------------------------------------------------
html_theme = "furo"
html_static_path = ["_static"]

html_theme_options = {
    "light_css_variables": {
        "color-brand-primary": "#0071c5",
        "color-brand-content": "#0071c5",
    },
}
