"""
src/rag/embeddings.py
──────────────────────
Turn text into vectors for semantic retrieval.

TWO BACKENDS, CHOSEN AUTOMATICALLY
──────────────────────────────────
  1. Ollama embeddings (preferred) — a real embedding model such as
     ``nomic-embed-text`` served locally. High-quality semantic vectors,
     no data leaves the machine.

  2. Local hashing embedding (fallback) — a deterministic, dependency-free
     bag-of-words vector using the hashing trick with sub-linear TF
     weighting and L2 normalisation. It captures *lexical* overlap rather
     than deep semantics, but it is good enough that retrieval works out
     of the box with no server, no model download, and no GPU. Because it
     is deterministic, an index built with it stays queryable.

The pipeline records which backend produced an index and refuses to mix
backends (their vector spaces are unrelated), re-embedding if needed.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from typing import List, Optional

import config
from src.rag.ollama_http import get_json, post_json

log = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


# ── Ollama backend ───────────────────────────────────────────────

def _ollama_embed(text: str, model: str) -> Optional[List[float]]:
    """Embed a single string via Ollama; ``None`` if unavailable."""
    url = f"{config.OLLAMA_BASE_URL}/api/embeddings"
    data = post_json(url, {"model": model, "prompt": text},
                     timeout=config.OLLAMA_TIMEOUT)
    if not data:
        return None
    vec = data.get("embedding")
    if isinstance(vec, list) and vec:
        return [float(x) for x in vec]
    return None


def ollama_embeddings_available(model: Optional[str] = None) -> bool:
    """True if Ollama is running and the embedding model is pulled."""
    model = model or config.RAG_EMBED_MODEL
    tags = get_json(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=5)
    if not tags:
        return False
    names = [m.get("name", "") for m in tags.get("models", [])]
    return any(model.split(":")[0] in n for n in names)


# ── Cloud backend (Voyage AI — semantic, no local download) ──────

def voyage_embeddings_available() -> bool:
    """True if the Voyage SDK is installed and VOYAGE_API_KEY is set."""
    if not os.getenv("VOYAGE_API_KEY"):
        return False
    try:
        import voyageai  # noqa: F401
        return True
    except ImportError:
        return False


def _voyage_embed(text: str, model: str,
                  input_type: Optional[str] = None) -> Optional[List[float]]:
    """Embed one string via the Voyage API; ``None`` if unavailable.

    Gives true semantic search with no local model download — matches on
    meaning (so "borrowing limit" finds "maximum loan amount"). Never
    raises: returns ``None`` so the caller falls back.
    """
    try:
        import voyageai  # type: ignore

        client = voyageai.Client()  # reads VOYAGE_API_KEY from the environment
        result = client.embed([text], model=model, input_type=input_type)
        vecs = getattr(result, "embeddings", None)
        if vecs:
            return [float(x) for x in vecs[0]]
    except Exception as e:
        log.warning("Voyage embedding failed (%s) — falling back.", e)
    return None


# ── Local hashing backend (dependency-free) ──────────────────────

def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def _hash_embed(text: str, dim: int) -> List[float]:
    """Deterministic hashing-trick embedding with L2 normalisation.

    Uses word unigrams + bigrams so short lexical phrases retrieve well.
    Term frequency is damped (1 + log tf) to stop repeated words from
    dominating, matching standard TF weighting.
    """
    tokens = _tokenize(text)
    if not tokens:
        return [0.0] * dim

    counts: dict[int, float] = {}
    grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    raw: dict[int, int] = {}
    for g in grams:
        h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h // dim) % 2 == 0 else -1.0  # signed hashing
        raw[idx] = raw.get(idx, 0) + 1
        counts[idx] = counts.get(idx, 0.0) + sign

    # sub-linear TF weighting applied on magnitude, sign preserved
    vec = [0.0] * dim
    for idx, signed in counts.items():
        tf = raw[idx]
        weight = (1.0 + math.log(tf)) if tf > 0 else 0.0
        vec[idx] = math.copysign(weight, signed) if signed != 0 else weight

    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


# ── Public embedder ──────────────────────────────────────────────

class Embedder:
    """Embeds text, transparently choosing the best available backend.

    Backends, in order of retrieval quality:
      • ``ollama``  — a local embedding model (semantic, private, no cloud)
      • ``voyage``  — the Voyage cloud API (semantic, no local download;
                      needs VOYAGE_API_KEY)
      • ``local``   — a deterministic hashing embedding (lexical; no deps,
                      works everywhere)

    The provider is chosen from ``config.RAG_EMBED_PROVIDER``
    ("auto" | "ollama" | "voyage" | "local"). ``prefer_ollama=False`` forces
    the pure-local backend — used by tests and offline demos so results are
    deterministic and make no network calls.

    Args:
        model:   Ollama embedding model name.
        dim:     Dimension of the local fallback embedding.
        prefer_ollama: If False, force the local backend.
        provider: Override ``config.RAG_EMBED_PROVIDER``.
    """

    def __init__(self,
                 model: Optional[str] = None,
                 dim: Optional[int] = None,
                 prefer_ollama: bool = True,
                 provider: Optional[str] = None):
        self.model = model or config.RAG_EMBED_MODEL
        self.voyage_model = getattr(config, "VOYAGE_MODEL", "voyage-3")
        self.dim = dim or config.RAG_EMBED_DIM
        self.prefer_ollama = prefer_ollama
        self.provider = provider or getattr(config, "RAG_EMBED_PROVIDER", "auto")
        self._backend: Optional[str] = None  # resolved lazily on first embed

    def _resolve_backend(self) -> str:
        if self._backend is not None:
            return self._backend
        # Forced-local (tests / deterministic offline mode).
        if not self.prefer_ollama:
            self._backend = "local"
            return self._backend

        prov = self.provider
        if prov == "local":
            self._backend = "local"
        elif prov == "ollama":
            self._backend = ("ollama" if ollama_embeddings_available(self.model)
                             else self._local_warn("ollama"))
        elif prov == "voyage":
            self._backend = ("voyage" if voyage_embeddings_available()
                             else self._local_warn("voyage"))
        else:  # auto: best available
            if ollama_embeddings_available(self.model):
                self._backend = "ollama"
            elif voyage_embeddings_available():
                self._backend = "voyage"
            else:
                self._backend = self._local_warn("auto")
        return self._backend

    def _local_warn(self, wanted: str) -> str:
        log.warning(
            "Semantic embeddings unavailable (%s) — using the local lexical "
            "embedding. Run Ollama (`ollama pull %s`) or set VOYAGE_API_KEY "
            "for meaning-based search.", wanted, self.model)
        return "local"

    @property
    def backend(self) -> str:
        """Which backend is in use: 'ollama', 'voyage', or 'local'."""
        return self._resolve_backend()

    @property
    def signature(self) -> str:
        """Identifier stored with an index so we never mix vector spaces."""
        b = self.backend
        if b == "ollama":
            return f"ollama:{self.model}"
        if b == "voyage":
            return f"voyage:{self.voyage_model}"
        return f"local-hash:{self.dim}"

    def embed(self, text: str, is_query: bool = False) -> List[float]:
        """Embed one string, falling back to local per-call if the backend drops."""
        backend = self._resolve_backend()
        if backend == "ollama":
            vec = _ollama_embed(text, self.model)
            if vec is not None:
                return vec
            log.warning("Ollama embedding failed mid-run — local fallback.")
            self._backend = "local"
        elif backend == "voyage":
            vec = _voyage_embed(text, self.voyage_model,
                                input_type="query" if is_query else "document")
            if vec is not None:
                return vec
            log.warning("Voyage embedding failed mid-run — local fallback.")
            self._backend = "local"
        return _hash_embed(text, self.dim)

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of strings (sequential)."""
        return [self.embed(t) for t in texts]
