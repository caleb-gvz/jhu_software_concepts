"""The GitHub Actions workflow enforces the Module 5 checks as four separate jobs.

The workflow lives at the repository root (``.github/workflows/ci.yml``), next to
``module_5/``. These checks read it as text, so they need no YAML library.
"""

import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"

pytestmark = [
    pytest.mark.web,
    pytest.mark.skipif(not WORKFLOW.is_file(), reason="ci.yml is outside this folder layout"),
]


def _jobs():
    """``{job name: its text}`` for the top-level keys under ``jobs:``."""
    text = WORKFLOW.read_text(encoding="utf-8")
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"\n  ([a-z][a-z0-9-]*):\n", "\n" + body)
    return dict(zip(parts[1::2], parts[2::2]))


def test_the_workflow_runs_on_every_push_and_pull_request():
    triggers = WORKFLOW.read_text(encoding="utf-8").split("\njobs:\n", 1)[0]

    assert re.search(r"^on:\n  push:", triggers, re.MULTILINE)
    assert re.search(r"^  pull_request:", triggers, re.MULTILINE)
    assert "branches" not in triggers and "paths" not in triggers      # no filter: every push


def test_there_are_four_separate_jobs():
    assert sorted(_jobs()) == ["dependency-graph", "pylint", "pytest", "snyk"]


def test_every_job_runs_inside_module_5_on_python_3_12():
    for name, text in _jobs().items():
        assert "working-directory: module_5" in text, name
        assert 'python-version: "3.12"' in text, name


def test_pylint_job_fails_when_the_score_is_below_ten():
    job = _jobs()["pylint"]

    assert "pylint src --fail-under=10" in job
    assert "requirements.txt" in job


def test_dependency_graph_job_installs_graphviz_generates_the_svg_and_fails_if_missing():
    job = _jobs()["dependency-graph"]

    assert "graphviz" in job
    assert "pydeps src/flask_app.py --noshow -T svg -o dependency.svg" in job
    assert re.search(r"test -s dependency\.svg", job)       # exists AND is not empty
    assert "upload-artifact" in job


def test_snyk_job_runs_snyk_test_and_reads_the_token_from_a_secret():
    job = _jobs()["snyk"]

    assert "snyk test" in job
    assert "secrets.SNYK_TOKEN" in job
    assert "SNYK_TOKEN: " in job and "ghp_" not in job       # never a literal token


def test_pytest_job_provisions_the_roles_and_runs_the_marked_suite_with_the_coverage_gate():
    job = _jobs()["pytest"]

    assert "postgres:" in job and "services:" in job
    assert "src/db_setup.sql" in job                         # creates owner + app roles
    assert "TEST_DATABASE_URL" in job and "TEST_APP_DATABASE_URL" in job
    assert 'pytest -m "web or buttons or analysis or db or integration"' in job
    assert "continue-on-error" not in job                    # a failing test fails the build


def test_the_only_literal_passwords_belong_to_throwaway_ci_containers():
    text = WORKFLOW.read_text(encoding="utf-8")
    passwords = set(re.findall(r"(?:PASSWORD|password)[A-Za-z_]*:\s*(\S+)", text))

    assert all("secrets." in value or value.startswith("ci-") or value == "postgres"
               for value in passwords), passwords
