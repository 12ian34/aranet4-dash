---
name: use-uv
description: Enforces uv for all Python package management and script execution. Use when installing packages, managing dependencies, creating venvs, or running Python scripts.
---

# Python: always use uv

- Use `uv` for all Python operations — never raw `pip`, `pip install`, `python -m venv`, or `virtualenv`.
- Dependencies go in `pyproject.toml`, not `requirements.txt`.
- `uv sync` to install/update deps. `uv add <pkg>` to add a new dependency.
- `uv run script.py` to execute scripts (handles venv automatically).
- In crontab/systemd, use full path: `$HOME/.local/bin/uv run`.
- Install uv itself: `curl -LsSf https://astral.sh/uv/install.sh | sh`
