"""
src/rag/pipeline.py
────────────────────
The RAG orchestrator: ingest documents, then answer questions grounded
in what was ingested.

FLOW
────
    ingest:  load → chunk → embed → store (persisted to disk, with a
             per-source manifest recording ingest time + content hash)
    query:   embed question → retrieve top-k chunks → build a grounded
             prompt → generate an answer with citations → write an
             audit-trail event

GROUNDING & ANTI-HALLUCINATION
──────────────────────────────
Answers must come *only* from retrieved passages. Every passage is
numbered and the model is told to cite the number(s) it used and to say
it doesn't know when the context is insufficient. If nothing retrieves
above ``RAG_MIN_SCORE`` the pipeline refuses to call the model at all and
returns a clean "not found in the knowledge base" answer — so the system
never invents an answer the archive can't support.

When Ollama is offline, ``query`` still works: it returns an *extractive*
answer (the most relevant passages verbatim) with the same citations, so
the retrieval half of the system is fully usable with no LLM.

AUDITABILITY
────────────
Each query is written to an append-only audit log (question, answer,
cited sources + their document versions), and every retrieved source
carries the ingest timestamp / content hash of the document version it
came from.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import config
from src.rag.audit import AuditLog
from src.rag.chunker import chunk_document
from src.rag.embeddings import Embedder
from src.rag.loaders import load_dir, load_file
from src.rag.ollama_http import post_json
from src.rag.vector_store import Record, VectorStore

log = logging.getLogger(__name__)


# ── Result types ─────────────────────────────────────────────────

@dataclass
class RetrievedChunk:
    """A passage returned for a query, with its relevance score."""
    source: str
    text: str
    score: float
    breadcrumb: str = ""
    version: dict = field(default_factory=dict)   # {ingested_at, sha, chunks}

    @property
    def citation(self) -> str:
        return self.source + (f" › {self.breadcrumb}" if self.breadcrumb else "")

    def to_dict(self) -> dict:
        return {"source": self.source, "citation": self.citation,
                "score": self.score, "version": self.version}


@dataclass
class Answer:
    """The result of a query."""
    text: str
    sources: List[RetrievedChunk] = field(default_factory=list)
    grounded: bool = True           # False when nothing relevant was found
    backend: str = "template"       # 'ollama' | 'extractive' | 'template'

    def __str__(self) -> str:
        out = [self.text]
        if self.sources:
            out.append("\nSources:")
            for i, s in enumerate(self.sources, 1):
                out.append(f"  [{i}] {s.citation}  (relevance {s.score:.2f})")
        return "\n".join(out)


# ── System prompt for grounded answering ─────────────────────────

_SYSTEM_PROMPT = (
    "You are a knowledge assistant for a financial institution. Answer the "
    "user's question using ONLY the numbered context passages provided. "
    "Follow these rules strictly:\n"
    "1. Base every statement on the passages. Do not use outside knowledge.\n"
    "2. Cite the passage number(s) you used in square brackets, e.g. [1], [2].\n"
    "3. If the passages do not contain the answer, say: "
    "\"I could not find that in the knowledge base.\" Do not guess.\n"
    "4. Be concise, accurate, and quote figures/thresholds exactly as written.\n"
    "5. Never fabricate policy numbers, dates, or names."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RAGPipeline:
    """Ingest documents and answer questions grounded in them.

    Args:
        index_path: Where the vector index is persisted (JSON).
        prefer_ollama: Use Ollama for embeddings/generation when available.
        chunk_size / overlap: Chunking parameters (default from config).
        audit: Enable the audit trail (default from config.AUDIT_ENABLED).
    """

    def __init__(self,
                 index_path=None,
                 prefer_ollama: bool = True,
                 chunk_size: Optional[int] = None,
                 overlap: Optional[int] = None,
                 audit: Optional[bool] = None):
        self.index_path = Path(index_path or config.RAG_INDEX_PATH)
        self.chunk_size = chunk_size or config.RAG_CHUNK_SIZE
        self.overlap = overlap if overlap is not None else config.RAG_CHUNK_OVERLAP
        self.embedder = Embedder(prefer_ollama=prefer_ollama)
        self.store = VectorStore.load(self.index_path)
        audit_enabled = getattr(config, "AUDIT_ENABLED", True) if audit is None else audit
        self.audit = AuditLog(getattr(config, "AUDIT_LOG_PATH",
                                      self.index_path.parent / "audit_log.jsonl"),
                              enabled=audit_enabled)
        self._check_signature()

    # ── signature guard ──────────────────────────────────────────

    def _check_signature(self) -> None:
        """Warn if the on-disk index was built with a different embedder."""
        sig = self.embedder.signature
        if len(self.store) and self.store.embedding_signature and \
                self.store.embedding_signature != sig:
            log.warning(
                "Index was built with embedding backend '%s' but the active "
                "backend is '%s'. Queries may be inaccurate — re-run ingest "
                "with reset=True to rebuild.",
                self.store.embedding_signature, sig)

    # ── ingestion ────────────────────────────────────────────────

    def _chunk_id(self, source: str, index: int, text: str) -> str:
        h = hashlib.md5(f"{source}::{index}::{text}".encode()).hexdigest()[:12]
        return f"{source}#{index}#{h}"

    def _add_document(self, text: str, source: str, meta: dict) -> int:
        # Replace any prior version of this source for idempotent re-ingest.
        self.store.remove_source(source)
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        ingested_at = _now_iso()
        chunks = chunk_document(text, source, self.chunk_size, self.overlap,
                                base_meta=meta)
        for ch in chunks:
            vec = self.embedder.embed(ch.text)
            self.store.add(
                id=self._chunk_id(source, ch.index, ch.text),
                text=ch.text, embedding=vec, source=source,
                meta={"index": ch.index, "breadcrumb": ch.meta.get("breadcrumb", ""),
                      "ingested_at": ingested_at, "sha": sha,
                      **{k: v for k, v in meta.items() if k != "path"}},
            )
        self.store.set_source_meta(source, ingested_at, sha, len(chunks))
        return len(chunks)

    def ingest(self, path, reset: bool = False) -> dict:
        """Ingest a single file. Re-ingesting a file replaces its chunks."""
        if reset:
            self.reset(save=False)
        doc = load_file(path)
        if not doc:
            log.warning("Nothing ingested from %s (unsupported or empty).", path)
            return {"files": 0, "chunks": 0, "sources": []}
        n = self._add_document(doc.text, doc.source, doc.meta)
        self._finalize()
        return {"files": 1, "chunks": n, "sources": [doc.source]}

    def ingest_dir(self, directory, recursive: bool = True,
                   suffixes=None, reset: bool = False) -> dict:
        """Ingest every supported file under a directory."""
        if reset:
            self.reset(save=False)
        docs = load_dir(directory, recursive=recursive, suffixes=suffixes)
        total = 0
        srcs = []
        for doc in docs:
            total += self._add_document(doc.text, doc.source, doc.meta)
            srcs.append(doc.source)
        self._finalize()
        log.info("Ingested %d files → %d chunks (backend=%s).",
                 len(docs), total, self.embedder.backend)
        return {"files": len(docs), "chunks": total, "sources": srcs}

    def ingest_text(self, text: str, source: str) -> dict:
        """Ingest raw text under a synthetic source name."""
        n = self._add_document(text, source, {"suffix": ".txt"})
        self._finalize()
        return {"files": 1, "chunks": n, "sources": [source]}

    def _finalize(self) -> None:
        self.store.embedding_signature = self.embedder.signature
        self.store.save(self.index_path)

    def reset(self, save: bool = True) -> None:
        """Delete all indexed content."""
        self.store = VectorStore(embedding_signature=self.embedder.signature)
        if save:
            self.store.save(self.index_path)

    # ── retrieval ────────────────────────────────────────────────

    def retrieve(self, question: str, top_k: Optional[int] = None,
                 min_score: Optional[float] = None) -> List[RetrievedChunk]:
        """Return the most relevant chunks for a question."""
        top_k = top_k or config.RAG_TOP_K
        min_score = config.RAG_MIN_SCORE if min_score is None else min_score
        if not len(self.store):
            return []
        qvec = self.embedder.embed(question)
        hits = self.store.search(qvec, top_k=top_k)
        out = []
        for rec, score in hits:
            if score < min_score:
                continue
            out.append(RetrievedChunk(
                source=rec.source, text=rec.text, score=round(score, 4),
                breadcrumb=rec.meta.get("breadcrumb", ""),
                version=self.store.source_version(rec.source)))
        return out

    # ── generation ───────────────────────────────────────────────

    def _build_context(self, chunks: List[RetrievedChunk]) -> str:
        parts = []
        budget = config.RAG_MAX_CONTEXT
        for i, c in enumerate(chunks, 1):
            block = f"[{i}] (source: {c.citation})\n{c.text}"
            if budget - len(block) < 0:
                break
            parts.append(block)
            budget -= len(block)
        return "\n\n".join(parts)

    def _generate_ollama(self, question: str, context: str) -> Optional[str]:
        prompt = (
            f"Context passages:\n{context}\n\n"
            f"Question: {question}\n\n"
            "Answer using only the passages above, citing passage numbers."
        )
        url = f"{config.OLLAMA_BASE_URL}/api/generate"
        data = post_json(url, {
            "model": config.OLLAMA_MODEL,
            "prompt": prompt,
            "system": _SYSTEM_PROMPT,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 700, "top_p": 0.9},
        }, timeout=config.OLLAMA_TIMEOUT)
        if not data:
            return None
        resp = (data.get("response") or "").strip()
        return resp or None

    def _extractive_answer(self, chunks: List[RetrievedChunk]) -> str:
        """LLM-free answer: stitch the top passages together with citations."""
        lines = [
            "Ollama is offline, so here are the most relevant passages from "
            "the knowledge base (no generated summary):",
            "",
        ]
        for i, c in enumerate(chunks, 1):
            body = c.text.split("]\n", 1)[-1].strip()  # drop the header line
            snippet = body[:600] + ("…" if len(body) > 600 else "")
            lines.append(f"[{i}] {c.citation}\n{snippet}\n")
        return "\n".join(lines).strip()

    def query(self, question: str, top_k: Optional[int] = None,
              min_score: Optional[float] = None,
              user: Optional[str] = None) -> Answer:
        """Answer a question grounded in the ingested documents.

        Writes an audit-trail event for every call (grounded or refused).
        """
        chunks = self.retrieve(question, top_k=top_k, min_score=min_score)

        if not chunks:
            msg = (
                "I could not find anything relevant in the knowledge base to "
                "answer that. Try rephrasing, or ingest more documents."
                if len(self.store) else
                "The knowledge base is empty. Ingest documents first before "
                "asking questions.")
            ans = Answer(text=msg, sources=[], grounded=False,
                         backend="template")
            self._audit(question, ans, user)
            return ans

        context = self._build_context(chunks)
        generated = self._generate_ollama(question, context)
        if generated is not None:
            ans = Answer(text=generated, sources=chunks, grounded=True,
                         backend="ollama")
        else:
            # Ollama offline → extractive fallback (retrieval still works).
            ans = Answer(text=self._extractive_answer(chunks), sources=chunks,
                         grounded=True, backend="extractive")
        self._audit(question, ans, user)
        return ans

    def _audit(self, question: str, ans: Answer, user: Optional[str]) -> None:
        self.audit.record(
            question=question, answer=ans.text,
            sources=[s.to_dict() for s in ans.sources],
            backend=ans.backend, grounded=ans.grounded, user=user)

    # ── status ───────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "index_path": str(self.index_path),
            "num_chunks": len(self.store),
            "num_sources": len(self.store.sources()),
            "sources": self.store.sources(),
            "manifest": self.store.manifest,
            "embedding_backend": self.embedder.backend,
            "embedding_signature": self.embedder.signature,
            "index_signature": self.store.embedding_signature,
            "audit_events": self.audit.count(),
        }
