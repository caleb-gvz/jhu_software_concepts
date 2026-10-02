"""``setup.py`` and ``requirements.txt`` describe the project completely and consistently.

``setup.py`` is executed with ``setuptools.setup`` replaced by a recorder, so these tests
need no build tools and no network.
"""

import ast
import re
import runpy
import sys
from pathlib import Path

import pytest
import setuptools

import flask_app

pytestmark = pytest.mark.web

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# import name -> distribution name, for every third-party package the code in src/ imports
# (the two optional LLM packages in src/llm_hosting are deliberately not required).
RUNTIME_IMPORTS = {
    "bs4": "beautifulsoup4",
    "flask": "flask",
    "psycopg": "psycopg",
    "reportlab": "reportlab",
    "sqlalchemy": "sqlalchemy",
}
OPTIONAL_IMPORTS = {"huggingface_hub", "llama_cpp"}


@pytest.fixture
def setup_kwargs(monkeypatch):
    """The keyword arguments ``setup.py`` passes to ``setuptools.setup``."""
    captured = {}
    monkeypatch.setattr(setuptools, "setup", lambda **kwargs: captured.update(kwargs))
    runpy.run_path(str(ROOT / "setup.py"))
    return captured


def _distribution_names(requirement_lines):
    """Lower-cased distribution names from requirement strings (extras and pins removed)."""
    names = set()
    for line in requirement_lines:
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if match:
            names.add(match.group(1).lower().replace("_", "-"))
    return names


def _requirement_lines():
    return [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _third_party_imports():
    """Top-level names imported anywhere in src/ that are neither stdlib nor local modules."""
    local = {path.stem for path in SRC.glob("*.py")} | {
        path.name for path in SRC.iterdir() if path.is_dir()
    }
    found = set()
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return {name for name in found if name not in local and name not in sys.stdlib_module_names}


# ---- setup.py ------------------------------------------------------------------------------

def test_setup_py_names_the_project_and_uses_the_src_layout(setup_kwargs):
    assert setup_kwargs["name"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", setup_kwargs["version"])
    assert setup_kwargs["package_dir"] == {"": "src"}
    assert setup_kwargs["python_requires"].startswith(">=3.10")


def test_setup_py_lists_every_top_level_module_in_src(setup_kwargs):
    on_disk = {path.stem for path in SRC.glob("*.py")}

    assert set(setup_kwargs["py_modules"]) == on_disk


def test_setup_py_ships_the_templates_and_static_files_the_pages_need(setup_kwargs):
    assert setup_kwargs["packages"] == ["web_assets"]
    patterns = setup_kwargs["package_data"]["web_assets"]
    shipped = {path.relative_to(SRC / "web_assets").as_posix()
               for pattern in patterns for path in (SRC / "web_assets").glob(pattern)}

    assert {"templates/analysis.html", "static/style.css"} <= shipped


def test_the_flask_app_finds_its_templates_and_static_files_inside_web_assets():
    app = flask_app.create_app({"TESTING": True})

    assert Path(app.root_path, app.template_folder).resolve() == (SRC / "web_assets" / "templates").resolve()
    assert Path(app.root_path, app.static_folder).resolve() == (SRC / "web_assets" / "static").resolve()
    assert (SRC / "web_assets" / "__init__.py").is_file()


def test_every_third_party_package_the_code_imports_is_an_install_requirement(setup_kwargs):
    imported = _third_party_imports() - OPTIONAL_IMPORTS
    declared = _distribution_names(setup_kwargs["install_requires"])

    assert imported == set(RUNTIME_IMPORTS), "update RUNTIME_IMPORTS if src/ imports something new"
    assert set(RUNTIME_IMPORTS.values()) <= declared


def test_the_dev_extra_carries_the_test_and_security_tooling(setup_kwargs):
    dev = _distribution_names(setup_kwargs["extras_require"]["dev"])

    assert {"pytest", "pytest-cov", "pylint", "pydeps"} <= dev


# ---- requirements.txt ----------------------------------------------------------------------

def test_requirements_pin_every_package_exactly_so_uv_pip_sync_can_rebuild_the_environment():
    lines = _requirement_lines()

    assert lines
    unpinned = [line for line in lines if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._\[\]-]*==\S+", line)]
    assert unpinned == []


def test_requirements_include_runtime_packages_and_the_required_tools(setup_kwargs):
    names = _distribution_names(_requirement_lines())
    wanted = (
        _distribution_names(setup_kwargs["install_requires"])
        | _distribution_names(setup_kwargs["extras_require"]["dev"])
    )

    assert {"pylint", "pydeps"} <= names
    assert wanted <= names


def test_requirements_pull_in_the_transitive_packages_too():
    # uv pip sync installs exactly what is listed, so these indirect dependencies must be
    # present or the app would fail to import in a fresh environment.
    names = _distribution_names(_requirement_lines())

    assert {"werkzeug", "jinja2", "markupsafe", "click", "psycopg-binary", "soupsieve",
            "astroid"} <= names
