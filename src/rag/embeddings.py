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

    Args:
        model:   Ollama embedding model name.
        dim:     Dimension of the local fallback embedding.
        prefer_ollama: If False, always use the local backend (useful for
                       deterministic tests and offline demos).
    """

    def __init__(self,
                 model: Optional[str] = None,
                 dim: Optional[int] = None,
                 prefer_ollama: bool = True):
        self.model = model or config.RAG_EMBED_MODEL
        self.dim = dim or config.RAG_EMBED_DIM
        self.prefer_ollama = prefer_ollama
        self._backend: Optional[str] = None  # resolved lazily on first embed

    def _resolve_backend(self) -> str:
        if self._backend is not None:
            return self._backend
        if self.prefer_ollama and ollama_embeddings_available(self.model):
            self._backend = "ollama"
        else:
            if self.prefer_ollama:
                log.warning(
                    "Ollama embeddings unavailable — using local hashing "
                    "embedding (lexical retrieval). Pull '%s' and run "
                    "'ollama serve' for semantic retrieval.", self.model)
            self._backend = "local"
        return self._backend

    @property
    def backend(self) -> str:
        """Which backend is in use: 'ollama' or 'local'."""
        return self._resolve_backend()

    @property
    def signature(self) -> str:
        """Identifier stored with an index so we never mix vector spaces."""
        if self.backend == "ollama":
            return f"ollama:{self.model}"
        return f"local-hash:{self.dim}"

    def embed(self, text: str) -> List[float]:
        """Embed one string, falling back to local per-call if Ollama drops."""
        if self._resolve_backend() == "ollama":
            vec = _ollama_embed(text, self.model)
            if vec is not None:
                return vec
            log.warning("Ollama embedding call failed mid-run — "
                        "falling back to local embedding for this text.")
            self._backend = "local"
        return _hash_embed(text, self.dim)

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of strings (sequential; Ollama has no batch API)."""
        return [self.embed(t) for t in texts]
