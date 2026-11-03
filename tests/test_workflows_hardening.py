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


def test_runner_images_pinned(workflow):
    """A *-latest label moves to a new OS under us; upgrades must be deliberate."""
    for job_id, job in _jobs(workflow):
        labels = job.get("runs-on")
        if labels is None:  # reusable-workflow call; the callee is checked
            continue
        for label in [labels] if isinstance(labels, str) else labels:
            assert not str(label).endswith("-latest"), (
                f"{workflow.name}:{job_id} runs-on {label!r}; pin a versioned image"
            )


def test_no_event_expressions_in_run_blocks(workflow):
    """Event data (tag names, titles, ...) must reach shell only through env."""
    for job_id, step in _steps(workflow):
        run = step.get("run")
        if run is not None:
            assert not EVENT_EXPR.search(run), (
                f"{workflow.name}:{job_id} step {step.get('name')!r} expands "
                f"github.event.* inside run:; pass it through env instead"
            )


EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def _uv_floor():
    """The floor in [tool.uv] required-version, which must be a bare >=x.y.z.

    An == pin or an upper bound makes Dependabot's bundled uv fail every
    uv.lock update with tool_version_not_supported once it moves past it.
    """
    import tomllib

    spec = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "tool"]["uv"]["required-version"]
    m = re.fullmatch(r">=\s*(\d+\.\d+\.\d+)", spec.strip())
    assert m, f"required-version {spec!r} must be a floor only (>=x.y.z)"
    return tuple(int(x) for x in m.group(1).split("."))


def _setup_uv_versions():
    for wf in WORKFLOWS:
        for job_id, step in _steps(wf):
            if str(step.get("uses", "")).startswith("astral-sh/setup-uv@"):
                yield wf.name, job_id, (step.get("with") or {}).get("version")


def test_setup_uv_pins_one_exact_version_at_or_above_floor():
    """CI never derives uv from pyproject.toml: every setup-uv step pins the
    same exact version, at or above the required-version floor."""
    found = list(_setup_uv_versions())
    assert found, "no setup-uv steps found"
    for name, job_id, version in found:
        assert version is not None and EXACT_VERSION.match(str(version)), (
            f"{name}:{job_id} setup-uv needs an exact version: x.y.z (got {version!r})"
        )
    versions = {str(v) for _, _, v in found}
    assert len(versions) == 1, f"setup-uv steps pin different uv versions: {sorted(versions)}"
    pinned = tuple(int(x) for x in versions.pop().split("."))
    assert pinned >= _uv_floor(), "CI uv pin is below [tool.uv] required-version"
