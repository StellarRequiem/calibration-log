"""Hash-linked, append-only audit chain — tamper-evident provenance.

Single source of truth: this re-exports the audit primitive from verity-core (the SPINE),
so the chain is defined ONCE for the whole ecosystem rather than re-vendored. This module
used to be a byte-identical copy of ``verity/audit.py``; importing it keeps calibration-log
and verity-core provably in lockstep (one implementation, one place to fix).
"""
from verity.audit import (  # noqa: F401  (re-export — public API preserved)
    GENESIS,
    AuditChain,
    _now_iso,
    entry_hash,
)

__all__ = ["GENESIS", "AuditChain", "entry_hash", "_now_iso"]
