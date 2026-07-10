"""
eval/eval_set.py
─────────────────
A small retrieval-quality evaluation for the knowledge base.

Each item is a question paired with the document that *should* be its
top source. The runner ingests the seed knowledge base with the local
(deterministic, offline) embedding backend, runs every question, and
reports recall@k — the fraction of questions whose expected document
appears in the top-k retrieved passages.

Run it in CI so retrieval quality can't silently regress:

    python eval/eval_set.py            # prints a report, exits non-zero on fail
    python eval/eval_set.py --top-k 5  # override k

This evaluates *retrieval* (which passages come back), which is offline
and deterministic — it does not need Ollama or a GPU. Generation quality
is a separate concern handled by the grounded-prompt + refusal logic.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from src.rag.pipeline import RAGPipeline

# (question, expected source filename substring)
EVAL_ITEMS = [
    ("What are the hard policy rules in the decision engine?", "CREDIT_POLICY"),
    ("How does fraud screening work as the first gate?", "CREDIT_POLICY"),
    ("What is the human authority matrix for approvals?", "CREDIT_POLICY"),
    ("What are the board-approved quantitative risk appetite limits?", "CREDIT_POLICY"),
    ("Which exposures are prohibited?", "CREDIT_POLICY"),
    ("What is the intended use of the PD model?", "MODEL_CARD"),
    ("What are the documented limitations of the model?", "MODEL_CARD"),
    ("What human oversight is required before a decline?", "MODEL_CARD"),
    ("Describe the fairness evaluation methodology.", "MODEL_CARD"),
    ("What is the v1.1 segmented product models challenger?", "MODEL_CARD"),
    ("What are the seven tabs in the platform?", "PRODUCT_GUIDE"),
    ("How does batch portfolio scoring work?", "PRODUCT_GUIDE"),
    ("What does calibration-first validation mean?", "PRODUCT_GUIDE"),
    ("How do I score a single applicant with the API?", "API_GUIDE"),
    ("How do I do batch scoring via CSV upload?", "API_GUIDE"),
    ("How is error handling done in the API?", "API_GUIDE"),
    ("How do I check the health of the API server?", "API_GUIDE"),
    ("What is the score-to-PD lookup table in the scorecard?", "CREDIT_SCORECARD"),
    ("What are the scorecard adverse action reason codes?", "CREDIT_SCORECARD"),
    ("How are points attributed to features in the scorecard?", "CREDIT_SCORECARD"),
]

# Minimum acceptable recall@k. Below this, the eval fails.
RECALL_THRESHOLD = 0.70


def run(top_k: int = 5) -> float:
    with tempfile.TemporaryDirectory() as d:
        idx = Path(d) / "eval_index.json"
        # Local backend → deterministic, offline; no audit noise.
        rag = RAGPipeline(index_path=idx, prefer_ollama=False, audit=False)
        rag.ingest_dir(config.KNOWLEDGE_DIR)

        hits = 0
        print(f"\nRetrieval eval — recall@{top_k} over {len(EVAL_ITEMS)} "
              f"questions (backend: {rag.embedder.backend})")
        print("─" * 72)
        for question, expected in EVAL_ITEMS:
            chunks = rag.retrieve(question, top_k=top_k, min_score=0.0)
            got = [c.source for c in chunks]
            ok = any(expected in s for s in got)
            hits += ok
            mark = "✓" if ok else "✗"
            top = got[0] if got else "(none)"
            print(f"  {mark}  [{expected:<13}] top={top:<20} :: {question}")

        recall = hits / len(EVAL_ITEMS)
        print("─" * 72)
        print(f"  recall@{top_k} = {recall:.2f}  ({hits}/{len(EVAL_ITEMS)})  "
              f"threshold {RECALL_THRESHOLD:.2f}")
        return recall


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RAG retrieval eval.")
    ap.add_argument("--top-k", type=int, default=5)
    args = ap.parse_args(argv)
    recall = run(top_k=args.top_k)
    if recall < RECALL_THRESHOLD:
        print(f"\nFAIL — recall {recall:.2f} below threshold "
              f"{RECALL_THRESHOLD:.2f}")
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
