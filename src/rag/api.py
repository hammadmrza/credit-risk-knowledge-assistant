"""
src/rag/api.py
───────────────
FastAPI surface for the RAG knowledge base.

Exposes an ``APIRouter`` (mounted under /rag in the main scoring API) and
a standalone ``app`` so the knowledge base can run on its own:

    uvicorn src.rag.api:app --host 0.0.0.0 --port 8100 --reload

ENDPOINTS
─────────
  POST /rag/query          — ask a question, get a grounded answer + sources
  POST /rag/ingest/paths   — index files/dirs already on the server
  POST /rag/ingest/text    — index a pasted block of text
  POST /rag/ingest/upload  — upload a document (multipart) and index it
  POST /rag/reset          — clear the index
  GET  /rag/status         — index statistics and active backend

The pipeline is created once and reused across requests. Ingestion
mutates the shared index, so writes are serialised behind a lock.
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from src.rag.pipeline import RAGPipeline

router = APIRouter(prefix="/rag", tags=["rag"])

# Single shared pipeline + a lock guarding ingest/reset (index writes).
_rag = RAGPipeline()
_lock = threading.Lock()


# ── Schemas ──────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: Optional[int] = Field(default=None, ge=1, le=20)
    min_score: Optional[float] = Field(default=None, ge=0, le=1)

    class Config:
        json_schema_extra = {"example": {
            "question": "What is the DTI cap for unsecured loans?"}}


class SourceOut(BaseModel):
    source: str
    citation: str
    score: float
    excerpt: str


class QueryResponse(BaseModel):
    answer: str
    grounded: bool
    backend: str
    sources: List[SourceOut]


class IngestPathsRequest(BaseModel):
    paths: List[str] = Field(..., min_length=1)
    recursive: bool = True
    reset: bool = False


class IngestTextRequest(BaseModel):
    text: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)


class IngestResponse(BaseModel):
    files: int
    chunks: int
    sources: List[str]


# ── Endpoints ────────────────────────────────────────────────────

@router.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    ans = _rag.query(req.question, top_k=req.top_k, min_score=req.min_score)
    return QueryResponse(
        answer=ans.text, grounded=ans.grounded, backend=ans.backend,
        sources=[
            SourceOut(
                source=s.source, citation=s.citation, score=s.score,
                excerpt=s.text.split("]\n", 1)[-1][:400])
            for s in ans.sources
        ],
    )


@router.post("/ingest/paths", response_model=IngestResponse)
def ingest_paths(req: IngestPathsRequest):
    with _lock:
        if req.reset:
            _rag.reset(save=False)
        files = chunks = 0
        srcs: List[str] = []
        for target in req.paths:
            p = Path(target)
            if p.is_dir():
                r = _rag.ingest_dir(p, recursive=req.recursive)
            elif p.is_file():
                r = _rag.ingest(p)
            else:
                raise HTTPException(404, f"Path not found: {target}")
            files += r["files"]
            chunks += r["chunks"]
            srcs.extend(r["sources"])
    return IngestResponse(files=files, chunks=chunks, sources=srcs)


@router.post("/ingest/text", response_model=IngestResponse)
def ingest_text(req: IngestTextRequest):
    with _lock:
        r = _rag.ingest_text(req.text, req.source)
    return IngestResponse(**r)


@router.post("/ingest/upload", response_model=IngestResponse)
async def ingest_upload(file: UploadFile = File(...)):
    """Upload a document (md/txt/csv/pdf/docx) and index it."""
    suffix = Path(file.filename or "upload").suffix or ".txt"
    data = await file.read()
    # Write to a temp file so the loaders (which dispatch on suffix) can read it.
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        with _lock:
            doc = _load_upload(tmp_path, file.filename or tmp_path.name)
            if doc is None:
                raise HTTPException(
                    415, f"Unsupported or empty file: {file.filename}")
            n = _rag._add_document(doc.text, doc.source, doc.meta)
            _rag._finalize()
        return IngestResponse(files=1, chunks=n, sources=[doc.source])
    finally:
        tmp_path.unlink(missing_ok=True)


def _load_upload(tmp_path: Path, original_name: str):
    from src.rag.loaders import load_file
    doc = load_file(tmp_path)
    if doc is not None:
        doc.source = original_name  # show the user's filename, not the temp path
    return doc


@router.post("/reset")
def reset():
    with _lock:
        _rag.reset()
    return {"status": "ok", "message": "Knowledge base cleared."}


@router.get("/status")
def status():
    return _rag.status()


# ── Standalone app ───────────────────────────────────────────────

app = FastAPI(
    title="Credit Risk Platform — RAG Knowledge Base",
    description=(
        "Grounded question-answering over a company's own documents and "
        "archives. Local-first (Ollama) with deterministic offline "
        "fallbacks. Answers cite the source passages they are drawn from."),
    version="1.0.0",
)
app.include_router(router)


@app.get("/health")
def health():
    st = _rag.status()
    return {"status": "healthy", "num_chunks": st["num_chunks"],
            "backend": st["embedding_backend"]}
