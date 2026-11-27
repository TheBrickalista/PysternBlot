# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""Conformance with Pyblication's plugin protocol v1 (Pyblication's
docs/plugin-protocol.md). PysternBlot can't import Pyblication, so the
rules Pyblication enforces are encoded here.
"""

from __future__ import annotations

import importlib
import json
import ntpath
import os
import re
import tomllib
from pathlib import Path, PurePosixPath

import pytest

import test_pyblication_plugin as base
from pysternblot import plugin

# The workspace fixtures of the plugin tests (a project with two blots and an
# overlay, and a logged export).
ws = base.ws
exported = base.exported

ROOT = Path(__file__).resolve().parents[1]
ROLES = {"project", "asset", "raw", "sidecar"}
MAX_PROVENANCE_BYTES = 64 * 1024
HASH = re.compile(r"^[0-9a-f]{64}$")
EXT = re.compile(r"^\.[a-z0-9]+$")
WINDOWS_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}


def _valid_part(part: str) -> bool:
    if part in ("", ".", ".."):
        return False
    if WINDOWS_FORBIDDEN.search(part) or part[-1] in " .":
        return False
    return part.split(".")[0].upper() not in WINDOWS_RESERVED


def _valid_name(name: str) -> bool:
    """A relative POSIX path whose parts are valid file names on Windows and
    POSIX (Pyblication extracts tree members under these names)."""
    if not name or name.startswith("/") or "\\" in name:
        return False
    return all(_valid_part(p) for p in PurePosixPath(name).parts)


def check_describe(d) -> None:
    assert isinstance(d, dict)
    assert d["protocol"] == 1 and not isinstance(d["protocol"], bool)
    for key in ("name", "version", "app_name"):
        assert isinstance(d[key], str) and d[key].strip(), key
    assert isinstance(d["extensions"], list) and d["extensions"]
    assert all(isinstance(e, str) and EXT.match(e) for e in d["extensions"])
    assert callable(d["identify"])
    assert d.get("open_project") is None or callable(d["open_project"])


def check_identification(r) -> None:
    assert isinstance(r, dict)
    for key in ("project_id", "project_name"):
        assert isinstance(r[key], str) and r[key].strip(), key
    members = r["members"]
    assert isinstance(members, list) and members
    names = []
    for m in members:
        path = m["path"]
        assert isinstance(path, str) and (os.path.isabs(path) or ntpath.isabs(path)), path
        assert m["role"] in ROLES, m
        if "sha256" in m and m["sha256"] is not None:
            assert HASH.match(m["sha256"]), m
        name = m.get("name") or PurePosixPath(path).name
        assert _valid_name(name), name
        names.append(name)
    assert len(names) == len(set(names)), "member names must be unique"
    assert any(m["role"] == "project" for m in members)
    provenance = r["provenance"]
    assert isinstance(provenance, dict)
    size = len(json.dumps(provenance, sort_keys=True).encode("utf-8"))  # JSON-safe
    assert size <= MAX_PROVENANCE_BYTES


def test_describe_conforms():
    check_describe(plugin.describe())
    d = plugin.describe()
    assert (d["name"], d["app_name"], d["extensions"]) == (
        "pysternblot",
        "PysternBlot",
        [".svg", ".pdf", ".png"],
    )


def test_entry_point_is_registered():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    eps = meta["project"]["entry-points"]["pyblication.plugins"]
    assert eps == {"pysternblot": "pysternblot.plugin:describe"}
    module, attr = eps["pysternblot"].split(":")
    describe = getattr(importlib.import_module(module), attr)
    assert describe()["name"] == "pysternblot"  # = the entry point name


def test_identification_conforms(ws, exported):
    _, _, export, _ = exported
    check_identification(plugin.identify(str(export)))


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        (lambda r: r["members"][0].update(path="project.json"), "absolute"),
        (lambda r: r["members"][0].update(role="raw"), "project member"),
        (lambda r: r["members"][1].update(name="project.json"), "unique"),
        (lambda r: r["members"][1].update(name="../x"), "name"),
        (lambda r: r["members"][1].update(sha256="ABC"), "sha256"),
        (lambda r: r["provenance"].update(big="x" * MAX_PROVENANCE_BYTES), "size"),
        (lambda r: r["provenance"].update(obj=object()), "JSON-safe"),
    ],
)
def test_checks_catch_violations(ws, exported, change, rule):
    """The encoded rules are not vacuous: each broken rule is caught."""
    _, _, export, _ = exported
    r = plugin.identify(str(export))
    change(r)
    with pytest.raises((AssertionError, TypeError)):
        check_identification(r)
