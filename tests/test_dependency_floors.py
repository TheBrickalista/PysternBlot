"""The floors in pyproject.toml must be exactly what the `minimum` CI job tests.

That job installs ci/requirements-min.txt (compiled from
ci/requirements-min.in) on the lowest supported Python. If a floor moves
without the pin (or the reverse), the job would be testing versions other
than the ones pip users can actually get.
"""

import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 has no stdlib tomllib
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
MIN_IN = ROOT / "ci" / "requirements-min.in"
MIN_TXT = ROOT / "ci" / "requirements-min.txt"

pytestmark = pytest.mark.skipif(
    not MIN_IN.exists(),
    reason="source checkout only (ci/ is not shipped in the wheel)",
)


def _floors():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    floors = {}
    for spec in data["project"]["dependencies"]:
        req = Requirement(spec)
        specs = list(req.specifier)
        assert len(specs) == 1 and specs[0].operator == ">=", (
            f"{spec!r}: runtime dependencies must have a single >= floor"
        )
        floors[canonicalize_name(req.name)] = Version(specs[0].version)
    return floors


def _pins(path):
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)", line)
        if m:
            pins[canonicalize_name(m.group(1))] = Version(m.group(2))
    return pins


def test_every_floor_is_pinned_in_requirements_min_in():
    pins = _pins(MIN_IN)
    for name, floor in _floors().items():
        assert name in pins, f"{name} has a floor but no pin in {MIN_IN.name}"
        assert pins[name] == floor, (
            f"{name}: pyproject floor {floor} != {MIN_IN.name} pin {pins[name]}"
        )


def test_compiled_lock_matches_floors():
    """Catches editing requirements-min.in without recompiling the .txt."""
    locked = _pins(MIN_TXT)
    for name, floor in _floors().items():
        assert locked.get(name) == floor, (
            f"{name}: {MIN_TXT.name} has {locked.get(name)}, floor is {floor}"
        )
