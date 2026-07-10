"""
tests/test_rag.py
──────────────────
Tests for the RAG pipeline that run with the standard library only —
no Ollama, no numpy, no third-party parsers required. They force the
local embedding backend (``prefer_ollama=False``) so results are
deterministic and offline.

Run:
    python -m pytest tests/test_rag.py -q
    # or without pytest:
    python tests/test_rag.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rag.chunker import chunk_document
from src.rag.embeddings import Embedder, _hash_embed
from src.rag.loaders import load_dir, load_file
from src.rag.pipeline import RAGPipeline
from src.rag.vector_store import VectorStore, _cosine


# ── embeddings ───────────────────────────────────────────────────

def test_hash_embed_is_deterministic_and_normalised():
    a = _hash_embed("the quick brown fox", dim=256)
    b = _hash_embed("the quick brown fox", dim=256)
    assert a == b
    norm = sum(x * x for x in a) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_similar_text_scores_higher_than_unrelated():
    e = Embedder(prefer_ollama=False, dim=512)
    q = e.embed("what is the debt to income cap")
    close = e.embed("the debt to income cap is 45 percent")
    far = e.embed("bananas grow in tropical climates")
    assert _cosine(q, close) > _cosine(q, far)


# ── chunker ──────────────────────────────────────────────────────

def test_chunker_respects_size_and_tracks_headings():
    text = ("# Policy\n\n"
            "## DTI Limits\n\n"
            + ("The debt to income ratio cap is 45 percent. " * 60))
    chunks = chunk_document(text, "policy.md", chunk_size=500, overlap=50)
    assert len(chunks) > 1
    assert any("DTI Limits" in c.meta["breadcrumb"] for c in chunks)
    # header breadcrumb is embedded in the chunk text
    assert chunks[0].text.startswith("[policy.md")


# ── vector store round-trip ──────────────────────────────────────

def test_vector_store_persists_and_searches(tmp_path=None):
    tmp_path = tmp_path or Path(tempfile.mkdtemp())
    e = Embedder(prefer_ollama=False, dim=256)
    store = VectorStore(embedding_signature=e.signature)
    docs = {
        "a": "The maximum loan amount for unsecured loans is 50000 dollars.",
        "b": "Fraud alerts are triggered when the fraud score exceeds 65.",
        "c": "HELOC products require a loan to value ratio below 0.8.",
    }
    for k, v in docs.items():
        store.add(k, v, e.embed(v), source=f"{k}.md", meta={})
    p = tmp_path / "idx.json"
    store.save(p)

    reloaded = VectorStore.load(p)
    assert len(reloaded) == 3
    assert reloaded.embedding_signature == e.signature

    hits = reloaded.search(e.embed("what is the maximum unsecured loan"), top_k=1)
    assert hits and hits[0][0].source == "a.md"


# ── end-to-end pipeline (offline, local backend) ─────────────────

def _make_corpus(root: Path):
    (root / "credit_policy.md").write_text(
        "# Credit Policy\n\n"
        "## DTI\n\nThe debt-to-income ratio cap for unsecured personal "
        "loans is 45 percent. Applications above this are declined.\n\n"
        "## Fraud\n\nThe fraud decline threshold is a fraud score of 65.\n",
        encoding="utf-8")
    (root / "products.md").write_text(
        "# Products\n\n## HELOC\n\nHome Equity Lines of Credit require a "
        "loan-to-value ratio below 0.8 and are secured by the property.\n",
        encoding="utf-8")
    (root / "rates.csv").write_text(
        "tier,rate\nA,5.5\nB,7.0\nC,9.5\n", encoding="utf-8")


def test_pipeline_end_to_end_offline():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _make_corpus(root)
        idx = root / "index.json"
        rag = RAGPipeline(index_path=idx, prefer_ollama=False, audit=False,
                          generation="ollama")

        stats = rag.ingest_dir(root)
        assert stats["files"] == 3
        assert stats["chunks"] >= 3
        assert idx.exists()

        # Relevant question → grounded answer citing the right source.
        ans = rag.query("What is the DTI cap for unsecured loans?")
        assert ans.grounded is True
        assert ans.sources
        assert ans.sources[0].source == "credit_policy.md"
        # Offline → extractive backend, and the answer contains the fact.
        assert ans.backend == "extractive"
        assert "45" in ans.text

        # Irrelevant question → honest refusal, no fabricated sources.
        miss = rag.query("What is the airspeed velocity of a swallow?",
                         min_score=0.3)
        assert miss.grounded is False
        assert miss.sources == []
        assert "could not find" in miss.text.lower()


def test_reingest_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "doc.md").write_text("The loan cap is 50000.", encoding="utf-8")
        idx = root / "index.json"
        rag = RAGPipeline(index_path=idx, prefer_ollama=False, audit=False,
                          generation="ollama")
        rag.ingest(root / "doc.md")
        n1 = len(rag.store)
        rag.ingest(root / "doc.md")  # same file again
        assert len(rag.store) == n1  # not duplicated


def test_empty_index_query_is_safe():
    with tempfile.TemporaryDirectory() as d:
        idx = Path(d) / "index.json"
        rag = RAGPipeline(index_path=idx, prefer_ollama=False, audit=False,
                          generation="ollama")
        ans = rag.query("anything?")
        assert ans.grounded is False
        assert "empty" in ans.text.lower()


# ── versioning & audit ───────────────────────────────────────────

def test_source_manifest_records_version():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "policy.md").write_text("The DTI cap is 45 percent.",
                                        encoding="utf-8")
        idx = root / "index.json"
        rag = RAGPipeline(index_path=idx, prefer_ollama=False, audit=False,
                          generation="ollama")
        src = rag.ingest(root / "policy.md")["sources"][0]
        ver = rag.store.source_version(src)
        assert ver.get("sha")            # content hash recorded
        assert ver.get("ingested_at")    # ingest timestamp recorded
        # retrieved chunks carry the version through
        ans = rag.query("what is the dti cap")
        assert ans.sources[0].version.get("sha") == ver["sha"]


def test_audit_log_written():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "policy.md").write_text("The DTI cap is 45 percent.",
                                        encoding="utf-8")
        idx = root / "index.json"
        audit_path = root / "audit.jsonl"
        rag = RAGPipeline(index_path=idx, prefer_ollama=False, audit=True,
                          generation="ollama")
        rag.audit.path = audit_path  # redirect to temp
        rag.ingest(root / "policy.md")
        rag.query("what is the dti cap", user="tester")
        events = rag.audit.tail(5)
        assert events and events[-1]["user"] == "tester"
        assert events[-1]["question"] == "what is the dti cap"


# ── generation provider resolution ───────────────────────────────

def test_generation_off_forces_extractive():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "policy.md").write_text("The DTI cap is 45 percent.",
                                        encoding="utf-8")
        idx = root / "index.json"
        rag = RAGPipeline(index_path=idx, prefer_ollama=False, audit=False,
                          generation="off")
        rag.ingest(root / "policy.md")
        ans = rag.query("what is the dti cap")
        # "off" never calls a model → extractive, still grounded + cited
        assert ans.backend == "extractive"
        assert ans.grounded is True and ans.sources


def test_anthropic_generation_skipped_without_key():
    import os
    from src.rag.pipeline import RAGPipeline as RP
    with tempfile.TemporaryDirectory() as d:
        idx = Path(d) / "index.json"
        rag = RP(index_path=idx, prefer_ollama=False, audit=False,
                 generation="anthropic")
        # With no API key, the anthropic path returns None (no crash/import).
        prev = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            assert rag._generate_anthropic("q", "ctx") is None
        finally:
            if prev is not None:
                os.environ["ANTHROPIC_API_KEY"] = prev


# ── loaders ──────────────────────────────────────────────────────

def test_loaders_skip_unsupported_and_read_csv():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "a.md").write_text("hello world", encoding="utf-8")
        (root / "b.csv").write_text("x,y\n1,2\n", encoding="utf-8")
        (root / "c.bin").write_bytes(b"\x00\x01\x02")
        docs = load_dir(root)
        sources = {doc.source for doc in docs}
        assert "a.md" in sources and "b.csv" in sources
        assert "c.bin" not in sources
        csv_doc = load_file(root / "b.csv")
        assert "x: 1" in csv_doc.text


# ── simple runner (no pytest needed) ─────────────────────────────

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests passed.")
