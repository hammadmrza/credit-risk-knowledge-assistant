"""
src/rag/audit.py
─────────────────
Append-only audit trail for the knowledge assistant.

Every question, the answer given, and the exact sources cited (with the
version of each source document) are written as one JSON line. In a
regulated setting this is the paper trail: you can show an examiner what
the assistant told whom, when, and from which version of which policy.

The log is append-only JSONL — cheap to write, trivial to grep, and
easy to load into pandas for review. It never blocks or raises into the
caller: an audit-write failure is logged, not propagated.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)

_write_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AuditLog:
    """Append-only JSONL audit log of question/answer/citation events."""

    def __init__(self, path, enabled: bool = True):
        self.path = Path(path)
        self.enabled = enabled
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self,
               question: str,
               answer: str,
               sources: List[dict],
               backend: str,
               grounded: bool,
               user: Optional[str] = None) -> Optional[dict]:
        """Append one event. Returns the written record (or None if disabled).

        Args:
            question: The user's question.
            answer:   The answer returned.
            sources:  List of {source, citation, score, version} dicts.
            backend:  Which backend produced the answer.
            grounded: Whether the answer was grounded (vs. a refusal).
            user:     Optional user/actor identifier.
        """
        if not self.enabled:
            return None
        event = {
            "ts": _now_iso(),
            "user": user or "anonymous",
            "question": question,
            "answer": answer,
            "grounded": grounded,
            "backend": backend,
            "sources": sources,
        }
        try:
            with _write_lock:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:  # never break a query because logging failed
            log.warning("Audit write failed: %s", e)
        return event

    def tail(self, n: int = 20) -> List[dict]:
        """Return the last ``n`` audit events (most recent last)."""
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as f:
            lines = f.readlines()
        out = []
        for line in lines[-n:]:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def count(self) -> int:
        """Total number of logged events."""
        if not self.path.exists():
            return 0
        with open(self.path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
