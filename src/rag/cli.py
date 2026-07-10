"""
src/rag/cli.py
───────────────
Command-line interface for the RAG knowledge base.

    # Index a whole documentation tree (rebuild from scratch)
    python -m src.rag.cli ingest . --reset

    # Index specific files or a folder
    python -m src.rag.cli ingest CREDIT_POLICY.md docs/

    # Ask a question
    python -m src.rag.cli query "What is the DTI cap for unsecured loans?"

    # Interactive Q&A session
    python -m src.rag.cli chat

    # Inspect the index
    python -m src.rag.cli status
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.rag.pipeline import RAGPipeline


def _log_setup(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s  %(message)s")


def cmd_ingest(args) -> int:
    rag = RAGPipeline(prefer_ollama=not args.local)
    if args.reset:
        rag.reset(save=False)
    totals = {"files": 0, "chunks": 0}
    for target in args.paths:
        p = Path(target)
        if p.is_dir():
            r = rag.ingest_dir(p, recursive=not args.no_recursive)
        elif p.is_file():
            r = rag.ingest(p)
        else:
            print(f"  ! skipped (not found): {target}")
            continue
        totals["files"] += r["files"]
        totals["chunks"] += r["chunks"]
        print(f"  + {target}: {r['files']} file(s), {r['chunks']} chunk(s)")
    print(f"\nIndexed {totals['files']} file(s) → {totals['chunks']} chunk(s) "
          f"[backend: {rag.embedder.backend}]")
    print(f"Index saved to {rag.index_path}")
    return 0


def _print_answer(ans) -> None:
    print("\n" + ans.text + "\n")
    if ans.sources:
        print("─" * 60)
        print(f"Sources ({ans.backend}):")
        for i, s in enumerate(ans.sources, 1):
            print(f"  [{i}] {s.citation}  (relevance {s.score:.2f})")
    elif not ans.grounded:
        print(f"[{ans.backend}]")


def cmd_query(args) -> int:
    rag = RAGPipeline(prefer_ollama=not args.local)
    ans = rag.query(args.question, top_k=args.top_k)
    _print_answer(ans)
    return 0


def cmd_chat(args) -> int:
    rag = RAGPipeline(prefer_ollama=not args.local)
    st = rag.status()
    print(f"RAG chat — {st['num_chunks']} chunks from {st['num_sources']} "
          f"source(s), backend '{st['embedding_backend']}'.")
    print("Type a question, or 'exit' to quit.\n")
    while True:
        try:
            q = input("you › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if q.lower() in {"exit", "quit", "q"}:
            break
        if not q:
            continue
        _print_answer(rag.query(q, top_k=args.top_k))
        print()
    return 0


def cmd_status(args) -> int:
    rag = RAGPipeline(prefer_ollama=not args.local)
    st = rag.status()
    print("RAG knowledge base status")
    print("─" * 40)
    print(f"  Index file        : {st['index_path']}")
    print(f"  Chunks indexed    : {st['num_chunks']}")
    print(f"  Distinct sources  : {st['num_sources']}")
    print(f"  Embedding backend : {st['embedding_backend']}")
    print(f"  Index signature   : {st['index_signature'] or '(empty)'}")
    if st["sources"]:
        print("  Sources:")
        for s in st["sources"]:
            print(f"    - {s}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.rag.cli",
        description="RAG knowledge base for the Credit Risk Platform.")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Show info-level logs.")
    p.add_argument("--local", action="store_true",
                   help="Force the local embedding backend (ignore Ollama).")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("ingest", help="Index files or directories.")
    pi.add_argument("paths", nargs="+", help="Files and/or directories.")
    pi.add_argument("--reset", action="store_true",
                    help="Clear the index before ingesting.")
    pi.add_argument("--no-recursive", action="store_true",
                    help="Do not descend into subdirectories.")
    pi.set_defaults(func=cmd_ingest)

    pq = sub.add_parser("query", help="Ask a single question.")
    pq.add_argument("question")
    pq.add_argument("--top-k", type=int, default=None)
    pq.set_defaults(func=cmd_query)

    pc = sub.add_parser("chat", help="Interactive Q&A session.")
    pc.add_argument("--top-k", type=int, default=None)
    pc.set_defaults(func=cmd_chat)

    ps = sub.add_parser("status", help="Show index statistics.")
    ps.set_defaults(func=cmd_status)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    _log_setup(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
