# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
The PR workflow's docs job builds the docs the way Read the Docs does.

Same Python version as .readthedocs.yaml, same requirements file, same Sphinx
source directory, warnings as errors. A docs dependency that needs a newer
Python (e.g. sphinx 9.2 needs Python >= 3.13) then fails in the PR instead of
on Read the Docs.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RTD = ROOT / ".readthedocs.yaml"
PR_WORKFLOW = ROOT / ".github" / "workflows" / "pytest.yml"


def _rtd() -> dict:
    return yaml.safe_load(RTD.read_text(encoding="utf-8"))


def _docs_job() -> dict:
    jobs = yaml.safe_load(PR_WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    assert "docs" in jobs, "pytest.yml has no docs job"
    return jobs["docs"]


def _setup_python_version(job) -> str:
    (step,) = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/setup-python@")]
    return str(step["with"]["python-version"])


def _run_lines(job) -> list[str]:
    return [s["run"] for s in job["steps"] if "run" in s]


def test_docs_job_uses_the_read_the_docs_python_version():
    rtd_python = str(_rtd()["build"]["tools"]["python"])
    assert _setup_python_version(_docs_job()) == rtd_python


def test_docs_job_installs_the_read_the_docs_requirements():
    rtd_reqs = [i["requirements"] for i in _rtd()["python"]["install"] if "requirements" in i]
    assert rtd_reqs == ["docs/requirements.txt"]
    runs = _run_lines(_docs_job())
    assert any("pip install" in r and "-r docs/requirements.txt" in r for r in runs), runs


def test_docs_job_builds_the_read_the_docs_source_with_warnings_as_errors():
    conf = Path(_rtd()["sphinx"]["configuration"])
    assert conf == Path("docs/conf.py")
    build = [r for r in _run_lines(_docs_job()) if "sphinx" in r]
    assert len(build) == 1, build
    args = build[0].split()
    assert args[:3] == ["python", "-m", "sphinx"]
    assert "-W" in args and "html" in args
    assert str(conf.parent) in args            # the source directory RTD builds
