"""Sphinx configuration for the Grad Café analytics documentation (Module 4)."""

import os
import sys
from pathlib import Path

# Make the application modules in module_4/src importable for autodoc.
SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))

# Importing the app builds a (lazy) SQLAlchemy engine; give it a harmless URL so the
# docs build never needs a database or credentials.
os.environ.setdefault("DATABASE_URL", "postgresql://docs@localhost:5432/gradcafe")

project = "Grad Café Analytics"
author = "Caleb Gevertz"
copyright = "2026, Caleb Gevertz"
release = "4.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
    "member-order": "bysource",
}
autodoc_typehints = "description"
# The optional local-LLM packages are not needed to document the application.
autodoc_mock_imports = ["llama_cpp", "huggingface_hub"]

templates_path = []
exclude_patterns = []

html_theme = "sphinx_rtd_theme"
html_title = "Grad Café Analytics"
html_show_sourcelink = False
