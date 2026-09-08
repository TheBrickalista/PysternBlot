# Pystern Blot
# SPDX-License-Identifier: GPL-3.0-only
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.

"""
Hash-chained operation log verification.

This makes the operation log tamper-evident, not tamper-proof: anyone with
the source can edit an entry and recompute the whole chain from that point
forward. It only detects tampering that was not accompanied by a matching
recomputation of every downstream hash.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from pydantic import BaseModel

from .models import OperationLogEntry, Project

GENESIS_HASH = "0" * 64


def canonical_payload(entry: OperationLogEntry) -> str:
    """Deterministic JSON serialisation of every field except entry_hash.

    prev_hash IS included — that is what binds one entry to the next.
    None fields are serialised as JSON null (never omitted), so two
    otherwise-different entries can never collide.
    """
    payload = entry.model_dump(exclude={"entry_hash"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_entry_hash(entry: OperationLogEntry) -> str:
    return hashlib.sha256(canonical_payload(entry).encode("utf-8")).hexdigest()


def append_log_entry(project: Project, entry: OperationLogEntry) -> OperationLogEntry:
    """Append entry to project.operation_log, chaining it to the prior entry.

    If the log is empty, or the prior entry predates chaining (no
    entry_hash), prev_hash is set to GENESIS_HASH. In the latter case this
    also marks the start of the chained region: verify_log_chain() finds it
    by scanning for the first entry that carries an entry_hash.
    """
    log = project.operation_log
    if log and log[-1].entry_hash is not None:
        entry.prev_hash = log[-1].entry_hash
    else:
        entry.prev_hash = GENESIS_HASH
    entry.entry_hash = compute_entry_hash(entry)
    log.append(entry)
    return entry


class LogChainResult(BaseModel):
    status: str  # "ok" | "broken" | "not_chained" | "partial"
    first_broken_index: Optional[int] = None
    chained_from_index: Optional[int] = None
    n_entries: int
    n_chained: int
    message: str


def verify_log_chain(project: Project) -> LogChainResult:
    log = project.operation_log
    n_entries = len(log)

    if n_entries == 0:
        return LogChainResult(
            status="ok",
            n_entries=0,
            n_chained=0,
            message="Operation log is empty.",
        )

    chained_from_index: Optional[int] = None
    for i, e in enumerate(log):
        if e.entry_hash is not None:
            chained_from_index = i
            break

    if chained_from_index is None:
        return LogChainResult(
            status="not_chained",
            n_entries=n_entries,
            n_chained=0,
            message=f"Operation log predates chain verification ({n_entries} entries).",
        )

    expected_prev = GENESIS_HASH
    n_chained = 0
    for i in range(chained_from_index, n_entries):
        entry = log[i]

        if entry.entry_hash is None:
            return LogChainResult(
                status="broken",
                first_broken_index=i,
                chained_from_index=chained_from_index,
                n_entries=n_entries,
                n_chained=n_chained,
                message=f"Chain broken at entry {i}: entry is missing its hash.",
            )

        if entry.prev_hash != expected_prev:
            return LogChainResult(
                status="broken",
                first_broken_index=i,
                chained_from_index=chained_from_index,
                n_entries=n_entries,
                n_chained=n_chained,
                message=f"Chain broken at entry {i}: prev_hash does not match the preceding entry.",
            )

        if compute_entry_hash(entry) != entry.entry_hash:
            return LogChainResult(
                status="broken",
                first_broken_index=i,
                chained_from_index=chained_from_index,
                n_entries=n_entries,
                n_chained=n_chained,
                message=f"Chain broken at entry {i}: recomputed hash does not match entry_hash.",
            )

        expected_prev = entry.entry_hash
        n_chained += 1

    if chained_from_index == 0:
        return LogChainResult(
            status="ok",
            chained_from_index=0,
            n_entries=n_entries,
            n_chained=n_chained,
            message=f"Operation log chain verified ({n_chained} entries).",
        )

    return LogChainResult(
        status="partial",
        chained_from_index=chained_from_index,
        n_entries=n_entries,
        n_chained=n_chained,
        message=(
            f"Operation log chain verified from entry {chained_from_index} onward "
            f"({n_chained} of {n_entries} entries chained)."
        ),
    )
