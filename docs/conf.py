# Configuration file for the Sphinx documentation builder.
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------

project = "PysternBlot"
copyright = "2026, Etienne Boulter and Chloé C. Féral"
author = "Etienne Boulter, Chloé C. Féral"
release = "1.1.0"

# -- General configuration ---------------------------------------------------

extensions = [
    "myst_parser",  # lets Sphinx read Markdown (.md) as well as reStructuredText
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- HTML output -------------------------------------------------------------

html_theme = "furo"
html_title = "PysternBlot"
html_static_path = ["_static"]
