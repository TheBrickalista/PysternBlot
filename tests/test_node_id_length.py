# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only

"""Regression guard for the CI hang in issue #N: a pytest.mark.parametrize
value with no explicit id (a ~1 MB bytes literal in test_update_check.py)
produced a node ID over 1,000,000 characters. GitHub Actions' log processing
handles a single line that long extremely poorly, which hung the publish.yml
"Run tests" job even though the test itself ran in under a second locally.

This collects the real suite (no test execution) and fails if any node ID
is unreasonably long. The threshold (NODE_ID_MAX_CHARS) is set well above
any legitimate descriptive test name -- this guards against another
pathological, unlabeled parametrize value, not against verbose test names.

Run from repo root:
    pytest tests/test_node_id_length.py -v
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The bug that prompted this test produced a node ID over 1,000,000 characters.
# 300 is comfortably above the longest legitimate (class + descriptive method
# name + parametrize label) node ID in this suite today, while still catching
# any future pathological growth by orders of magnitude, not just verbosity.
NODE_ID_MAX_CHARS = 300


def _collected_node_ids() -> list[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    lines = result.stdout.splitlines()
    # The collect-only summary footer ("N tests collected in Ns") and blank
    # lines are not node IDs.
    return [
        line for line in lines
        if line and "::" in line and not line[0].isspace()
    ]


def test_no_collected_node_id_exceeds_the_length_cap():
    node_ids = _collected_node_ids()
    assert node_ids, "collection produced no node IDs -- something else is wrong"

    offenders = [
        (len(n), n if len(n) <= 200 else n[:200] + f"...<+{len(n) - 200} more chars>")
        for n in node_ids if len(n) > NODE_ID_MAX_CHARS
    ]
    assert not offenders, (
        f"{len(offenders)} collected node ID(s) exceed {NODE_ID_MAX_CHARS} chars "
        f"-- likely an unlabeled parametrize value (give it an explicit "
        f"pytest.param(..., id=...)):\n" + "\n".join(f"  {n} chars: {s}" for n, s in offenders)
    )
