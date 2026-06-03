"""Hash-linked, append-only audit chain — tamper-evident provenance.

Each entry commits to the previous one by hash, so any after-the-fact edit to an
earlier record breaks the chain and ``verify()`` catches it. The timestamp is
recorded but deliberately NOT part of the hash, so re-stamping can't silently
rewrite the links.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "GENESIS"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def entry_hash(seq: int, prev_hash: str, actor: str,
               event_type: str, event_data: dict) -> str:
    canonical = json.dumps(
        {"seq": seq, "prev_hash": prev_hash, "actor": actor,
         "event_type": event_type, "event_data": event_data},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditChain:
    """Append-only JSONL chain at ``path``. Thread-safe within a process."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line
                in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def append(self, event_type: str, event_data: dict, actor: str = "agent") -> dict:
        with self._lock:
            rows = self.read()
            seq = len(rows)
            prev = rows[-1]["entry_hash"] if rows else GENESIS
            h = entry_hash(seq, prev, actor, event_type, event_data)
            entry = {"seq": seq, "prev_hash": prev, "actor": actor,
                     "event_type": event_type, "event_data": event_data,
                     "timestamp": _now_iso(), "entry_hash": h}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return entry

    def verify(self) -> tuple[bool, str]:
        prev = GENESIS
        rows = self.read()
        for i, r in enumerate(rows):
            if r.get("seq") != i:
                return False, f"seq mismatch at index {i}"
            if r.get("prev_hash") != prev:
                return False, f"broken link at seq {i}"
            if r.get("entry_hash") != entry_hash(
                    i, prev, r["actor"], r["event_type"], r["event_data"]):
                return False, f"hash mismatch at seq {i} — tampered"
            prev = r["entry_hash"]
        return True, f"intact: {len(rows)} entries"
