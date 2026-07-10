"""
src/rag/vector_store.py
────────────────────────
A small, dependency-free persistent vector store.

Records are held in memory and serialised to a single JSON file, so an
index survives across processes with no database to run. Similarity
search is cosine similarity; it uses numpy when available for speed and
falls back to pure Python otherwise.

Alongside the vectors, the store keeps a per-source **manifest** —
ingest timestamp, content hash, and chunk count for every document. That
gives every answer an auditable "as-of" version of the source it was
drawn from, which is exactly what a compliance reviewer needs.

For very large corpora, swap in FAISS behind the same ``add`` / ``search``
interface.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

try:
    import numpy as _np  # optional acceleration
    _HAS_NUMPY = True
except Exception:  # pragma: no cover - numpy usually present in prod
    _np = None
    _HAS_NUMPY = False


class Record:
    """One stored chunk: text, its embedding, and metadata."""

    __slots__ = ("id", "text", "embedding", "source", "meta")

    def __init__(self, id: str, text: str, embedding: List[float],
                 source: str, meta: dict):
        self.id = id
        self.text = text
        self.embedding = embedding
        self.source = source
        self.meta = meta

    def to_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "embedding": self.embedding,
                "source": self.source, "meta": self.meta}

    @classmethod
    def from_dict(cls, d: dict) -> "Record":
        return cls(d["id"], d["text"], d["embedding"], d["source"],
                   d.get("meta", {}))


def _cosine(a: List[float], b: List[float]) -> float:
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class VectorStore:
    """In-memory + JSON-persisted vector store with cosine search."""

    def __init__(self, embedding_signature: str = ""):
        self.records: List[Record] = []
        self.embedding_signature = embedding_signature
        # Per-source provenance: source -> {ingested_at, sha, chunks}.
        self.manifest: dict = {}
        self._matrix = None  # cached numpy matrix, invalidated on write

    # ── mutation ─────────────────────────────────────────────────

    def add(self, id: str, text: str, embedding: List[float],
            source: str, meta: dict) -> None:
        self.records.append(Record(id, text, embedding, source, meta))
        self._matrix = None

    def set_source_meta(self, source: str, ingested_at: str, sha: str,
                        chunks: int) -> None:
        """Record provenance for a source (for audit / as-of versioning)."""
        self.manifest[source] = {
            "ingested_at": ingested_at, "sha": sha, "chunks": chunks}

    def source_version(self, source: str) -> dict:
        """Return {ingested_at, sha, chunks} for a source, or {} if unknown."""
        return self.manifest.get(source, {})

    def remove_source(self, source: str) -> int:
        """Drop all records from ``source``. Returns how many were removed."""
        before = len(self.records)
        self.records = [r for r in self.records if r.source != source]
        self.manifest.pop(source, None)
        self._matrix = None
        return before - len(self.records)

    def sources(self) -> List[str]:
        return sorted({r.source for r in self.records})

    def __len__(self) -> int:
        return len(self.records)

    # ── search ───────────────────────────────────────────────────

    def _ensure_matrix(self):
        if not _HAS_NUMPY:
            return None
        if self._matrix is None and self.records:
            self._matrix = _np.array([r.embedding for r in self.records],
                                     dtype=_np.float32)
        return self._matrix

    def search(self, query_vec: List[float], top_k: int = 5
               ) -> List[Tuple[Record, float]]:
        """Return the top-k (record, cosine_score) pairs, best first."""
        if not self.records:
            return []

        if _HAS_NUMPY:
            mat = self._ensure_matrix()
            q = _np.array(query_vec, dtype=_np.float32)
            qn = _np.linalg.norm(q)
            mn = _np.linalg.norm(mat, axis=1)
            denom = mn * (qn if qn else 1.0)
            denom[denom == 0] = 1.0
            sims = (mat @ q) / denom
            k = min(top_k, len(self.records))
            idx = _np.argpartition(-sims, k - 1)[:k]
            idx = idx[_np.argsort(-sims[idx])]
            return [(self.records[int(i)], float(sims[int(i)])) for i in idx]

        scored = [(r, _cosine(query_vec, r.embedding)) for r in self.records]
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:top_k]

    # ── persistence ──────────────────────────────────────────────

    def save(self, path) -> None:
        """Atomically write the index to ``path`` as JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 2,
            "embedding_signature": self.embedding_signature,
            "manifest": self.manifest,
            "records": [r.to_dict() for r in self.records],
        }
        # Atomic write: temp file in the same dir, then replace.
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    @classmethod
    def load(cls, path) -> "VectorStore":
        """Load an index, or return an empty store if the file is absent."""
        path = Path(path)
        store = cls()
        if not path.exists():
            return store
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        store.embedding_signature = payload.get("embedding_signature", "")
        store.manifest = payload.get("manifest", {})
        store.records = [Record.from_dict(d)
                         for d in payload.get("records", [])]
        return store
