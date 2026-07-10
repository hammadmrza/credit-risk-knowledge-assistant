"""
src/rag/
─────────
Retrieval-Augmented Generation (RAG) engine for the Credit Risk
Knowledge Assistant.

A company points this pipeline at its own documents — credit policies,
product guides, model cards, regulatory filings, archived reports — and
then asks questions in plain English. Answers are grounded in the
retrieved passages and cite their sources, so users can verify every
claim against the underlying document.

WHY LOCAL-FIRST?
────────────────
Document content (which may contain PII or confidential policy) never
leaves the company's infrastructure. Embeddings and generation run
through a local Ollama server. When Ollama is unavailable the pipeline
degrades gracefully to a deterministic local embedding and an extractive
answer, so it works out of the box with no GPU and no cloud dependency.

Every query is written to an append-only audit trail, and every source
carries the version (ingest time + content hash) of the document it was
drawn from.

PUBLIC API
──────────
    from src.rag import RAGPipeline

    rag = RAGPipeline()
    rag.ingest("CREDIT_POLICY.md")          # a file
    rag.ingest_dir(".", recursive=True)      # a whole tree
    answer = rag.query("What is the DTI cap for unsecured loans?")
    print(answer.text)
    for src in answer.sources:
        print(src.source, src.score)
"""

from src.rag.pipeline import RAGPipeline, Answer, RetrievedChunk

__all__ = ["RAGPipeline", "Answer", "RetrievedChunk"]
