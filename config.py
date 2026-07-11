"""
config.py
─────────
Central configuration for the Credit Risk Knowledge Assistant.

A local-first, grounded question-answering system over a company's own
policy, procedure, and compliance documents. Import this module at the
top of every script.
"""

from pathlib import Path

# ── Project root ─────────────────────────────────────────────────
ROOT = Path(__file__).parent

# ── Knowledge base directories ───────────────────────────────────
KNOWLEDGE_DIR = ROOT / "knowledge"       # documents to ingest (seed corpus)
STORE_DIR     = ROOT / "rag_store"       # persisted index + audit log
INDEX_PATH    = STORE_DIR / "index.json"
AUDIT_LOG_PATH = STORE_DIR / "audit_log.jsonl"

for d in (KNOWLEDGE_DIR, STORE_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ── Ollama (local LLM) ───────────────────────────────────────────
# Same local-first rationale as the credit platform: document content
# never leaves the company's infrastructure.
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL    = "llama3"              # generation model
OLLAMA_TIMEOUT  = 60                    # seconds

# ── Retrieval / embedding ────────────────────────────────────────
# Which backend turns text into search vectors:
#   "auto"   — Ollama if running, else Voyage if VOYAGE_API_KEY is set, else local
#   "ollama" — local Ollama embedding model (semantic, private)
#   "voyage" — Voyage cloud API (semantic, no local download; needs a key)
#   "local"  — deterministic lexical embedding (no deps, keyword-level search)
RAG_EMBED_PROVIDER = "auto"
RAG_EMBED_MODEL   = "nomic-embed-text"   # Ollama embedding model
VOYAGE_MODEL      = "voyage-3"            # Voyage cloud embedding model
RAG_EMBED_DIM     = 512      # dimension of the local fallback embedding
RAG_CHUNK_SIZE    = 1_000    # target characters per chunk
RAG_CHUNK_OVERLAP = 150      # character overlap between adjacent chunks
RAG_TOP_K         = 8        # chunks retrieved per query (more context for the
                             # generator; it ignores the irrelevant ones)
RAG_MIN_SCORE     = 0.15     # cosine floor — below this, treat as "no match"
RAG_MAX_CONTEXT   = 6_000    # max characters of context sent to the LLM

# Bump this whenever a change to chunking or retrieval means an already-built
# index should be rebuilt. On a hosted deploy the index is persisted; the app
# auto-reingests the seed corpus when the stored build version differs from
# this one, so a code update never silently serves a stale index.
INDEX_BUILD_VERSION = "2024.2-bm25-heading-boost"

# ── Answer generation provider ───────────────────────────────────
# Which LLM writes the final answer from the retrieved passages:
#   "auto"      — use the Claude API if ANTHROPIC_API_KEY is set, else Ollama
#   "anthropic" — always use the Claude API (cloud; no local model needed)
#   "ollama"    — always use the local Ollama model
#   "off"       — never generate; return the retrieved passages verbatim
# Retrieval is unaffected — only who writes the prose answer.
GENERATION_PROVIDER = "auto"

# Claude API model used when the provider resolves to "anthropic".
# Set ANTHROPIC_API_KEY in the environment to enable it. Change this to
# "claude-haiku-4-5" for a cheaper/faster option if you prefer.
ANTHROPIC_MODEL     = "claude-opus-4-8"
ANTHROPIC_MAX_TOKENS = 1_024

# ── Audit trail ──────────────────────────────────────────────────
# Every question, its answer, and the exact sources cited are appended
# to an audit log for compliance / OSFI traceability.
AUDIT_ENABLED = True

# ── FastAPI ──────────────────────────────────────────────────────
API_HOST = "0.0.0.0"
API_PORT = 8100

# ── Aliases kept for compatibility with the shared RAG engine ────
# (the engine reads RAG_INDEX_PATH / RAG_DIR from config)
RAG_DIR        = STORE_DIR
RAG_INDEX_PATH = INDEX_PATH
