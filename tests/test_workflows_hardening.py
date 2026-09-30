"""Guard the GitHub Actions hardening (least-privilege tokens, no persisted
checkout credentials, SHA-pinned actions, no event data spliced into shell).

PyYAML (YAML 1.1) parses the bare key `on:` as the boolean True, so the
trigger block is read as data[True]; nothing here needs it.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml"))

pytestmark = pytest.mark.skipif(
    not WORKFLOWS,
    reason="source checkout only (workflows are not shipped in the wheel)",
)

# The only job-level token widenings allowed, keyed by (workflow file, job id).
# Adding a job that needs more than the top-level `contents: read` means
# adding it here, deliberately.
ALLOWED_JOB_PERMISSIONS = {
    ("codeql.yml", "analyze"): {"security-events": "write", "contents": "read"},
    ("publish.yml", "publish"): {"id-token": "write"},
    ("publish.yml", "build-macos"): {"contents": "write"},
    ("publish.yml", "build-windows"): {"contents": "write"},
    ("build-macos.yml", "build-macos"): {"contents": "write"},
    ("build-windows.yml", "build-windows"): {"contents": "write"},
}

SHA_PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
EVENT_EXPR = re.compile(r"\$\{\{[^}]*\bgithub\.event\.")


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _jobs(path):
    return _load(path)["jobs"].items()


def _steps(path):
    for job_id, job in _jobs(path):
        for step in job.get("steps", []):
            yield job_id, step


@pytest.fixture(params=WORKFLOWS, ids=lambda p: p.name)
def workflow(request):
    return request.param


def test_workflows_found():
    names = {p.name for p in WORKFLOWS}
    assert {"publish.yml", "pytest.yml", "codeql.yml"} <= names


def test_top_level_permissions_read_only(workflow):
    data = _load(workflow)
    assert True in data, "PyYAML should read the `on:` key as True"
    assert data.get("permissions") == {"contents": "read"}


def test_job_permissions_only_from_allowlist(workflow):
    for job_id, job in _jobs(workflow):
        if "permissions" not in job:
            continue
        key = (workflow.name, job_id)
        assert key in ALLOWED_JOB_PERMISSIONS, (
            f"{workflow.name}:{job_id} widens permissions without an allowlist entry"
        )
        assert job["permissions"] == ALLOWED_JOB_PERMISSIONS[key], (
            f"{workflow.name}:{job_id} permissions differ from the allowlist"
        )


def test_allowlist_entries_exist():
    """A stale allowlist entry would silently permit a future widening."""
    for name, job_id in ALLOWED_JOB_PERMISSIONS:
        jobs = dict(_jobs(WORKFLOW_DIR / name))
        assert "permissions" in jobs.get(job_id, {}), f"stale entry {name}:{job_id}"


def test_checkout_does_not_persist_credentials(workflow):
    for job_id, step in _steps(workflow):
        if str(step.get("uses", "")).startswith("actions/checkout@"):
            assert (step.get("with") or {}).get("persist-credentials") is False, (
                f"{workflow.name}:{job_id} checkout must set persist-credentials: false"
            )


def test_actions_pinned_to_full_sha(workflow):
    refs = [step["uses"] for _, step in _steps(workflow) if "uses" in step]
    # Job-level `uses:` calls a reusable workflow; local ones (./...) are
    # part of this repo and have no ref to pin.
    refs += [
        job["uses"]
        for _, job in _jobs(workflow)
        if "uses" in job and not job["uses"].startswith("./")
    ]
    for ref in refs:
        assert SHA_PINNED.match(ref), f"{workflow.name}: {ref!r} is not pinned to a 40-char SHA"


def test_no_event_expressions_in_run_blocks(workflow):
    """Event data (tag names, titles, ...) must reach shell only through env."""
    for job_id, step in _steps(workflow):
        run = step.get("run")
        if run is not None:
            assert not EVENT_EXPR.search(run), (
                f"{workflow.name}:{job_id} step {step.get('name')!r} expands "
                f"github.event.* inside run:; pass it through env instead"
            )
