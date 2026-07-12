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
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

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


_NUM_PREFIX = re.compile(r"^\s*\d+(\.\d+)*\.?\s+")

_TOPIC_STOP = {
    "overview", "data", "references", "introduction", "summary", "scope",
    "document control", "system requirements", "purpose and scope",
    "related documents", "signatures", "review and approval",
}


def _is_noise_topic(sec: str) -> bool:
    """True for boilerplate section names not worth showing as a topic."""
    s = (sec or "").lower().strip()
    if s in _TOPIC_STOP:
        return True
    if re.match(r"^step\s+\d+", s):      # "Step 3", "Step 4"…
        return True
    if re.match(r"^v(ersion)?[\s\d.]", s):  # "Version 1.1…", "v1.1"
        return True
    return len(s) < 5


def _clean_topic(text: str) -> str:
    """Tidy a heading into a readable topic label.

    Strips leading section numbers ("3.3 ") and everything after an em/en
    dash separator, so "3. Hierarchical Decision Engine" → "Hierarchical
    Decision Engine" and "Gate 2 — Hard Policy Rules" → "Gate 2".
    """
    text = _NUM_PREFIX.sub("", (text or "").strip())
    for sep in (" — ", " – ", " - "):
        if sep in text:
            text = text.split(sep, 1)[0].strip()
            break
    return text


class RAGPipeline:
    """Ingest documents and answer questions grounded in them.

    Args:
        index_path: Where the vector index is persisted (JSON).
        prefer_ollama: Use Ollama for embeddings when available.
        chunk_size / overlap: Chunking parameters (default from config).
        audit: Enable the audit trail (default from config.AUDIT_ENABLED).
        generation: Override the answer-generation provider
            ("auto" | "anthropic" | "ollama" | "off"); defaults to
            config.GENERATION_PROVIDER.
    """

    def __init__(self,
                 index_path=None,
                 prefer_ollama: bool = True,
                 chunk_size: Optional[int] = None,
                 overlap: Optional[int] = None,
                 audit: Optional[bool] = None,
                 generation: Optional[str] = None):
        self.index_path = Path(index_path or config.RAG_INDEX_PATH)
        self.chunk_size = chunk_size or config.RAG_CHUNK_SIZE
        self.overlap = overlap if overlap is not None else config.RAG_CHUNK_OVERLAP
        self.embedder = Embedder(prefer_ollama=prefer_ollama)
        self.store = VectorStore.load(self.index_path)
        self.generation = generation or getattr(config, "GENERATION_PROVIDER", "auto")
        self._bm25 = None            # lazily built for local keyword retrieval
        self._bm25_n = -1
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
        self.store.set_document(source, text)   # for the document viewer
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
        self.store.build_version = config.INDEX_BUILD_VERSION
        self.store.save(self.index_path)

    def reset(self, save: bool = True) -> None:
        """Delete all indexed content."""
        self.store = VectorStore(embedding_signature=self.embedder.signature)
        self.store.build_version = config.INDEX_BUILD_VERSION
        if save:
            self.store.save(self.index_path)

    # ── retrieval ────────────────────────────────────────────────

    def retrieve(self, question: str, top_k: Optional[int] = None,
                 min_score: Optional[float] = None) -> List[RetrievedChunk]:
        """Return the most relevant chunks for a question.

        Local (no Ollama/Voyage) uses BM25 keyword ranking; the semantic
        backends use embedding cosine similarity.
        """
        top_k = top_k or config.RAG_TOP_K
        min_score = config.RAG_MIN_SCORE if min_score is None else min_score
        if not len(self.store):
            return []

        if self.embedder.backend == "local":
            return self._bm25_retrieve(question, top_k)

        qvec = self.embedder.embed(question, is_query=True)
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

    def _ensure_bm25(self) -> None:
        if self._bm25 is None or self._bm25_n != len(self.store):
            from src.rag.bm25 import BM25
            # Heading boost (standard IR "title" weighting): repeat each chunk's
            # section breadcrumb so terms in the heading count more. This lifts
            # the passage whose *section* is about the query (e.g. the "Features
            # Used" section for a "what features…" question) above passages that
            # merely mention the common query words in passing.
            docs = []
            for r in self.store.records:
                head = r.meta.get("breadcrumb", "")
                docs.append((head + " ") * 3 + r.text if head else r.text)
            self._bm25 = BM25(docs)
            self._bm25_n = len(self.store)

    def _bm25_retrieve(self, question: str, top_k: int) -> List[RetrievedChunk]:
        """Keyword retrieval via BM25. Empty result → the query shares no
        terms with any passage, which the caller turns into an honest refusal."""
        from src.rag.bm25 import expand_query
        self._ensure_bm25()
        # Add formal synonyms (cap→maximum, floor→minimum) so a user's everyday
        # phrasing still finds the policy row, which uses the formal wording.
        scores = self._bm25.scores(expand_query(question))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        top = scores[order[0]] if order else 0.0
        out = []
        for i in order[:top_k]:
            if scores[i] <= 0:
                break
            rec = self.store.records[i]
            out.append(RetrievedChunk(
                source=rec.source, text=rec.text,
                score=round(scores[i] / top, 4) if top > 0 else 0.0,
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

    def _generate_anthropic(self, question: str, context: str) -> Optional[str]:
        """Write the answer with the Claude API. ``None`` if unavailable.

        Requires the ``anthropic`` package and ANTHROPIC_API_KEY in the
        environment. Never raises — returns ``None`` so the caller falls back.
        """
        if not os.getenv("ANTHROPIC_API_KEY"):
            return None
        try:
            import anthropic  # type: ignore
        except ImportError:
            log.warning("GENERATION_PROVIDER wants Claude but the 'anthropic' "
                        "package is not installed (pip install anthropic).")
            return None
        prompt = (
            f"Context passages:\n{context}\n\n"
            f"Question: {question}\n\n"
            "Answer using only the passages above, citing passage numbers."
        )
        try:
            client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY / base URL
            resp = client.messages.create(
                model=getattr(config, "ANTHROPIC_MODEL", "claude-opus-4-8"),
                max_tokens=getattr(config, "ANTHROPIC_MAX_TOKENS", 1024),
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            if resp.stop_reason == "refusal":
                return None
            text = "".join(b.text for b in resp.content
                           if getattr(b, "type", None) == "text").strip()
            return text or None
        except Exception as e:
            log.warning("Claude API call failed (%s) — falling back.", e)
            return None

    def _generate(self, question: str, context: str) -> Tuple[Optional[str], Optional[str]]:
        """Generate the answer via the configured provider chain.

        Returns (text, backend_name). Both ``None`` if no provider produced
        an answer (caller then uses the extractive fallback).
        """
        provider = self.generation
        if provider == "anthropic":
            order = ["anthropic"]
        elif provider == "ollama":
            order = ["ollama"]
        elif provider == "off":
            order = []
        else:  # "auto"
            order = (["anthropic", "ollama"] if os.getenv("ANTHROPIC_API_KEY")
                     else ["ollama"])
        for p in order:
            text = (self._generate_anthropic(question, context) if p == "anthropic"
                    else self._generate_ollama(question, context))
            if text is not None:
                return text, p
        return None, None

    def _extractive_answer(self, question: str, chunks: List[RetrievedChunk]) -> str:
        """LLM-free answer that still reads cleanly.

        Instead of dumping raw passages, we pull the few sentences across the
        top passages that best match the question and present them as a short,
        quoted answer. No model, fully deterministic, and every sentence is
        verbatim from a source — so it's trustworthy *and* tidy.
        """
        import re
        from src.rag.bm25 import content_tokens, expand_query

        # Match sentences on the *expanded* query (cap→maximum, floor→minimum)
        # so a sentence phrased in the document's formal wording still scores.
        q_terms = set(content_tokens(expand_query(question)))
        scored = []  # (score, order, sentence, citation)
        order = 0
        for c in chunks[:6]:                      # scan the top passages
            body = c.text.split("]\n", 1)[-1].strip()
            for sent in self._split_sentences(body):
                s_terms = content_tokens(sent)
                if not s_terms:
                    continue
                overlap = sum(1 for t in s_terms if t in q_terms)
                if not overlap:
                    continue
                # A sentence that ends in real terminal punctuation reads as a
                # complete thought; a clipped fragment doesn't. Reward the
                # former so whole sentences win over mid-wrap scraps. Weight by
                # the passage's own relevance (c.score) so a sentence from a
                # more-relevant passage outranks one from a weaker match.
                complete = bool(re.search(r"[.!?%)\]\d]$", sent))
                score = (overlap * (c.score or 0.1)
                         * (1.0 if complete else 0.55))
                if not complete:                  # signal the clip to the reader
                    sent = sent.rstrip(" ·,;:") + "…"
                scored.append((score, order, sent, c.citation, complete))
                order += 1

        if not scored:
            # Nothing matched at the sentence level — fall back to the single
            # most-relevant passage, trimmed, rather than an empty answer.
            top = chunks[0]
            body = top.text.split("]\n", 1)[-1].strip()
            snippet = body[:500] + ("…" if len(body) > 500 else "")
            return (f"Here's the most relevant passage:\n\n> {snippet}\n\n"
                    f"— {top.citation}")

        scored.sort(key=lambda x: (-x[0], x[1]))
        # Dedupe near-identical sentences (same first 40 chars), keep top 3.
        picked, seen = [], set()
        for item in scored:
            key = item[2][:40].lower()
            if key in seen:
                continue
            seen.add(key)
            picked.append(item)
            if len(picked) == 3:
                break
        picked.sort(key=lambda x: x[1])           # restore reading order

        lines = ["**Based on your documents:**\n"]
        for _, _, sent, cite, _ in picked:
            # Markdown-native muted citation (the chat renders without raw HTML,
            # so <sup> would show as literal text). Shorten to source + section.
            lines.append(f"- {sent}  \n  :gray[— {self._short_cite(cite)}]")
        return "\n".join(lines)

    @staticmethod
    def _short_cite(cite: str) -> str:
        """Compact a breadcrumb citation to 'SOURCE › last section'."""
        src = cite.split(" › ", 1)[0]
        last = cite.replace(" › ", " > ").split(" > ")[-1].strip()
        last = last.replace("[", "(").replace("]", ")")   # keep :gray[] intact
        return f"{src} › {last}" if last and last != src else src

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """Sentence splitter + markdown scrub that rejoins hard-wrapped lines.

        Markdown source often hard-wraps one sentence across several physical
        lines; naively splitting on newlines shreds it into fragments. We scrub
        each line, merge a line into the previous one when the previous didn't
        end in terminal punctuation and this one continues it (starts
        lowercase), then split the rejoined text into sentences.
        """
        import re

        # 1. Scrub each physical line (strip bold, table pipes, bullet markers).
        raw = []
        for ln in text.split("\n"):
            ln = ln.replace("**", "").replace("`", "")
            ln = re.sub(r"\s*\|\s*", " · ", ln)          # table cells → middots
            ln = re.sub(r"^[\s\-•*·>#]+", "", ln)        # leading list/heading marks
            ln = re.sub(r"\s{2,}", " ", ln).strip(" ·")
            if ln and not re.fullmatch(r"[-=_·:\s]+", ln):  # drop rule lines
                raw.append(ln)

        # 2. Rejoin wrapped continuations into whole sentences.
        merged: List[str] = []
        for ln in raw:
            if (merged and not re.search(r"[.!?:%)\]\d]$", merged[-1])
                    and ln[:1].islower()):
                merged[-1] = merged[-1] + " " + ln
            else:
                merged.append(ln)

        # 3. Split each merged unit into sentences on terminal punctuation.
        out = []
        for m in merged:
            for s in re.split(r"(?<=[.!?])\s+", m):
                s = re.sub(r"^[\s\-•*·:]+|[\s·]+$", "", s)
                if len(s) >= 20 and not re.fullmatch(r"[\-:·\s]+", s):
                    out.append(s)
        return out

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
        generated, backend = self._generate(question, context)
        if generated is not None:
            ans = Answer(text=generated, sources=chunks, grounded=True,
                         backend=backend)
        else:
            # No LLM available → extractive fallback (retrieval still works).
            ans = Answer(text=self._extractive_answer(question, chunks),
                         sources=chunks, grounded=True, backend="extractive")
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
            "index_build_version": self.store.build_version,
            "current_build_version": config.INDEX_BUILD_VERSION,
            "generation_provider": self.generation,
            "generation_active": self._active_generation(),
            "audit_events": self.audit.count(),
        }

    def _active_generation(self) -> str:
        """Best-effort description of which generator a query would use."""
        if self.generation == "off":
            return "off (extractive only)"
        if self.generation == "anthropic":
            return "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "anthropic (no API key set)"
        if self.generation == "ollama":
            return "ollama"
        # auto
        if os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic (Claude API)"
        return "ollama (or extractive if offline)"

    # ── orientation (derived from the documents, for any corpus) ─────

    def outline(self, max_sections: int = 6) -> List[dict]:
        """Per-document orientation, derived from the indexed content.

        Returns a list of {"source", "title", "sections"} where ``title`` is
        the document's top heading (or filename) and ``sections`` are its main
        section names. Used by UIs to tell a new user what they can ask about,
        without hardcoding anything domain-specific — it reflects whatever
        documents are actually loaded.
        """
        per: dict = {}
        for rec in self.store.records:
            src = rec.source
            crumb = rec.meta.get("breadcrumb", "") or ""
            parts = [p.strip() for p in crumb.split(">") if p.strip()]
            entry = per.setdefault(src, {"title": None, "sections": [], "seen": set()})
            if parts:
                if entry["title"] is None:
                    entry["title"] = _clean_topic(parts[0])
                if len(parts) >= 2:
                    sec = _clean_topic(parts[1])
                    if sec and sec.lower() not in entry["seen"] \
                            and len(entry["sections"]) < max_sections:
                        entry["seen"].add(sec.lower())
                        entry["sections"].append(sec)
        out = []
        for src in self.store.sources():
            e = per.get(src, {"title": None, "sections": []})
            title = e["title"] or Path(src).stem.replace("_", " ").title()
            out.append({"source": src, "title": title, "sections": e["sections"]})
        return out

    def document_text(self, source: str) -> str:
        """Full text of an indexed document, for manual verification."""
        return self.store.get_document(source)

    def topics(self, limit: int = 8) -> List[str]:
        """Meaningful topics across all documents, for chips / refusal hints.

        Filters out boilerplate sections (Overview, Step N, Version…, Document
        Control) and round-robins across documents so the list shows breadth
        rather than being dominated by one document.
        """
        doc_secs = [[s for s in d["sections"] if not _is_noise_topic(s)]
                    for d in self.outline()]
        seen, flat, i = set(), [], 0
        while len(flat) < limit and any(len(ds) > i for ds in doc_secs):
            for ds in doc_secs:
                if len(ds) > i:
                    k = ds[i].lower()
                    if k not in seen:
                        seen.add(k)
                        flat.append(ds[i])
                        if len(flat) >= limit:
                            break
            i += 1
        return flat
