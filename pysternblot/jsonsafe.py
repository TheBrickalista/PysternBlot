# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
Strict RFC 8259 JSON output.

Python's json module defaults to allow_nan=True and writes NaN / Infinity /
-Infinity tokens, which are not valid JSON and break strict parsers. Every
file Pystern Blot writes with json.dumps goes through dumps_strict(): any
non-finite float is replaced by null, and allow_nan=False guarantees that
nothing non-finite can slip through unnoticed.

finite_or_none() is also used at the sources (e.g. operation-log values) so
that what is hashed into the log chain is exactly what is saved.
"""

from __future__ import annotations

import json
import math
from typing import Any


def finite_or_none(value: Any) -> Any:
    """Return value with every non-finite float (NaN, ±Infinity) replaced by
    None, recursing into dicts, lists and tuples.

    If nothing needed replacing, the original object is returned unchanged
    (same identity), so callers that hash or compare values see no difference
    for ordinary data.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        out = {k: finite_or_none(v) for k, v in value.items()}
        return value if all(out[k] is value[k] for k in value) else out
    if isinstance(value, (list, tuple)):
        items = [finite_or_none(v) for v in value]
        if all(a is b for a, b in zip(items, value)):
            return value
        return tuple(items) if isinstance(value, tuple) else items
    return value


def dumps_strict(obj: Any, **kwargs: Any) -> str:
    """json.dumps that never emits NaN/Infinity: non-finite floats become
    null, and allow_nan=False makes any other path an error, not bad JSON."""
    return json.dumps(finite_or_none(obj), allow_nan=False, **kwargs)
