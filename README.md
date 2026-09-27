# jhu_software_concepts

Coursework for **Modern Software Concepts in Python** (Johns Hopkins University).

**Student:** Caleb Gevertz (JHED: cgevert1)

## Repo layout

Each assignment lives in its own self-contained module folder — its own
code, virtual environment, `requirements.txt`, README, and data outputs.
Modules don't share code or depend on files outside their own folder.

| Module | Assignment | Details |
|---|---|---|
| [`module_1/`](module_1/) | Personal Portfolio Flask App | [README.txt](module_1/README.txt) |
| [`module_2/`](module_2/) | Web Scraping (Grad Cafe) | [readme.txt](module_2/readme.txt) |
| [`module_3/`](module_3/) | Database Queries, SQLAlchemy, Flask | [README.md](module_3/README.md) |
| [`module_4/`](module_4/) | Pytest, CI and Sphinx docs | [README.md](module_4/README.md) · [docs](https://jhu-sphinx-module-4.readthedocs.io/en/latest/) |

See each module's own README for setup, run instructions, and the
approach used (data structures, algorithms, control flow, known bugs).

## Conventions across modules

- Python 3.10+
- Each module has its own virtual environment and a `requirements.txt` that
  fully reconstructs it
- No hard-coded local absolute paths, secrets, or API keys
- Git history reflects incremental development, not a single end-of-project
  commit
- `.github/workflows/tests.yml` runs the Module 4 test suite on every push, and
  `.readthedocs.yaml` builds the Module 4 Sphinx docs
