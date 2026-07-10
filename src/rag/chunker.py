"""
src/rag/chunker.py
───────────────────
Split a document into overlapping, retrieval-sized chunks.

Strategy: greedily pack whole paragraphs into chunks up to
``chunk_size`` characters. Paragraphs larger than the limit are split on
sentence boundaries, then on hard character boundaries as a last resort.
Adjacent chunks share ``overlap`` characters of tail context so a fact
that straddles a boundary is still fully present in at least one chunk.

Markdown headings are tracked and prepended to each chunk as a light
breadcrumb (e.g. ``[Credit Policy > DTI Limits]``) so a retrieved chunk
carries its section context into the LLM prompt.
"""

from __future__ import annotations

import re
from typing import List, Optional

import config

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


class Chunk:
    """A slice of a document, ready to embed."""

    __slots__ = ("text", "source", "index", "meta")

    def __init__(self, text: str, source: str, index: int,
                 meta: Optional[dict] = None):
        self.text = text
        self.source = source
        self.index = index          # ordinal position within the document
        self.meta = meta or {}

    def __repr__(self) -> str:
        return (f"Chunk(source={self.source!r}, index={self.index}, "
                f"chars={len(self.text)})")


def _split_paragraphs(text: str):
    """Yield (paragraph_text, heading_breadcrumb) preserving markdown sections."""
    heading_stack: List[tuple] = []  # (level, title)
    buf: List[str] = []

    def breadcrumb() -> str:
        return " > ".join(t for _, t in heading_stack)

    for line in text.splitlines():
        m = _HEADING_RE.match(line.strip())
        if m:
            if buf:
                yield "\n".join(buf).strip(), breadcrumb()
                buf = []
            level = len(m.group(1))
            title = m.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
        elif line.strip() == "":
            if buf:
                yield "\n".join(buf).strip(), breadcrumb()
                buf = []
        else:
            buf.append(line)
    if buf:
        yield "\n".join(buf).strip(), breadcrumb()


def _hard_split(text: str, size: int) -> List[str]:
    """Split an over-long paragraph on sentence, then character, boundaries."""
    if len(text) <= size:
        return [text]
    out: List[str] = []
    cur = ""
    for sent in _SENT_SPLIT_RE.split(text):
        if not sent:
            continue
        if len(cur) + len(sent) + 1 <= size:
            cur = f"{cur} {sent}".strip()
        else:
            if cur:
                out.append(cur)
            if len(sent) <= size:
                cur = sent
            else:  # a single monster "sentence" — chop by characters
                for i in range(0, len(sent), size):
                    out.append(sent[i:i + size])
                cur = ""
    if cur:
        out.append(cur)
    return out


def chunk_document(text: str,
                   source: str,
                   chunk_size: Optional[int] = None,
                   overlap: Optional[int] = None,
                   base_meta: Optional[dict] = None) -> List[Chunk]:
    """Chunk one document's text into overlapping Chunks."""
    chunk_size = chunk_size or config.RAG_CHUNK_SIZE
    overlap = overlap if overlap is not None else config.RAG_CHUNK_OVERLAP
    base_meta = base_meta or {}

    # 1. Pack paragraphs (respecting headings) into raw chunks.
    packed: List[tuple] = []  # (text, breadcrumb)
    cur, cur_crumb = "", ""
    for para, crumb in _split_paragraphs(text):
        if not para:
            continue
        for piece in _hard_split(para, chunk_size):
            if not cur:
                cur, cur_crumb = piece, crumb
            elif len(cur) + len(piece) + 2 <= chunk_size:
                cur = f"{cur}\n\n{piece}"
            else:
                packed.append((cur, cur_crumb))
                cur, cur_crumb = piece, crumb
    if cur:
        packed.append((cur, cur_crumb))

    # 2. Add tail-overlap from the previous chunk for boundary safety.
    chunks: List[Chunk] = []
    for i, (body, crumb) in enumerate(packed):
        text_out = body
        if overlap > 0 and i > 0:
            prev_tail = packed[i - 1][0][-overlap:]
            text_out = f"{prev_tail}\n\n{body}"
        header = f"[{source}" + (f" › {crumb}" if crumb else "") + "]\n"
        meta = dict(base_meta)
        meta["breadcrumb"] = crumb
        chunks.append(Chunk(text=header + text_out, source=source,
                            index=i, meta=meta))
    return chunks
