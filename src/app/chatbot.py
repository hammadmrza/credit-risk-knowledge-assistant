"""
src/app/chatbot.py
───────────────────
Streamlit chat interface for the Credit Risk Knowledge Assistant.

Underwriters, compliance staff, and model-risk teams ask questions about
policies and procedures in plain English and get answers grounded in the
company's own documents — every answer shows expandable source cards with
the exact passage, its relevance, and the document version it came from.

Run:
    streamlit run src/app/chatbot.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

import config
from src.rag.pipeline import RAGPipeline

st.set_page_config(page_title="Knowledge Assistant", page_icon="📚",
                   layout="wide", initial_sidebar_state="expanded")


@st.cache_resource
def get_pipeline() -> RAGPipeline:
    return RAGPipeline()


def _ingest_seed(rag: RAGPipeline):
    with st.spinner("Ingesting knowledge base…"):
        stats = rag.ingest_dir(config.KNOWLEDGE_DIR, reset=True)
    st.success(f"Indexed {stats['files']} document(s) → {stats['chunks']} "
               f"passage(s).")


# ── Header ───────────────────────────────────────────────────────
st.markdown(
    """
    <div style="border-bottom:3px solid #1F3864;padding-bottom:12px;margin-bottom:16px">
      <div style="font-size:1.7rem;font-weight:700;color:#1F3864">
        📚 Credit Risk Knowledge Assistant
      </div>
      <div style="font-size:0.9rem;color:#555;font-style:italic;margin-top:2px">
        Grounded, cited answers over your policies, procedures &amp; compliance docs — on-premise
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

rag = get_pipeline()
status = rag.status()

# ── Sidebar: knowledge base controls & health ───────────────────
with st.sidebar:
    st.subheader("Knowledge base")
    st.metric("Passages indexed", status["num_chunks"])
    st.metric("Documents", status["num_sources"])

    backend = status["embedding_backend"]
    if backend == "ollama":
        st.success("Retrieval: Ollama (semantic)")
    else:
        st.info("Retrieval: local (lexical). Start Ollama + pull "
                "`nomic-embed-text` for semantic search.")

    gen = status.get("generation_active", "")
    if gen.startswith("anthropic (Claude"):
        st.success("Answers: Claude API (cloud)")
    elif gen.startswith("anthropic (no API key"):
        st.warning("Answers: Claude selected but ANTHROPIC_API_KEY is unset — "
                   "set it to enable written answers.")
    elif gen.startswith("off"):
        st.info("Answers: passages only (generation off).")
    else:
        st.info("Answers: Ollama, or passages if offline. Set "
                "`ANTHROPIC_API_KEY` for cloud-written answers (no download).")

    st.caption(f"Audit events logged: {status['audit_events']}")

    st.divider()
    if st.button("📥 (Re)ingest knowledge/ folder", use_container_width=True):
        _ingest_seed(rag)
        st.cache_resource.clear()
        st.rerun()

    up = st.file_uploader("Add a document",
                          type=["md", "txt", "csv", "pdf", "docx"])
    if up is not None and st.button("Ingest uploaded file",
                                    use_container_width=True):
        import tempfile
        suffix = Path(up.name).suffix or ".txt"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(up.getvalue())
            tmp_path = Path(tmp.name)
        from src.rag.loaders import load_file
        doc = load_file(tmp_path)
        if doc:
            doc.source = up.name
            rag._add_document(doc.text, doc.source, doc.meta)
            rag._finalize()
            st.success(f"Ingested {up.name}.")
            st.cache_resource.clear()
            st.rerun()
        else:
            st.error(f"Could not read {up.name}.")
        tmp_path.unlink(missing_ok=True)

    st.divider()
    with st.expander("Indexed documents"):
        for s in status["sources"]:
            v = status["manifest"].get(s, {})
            when = v.get("ingested_at", "—")
            st.caption(f"• {s}  \n  _as-of {when}_")

# ── Empty-state guidance ─────────────────────────────────────────
if status["num_chunks"] == 0:
    st.warning("The knowledge base is empty. Click **(Re)ingest knowledge/ "
               "folder** in the sidebar to index the seed documents, or "
               "upload your own.")
    st.stop()

# ── Chat state ───────────────────────────────────────────────────
if "history" not in st.session_state:
    st.session_state.history = []  # list of dicts: {role, content, answer?}

# Replay history
for turn in st.session_state.history:
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])
        ans = turn.get("answer")
        if ans and ans.sources:
            with st.expander(f"📎 {len(ans.sources)} source(s) — click to verify"):
                for i, s in enumerate(ans.sources, 1):
                    ver = s.version.get("ingested_at", "")
                    st.markdown(
                        f"**[{i}] {s.citation}**  · relevance "
                        f"`{s.score:.2f}`" + (f" · _as-of {ver}_" if ver else ""))
                    body = s.text.split("]\n", 1)[-1].strip()
                    st.caption(body[:800] + ("…" if len(body) > 800 else ""))

# ── Chat input ───────────────────────────────────────────────────
q = st.chat_input("Ask about a policy, procedure, model, or compliance rule…")
if q:
    st.session_state.history.append({"role": "user", "content": q})
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant"):
        with st.spinner("Searching the knowledge base…"):
            ans = rag.query(q)
        if not ans.grounded:
            st.markdown(f":orange[{ans.text}]")
        else:
            st.markdown(ans.text)
            with st.expander(f"📎 {len(ans.sources)} source(s) — click to verify"):
                for i, s in enumerate(ans.sources, 1):
                    ver = s.version.get("ingested_at", "")
                    st.markdown(
                        f"**[{i}] {s.citation}**  · relevance "
                        f"`{s.score:.2f}`" + (f" · _as-of {ver}_" if ver else ""))
                    body = s.text.split("]\n", 1)[-1].strip()
                    st.caption(body[:800] + ("…" if len(body) > 800 else ""))
        st.caption(f"_answer backend: {ans.backend}_")
    st.session_state.history.append(
        {"role": "assistant", "content": ans.text if ans.grounded
         else f":orange[{ans.text}]", "answer": ans})
