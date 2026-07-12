# Credit Risk Knowledge Assistant

A **grounded question-answering assistant** for a lender's own
documents — credit policies, procedures, model cards, product guides,
regulatory filings, archived reports. Underwriters, compliance staff, and
model-risk teams ask questions in plain English and get answers **drawn
strictly from the source documents, with citations** they can click to
verify.

Runs two ways: **out of the box** on the cloud (Claude API) with **BM25
keyword search** — no install needed — or **fully on-premise** with a local
Ollama server, so confidential documents never leave your machine.

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
| **Cloud or on-premise** | Out of the box, search runs on **BM25 keyword ranking** and answers are written by the **Claude API** — no install. For confidential material, switch everything to a local [Ollama](https://ollama.ai) server so document content never leaves your infrastructure (the same PIPEDA rationale as the credit platform's on-prem LLM). |
| **Grounded, never invented** | Answers use *only* retrieved passages and cite them. If nothing relevant is found, the assistant says so instead of guessing. |
| **Auditable** | Every question, answer, and cited source (with the document's version) is written to an append-only audit trail. Each source is tagged with its ingest time and content hash. |
| **Robust** | 19 tests plus a retrieval **battery + eval set** run in CI so answer quality can't silently regress. The on-disk index **self-heals** — it auto-rebuilds when the app is upgraded, so a deploy never serves a stale index. Degrades gracefully with no Ollama, no GPU, and no third-party parsers. |
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

Without Ollama, the assistant still works: search falls back to **BM25
keyword ranking** (the algorithm behind Elasticsearch/Lucene) with synonym
expansion and section-heading boosting, and — with no answer model — returns
the relevant passages verbatim, with the same citations.

### Run fully local (private / on-prem)

Nothing leaves your machine — documents, search, and answers all run
locally. Best for confidential material.

```bash
# 1. Install Ollama (one-time):  https://ollama.com/download
# 2. Pull the models and start the server:
ollama pull nomic-embed-text     # semantic search   (~275 MB)
ollama pull llama3               # written answers    (~4.7 GB)
ollama serve

# 3. Install Python deps, index the docs, launch:
pip install -r requirements.txt
python -m src.rag.cli ingest knowledge/ --reset
streamlit run src/app/chatbot.py
```

Dependencies: **Python 3.10+**, **Ollama** (for local mode), and the
packages in `requirements.txt` (`streamlit`, `numpy`, plus optional
`fastapi`/`httpx`/`anthropic`/`voyageai`/`pypdf`/`python-docx`). In the
app's sidebar pick **"💻 On my computer — Ollama"** as the answer engine.

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
from generation.** For meaning-based *search* without a local model, set
`VOYAGE_API_KEY` and `RAG_EMBED_PROVIDER="voyage"` (Voyage cloud
embeddings); otherwise search uses Ollama embeddings, and falls back to
local **BM25 keyword search** if neither is available. For a fully on-prem
deployment over confidential documents, keep both retrieval and generation
on Ollama so nothing leaves the machine.

---

## What you get

- **Chatbot UI** (`streamlit run src/app/chatbot.py`) — a tabbed interface:
  a **💬 Chat** tab with expandable source cards (passage, relevance score,
  document version), plus reference tabs that stay accurate for any corpus:
  **About**, **What can I ask?** (per-document outline + clickable topic
  chips), **Strengths & limits** (a live readout of what the tool does well
  and where it's limited in the *current* setup), **Glossary** (plain-language
  definitions of terms found in your documents), and **Documents** (read any
  source in full to verify answers). Also: a plain-language answer-engine
  picker, a knowledge-base status sidebar, and drag-and-drop ingestion.
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

## Deploy

The chatbot is a self-contained Streamlit app that **auto-loads the seed
documents on first run**, so hosting it is one step.

**Streamlit Community Cloud (free):** point [share.streamlit.io](https://share.streamlit.io)
at this repo, main file `src/app/chatbot.py`. To preconfigure cloud answers,
add `ANTHROPIC_API_KEY` in the app's **Secrets** — this persists across
reboots, whereas a key pasted into the sidebar clears on restart. On a public
app, a Secrets key is spent by every visitor, so set a spend limit on it (or
let each visitor paste their own key). The index self-heals on deploy, so code
updates don't require a manual rebuild.

**Docker (anywhere):**

```bash
docker build -t knowledge-assistant .
docker run -p 8501:8501 -e ANTHROPIC_API_KEY=sk-ant-... knowledge-assistant
```

> On a cloud host, the on-device (Ollama) engine isn't available, so answers
> come from the Claude API (if a key is set) or fall back to cited passages.
> For a fully private, on-prem deployment over confidential documents, run it
> on your own machine with Ollama.

---

## How it works

```
ingest:  load documents → chunk (heading-aware) → index → store
         (+ record each source's ingest time & content hash)
query:   rank passages (BM25 keywords by default, or semantic embeddings)
         → grounded prompt → cited answer → write audit-trail event
```

| Module | Role |
|---|---|
| `src/rag/loaders.py` | Read md/txt/csv/json/pdf/docx (PDF/Word need optional parsers) |
| `src/rag/chunker.py` | Heading-aware, overlapping chunks with section breadcrumbs |
| `src/rag/bm25.py` | BM25 keyword ranking + synonym expansion + heading boost (default search) |
| `src/rag/embeddings.py` | Ollama / Voyage embeddings for semantic search (optional) |
| `src/rag/vector_store.py` | JSON-persisted store, cosine search, per-source version manifest, build-version stamp |
| `src/rag/pipeline.py` | Orchestration, retrieval, grounding, anti-hallucination, audit |
| `src/rag/audit.py` | Append-only JSONL audit trail |
| `src/rag/api.py` | FastAPI router + standalone app |
| `src/rag/cli.py` | Command-line interface |
| `src/app/chatbot.py` | Streamlit chatbot UI (tabbed) |

### Anti-hallucination guarantees

1. The system prompt restricts the model to the provided passages and
   requires citations.
2. If nothing retrieves above the relevance floor, the pipeline **refuses
   to call the model** and returns "I could not find that in the knowledge
   base."
3. With no answer model connected, answers are **extractive** — the user
   always sees real, cited source text (never invented).

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
python tests/test_rag.py        # 19 unit/integration tests (stdlib only),
                                # incl. a retrieval battery over the seed corpus
python eval/eval_set.py         # retrieval recall@k over the seed corpus
```

The test suite includes a **retrieval battery**: a set of realistic questions
that must each retrieve a passage containing the actual answer, so a
phrasing/retrieval regression fails in CI instead of reaching users. The eval
additionally checks recall@5 over the seed corpus, failing below 0.70 — a
regression guard for retrieval quality.

---

## Configuration

All settings live in `config.py` (knowledge/store paths, generation &
embedding providers, chunk size, top-k, relevance floor, audit toggle, and
`INDEX_BUILD_VERSION` — bump it when a chunking/retrieval change should force
a rebuild of any already-deployed index).

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
