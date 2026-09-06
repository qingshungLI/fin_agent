#!/usr/bin/env python3
"""Register the project-local RQAlpha mod in the active virtual environment."""

from __future__ import annotations

import site
import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[3]
    expected_python = (project_root / ".venv/bin/python").resolve()
    if Path(sys.executable).resolve() != expected_python:
        raise SystemExit(f"use the project interpreter: {expected_python}")

    package = project_root / "rqalpha_mod_local_rqdata/__init__.py"
    if not package.is_file():
        raise SystemExit(f"local RQAlpha mod is missing: {package}")

    candidates = [Path(path) for path in site.getsitepackages()]
    target_dir = next(
        (path for path in candidates if path.is_dir() and project_root / ".venv" in path.parents),
        None,
    )
    if target_dir is None:
        raise SystemExit("could not locate the project virtual environment site-packages")

    pth_path = target_dir / "rqalpha_local_project.pth"
    expected = f"{project_root}\n"
    if not pth_path.exists() or pth_path.read_text() != expected:
        pth_path.write_text(expected)
        action = "registered"
    else:
        action = "already registered"
    print(f"local RQAlpha mod {action}: {pth_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
