"""Packaging for the Module 5 Grad Cafe analysis app.

    pip install -e .            # editable install (what development and CI use)
    pip install -e ".[dev]"     # ... plus the test, lint and security tooling
    pip install .               # a regular install; the wheel includes the web assets

Why this file exists: the code in ``src/`` imports its own modules by bare name
(``import query_data``). Installing the project puts ``src/`` on the import path the same
way everywhere -- a local shell, pytest, GitHub Actions -- so imports stop depending on
the directory you happen to be standing in or on a hand-set ``PYTHONPATH``. An editable
install does it without copying anything, and ``uv`` can read the dependency lists below.

Dependency lists here use loose lower bounds (what the code needs). The exact versions
that were tested are pinned in ``requirements.txt``.
"""

from pathlib import Path

from setuptools import setup

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"

setup(
    name="gradcafe-analysis",
    version="5.0.0",
    description="Grad Cafe applicant analysis: Flask page, PostgreSQL loader and secure SQL layer",
    long_description=(HERE / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    author="Caleb Gevertz",
    python_requires=">=3.10",
    package_dir={"": "src"},
    # Every top-level module in src/ (the code imports them by bare name).
    py_modules=sorted(path.stem for path in SRC.glob("*.py")),
    # Jinja templates and CSS live in a package so the wheel carries them.
    packages=["web_assets"],
    package_data={"web_assets": ["templates/*.html", "static/*.css"]},
    install_requires=[
        "beautifulsoup4>=4.12",
        "Flask>=3.0",
        "psycopg[binary]>=3.2",
        "SQLAlchemy>=2.0",
    ],
    extras_require={
        "dev": [
            "pydeps>=3.0",
            "pylint>=4.0",
            "pypdf>=4.0",
            "pytest>=8.0",
            "pytest-cov>=5.0",
            "setuptools>=70",
        ],
    },
)
