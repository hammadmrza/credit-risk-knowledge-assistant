# Credit Risk Knowledge Assistant

A **local-first, grounded question-answering assistant** for a lender's own
documents — credit policies, procedures, model cards, product guides,
regulatory filings, archived reports. Underwriters, compliance staff, and
model-risk teams ask questions in plain English and get answers **drawn
strictly from the source documents, with citations** they can click to
verify.

Built as the knowledge companion to the
[Credit Risk Platform](https://github.com/hammadmrza/credit-risk-platform):
that platform *makes* credit decisions; this one *answers questions* about
the policies, models, and compliance posture behind them.

> **About the seed documents.** The files in [`knowledge/`](knowledge/) are
> sample copies taken from the
> [credit-risk-platform](https://github.com/hammadmrza/credit-risk-platform)
> repository, included only as an example corpus so the assistant works out
> of the box. In real use, replace them with your own documents — those
> stay on your machine and are never committed (see `.gitignore`).

---

## Why it's built this way

| Principle | How |
|---|---|
| **Local-first / on-premise** | Embeddings and generation run through a local [Ollama](https://ollama.ai) server. Document content never leaves your infrastructure — the same PIPEDA rationale as the credit platform's on-prem LLM. |
| **Grounded, never invented** | Answers use *only* retrieved passages and cite them. If nothing relevant is found, the assistant says so instead of guessing. |
| **Auditable** | Every question, answer, and cited source (with the document's version) is written to an append-only audit trail. Each source is tagged with its ingest time and content hash. |
| **Robust** | A retrieval eval set runs in CI so answer quality can't silently regress. Degrades gracefully with no Ollama, no GPU, and no third-party parsers. |
| **No database to run** | The index is a single JSON file on disk. |

---

## Quick start

```bash
pip install -r requirements.txt

# (Optional but recommended) semantic retrieval + natural-language answers
ollama pull nomic-embed-text
ollama pull llama3
ollama serve

# Index the seed documents in knowledge/
python -m src.rag.cli ingest knowledge/ --reset

# Ask a question
python -m src.rag.cli query "What human oversight is required before a decline?"

# Interactive session
python -m src.rag.cli chat

# Launch the chatbot UI
streamlit run src/app/chatbot.py
```

Without Ollama, the assistant still works: it uses a deterministic local
(lexical) embedding and returns the relevant passages verbatim, with the
same citations.

### Written answers without a local model — use the Claude API

Prefer not to download a local model? Set an Anthropic API key and the
assistant writes answers via the Claude API — no download, no GPU:

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # Windows: set ANTHROPIC_API_KEY=...
python -m src.rag.cli query "What is the DTI cap for unsecured loans?"
```

`GENERATION_PROVIDER` in `config.py` controls who writes the answer:

| Value | Behaviour |
|---|---|
| `auto` (default) | Claude API if `ANTHROPIC_API_KEY` is set, else Ollama |
| `anthropic` | Always the Claude API |
| `ollama` | Always the local Ollama model |
| `off` | Never generate — return the retrieved passages verbatim |

The model is `ANTHROPIC_MODEL` (`claude-opus-4-8` by default; set it to
`claude-haiku-4-5` for a cheaper, faster option). **Retrieval is separate
from generation** — with a cloud key you get written answers, but semantic
*search* still needs Ollama embeddings (or falls back to local lexical
search). For a fully on-prem deployment over confidential documents, keep
generation on Ollama so no content leaves the machine.

---

## What you get

- **Chatbot UI** (`streamlit run src/app/chatbot.py`) — chat interface with
  expandable source cards (passage, relevance score, document version),
  a knowledge-base status sidebar, and drag-and-drop document ingestion.
  New users are oriented automatically: a **"What can I ask about?"** panel
  and clickable **topic chips** are derived from whatever documents are
  loaded (so they stay accurate for any corpus), a plain-language answer-
  engine picker, and off-topic questions get redirected to in-scope topics.
- **REST API** (`uvicorn src.rag.api:app --port 8100`) — `/rag/query`,
  `/rag/ingest/*`, `/rag/status`, `/rag/reset`.
- **CLI** — `ingest`, `query`, `chat`, `status`.
- **Python API** — `from src.rag import RAGPipeline`.

```python
from src.rag import RAGPipeline

rag = RAGPipeline()
rag.ingest_dir("knowledge/")
ans = rag.query("What triggers a fraud decline?", user="j.smith")
print(ans.text)
for s in ans.sources:
    print(s.citation, s.score, s.version.get("ingested_at"))
```

---

## How it works

```
ingest:  load documents → chunk (heading-aware) → embed → store
         (+ record each source's ingest time & content hash)
query:   embed question → retrieve top-k passages → grounded prompt
         → cited answer → write audit-trail event
```

| Module | Role |
|---|---|
| `src/rag/loaders.py` | Read md/txt/csv/json/pdf/docx (PDF/Word need optional parsers) |
| `src/rag/chunker.py` | Heading-aware, overlapping chunks with section breadcrumbs |
| `src/rag/embeddings.py` | Ollama embeddings, deterministic local fallback |
| `src/rag/vector_store.py` | JSON-persisted cosine search + per-source version manifest |
| `src/rag/pipeline.py` | Orchestration, grounding, anti-hallucination, audit |
| `src/rag/audit.py` | Append-only JSONL audit trail |
| `src/rag/api.py` | FastAPI router + standalone app |
| `src/rag/cli.py` | Command-line interface |
| `src/app/chatbot.py` | Streamlit chatbot UI |

### Anti-hallucination guarantees

1. The system prompt restricts the model to the provided passages and
   requires citations.
2. If nothing retrieves above the relevance floor, the pipeline **refuses
   to call the model** and returns "I could not find that in the knowledge
   base."
3. Offline, answers are **extractive** — the user always sees real source text.

---

## Auditability & versioning

- **Audit trail** (`rag_store/audit_log.jsonl`) — one JSON line per query:
  timestamp, user, question, answer, backend, and the cited sources with
  their document versions. Load it into pandas for review, or show it to an
  examiner as the record of what the assistant told whom.
- **Document versioning** — each source is stamped with its ingest time and
  a content hash, surfaced on every answer ("as-of") so a claim is always
  tied to the version of the policy it came from.

---

## Tests & evaluation

```bash
python tests/test_rag.py        # 10 unit/integration tests (stdlib only)
python eval/eval_set.py         # retrieval recall@k over the seed corpus
```

The eval ingests the seed knowledge base with the offline backend and checks
that each known question retrieves its expected source document, failing if
recall@5 drops below 0.70 — a regression guard for retrieval quality.

---

## Configuration

All settings live in `config.py` (knowledge/store paths, Ollama model,
chunk size, top-k, relevance floor, audit toggle).

## Adapting to other document sets

The engine is domain-agnostic. To point it at a different corpus, replace
the files in `knowledge/` and (optionally) tune the assistant's persona in
the system prompt in `src/rag/pipeline.py`. The retrieval, grounding,
citation, audit, and refusal logic are unchanged.

## Scaling

The JSON + in-memory store suits a single organisation's policy/archive
corpus (thousands to low-tens-of-thousands of chunks). For larger volumes,
swap FAISS or a vector database behind the `add`/`search` interface in
`src/rag/vector_store.py`.

## License

MIT
