"""
src/app/chatbot.py
───────────────────
Friendly Streamlit chat interface for the Credit Risk Knowledge Assistant.

Anyone — underwriters, compliance, model-risk, new hires — asks a question
about the company's policies and procedures in plain English and gets an
answer grounded in the source documents, with clickable citations.

Design goals (borrowed from ChatGPT / Claude / Perplexity):
  • a short "what is this" panel and clickable example questions so a new
    user is never staring at a blank box wondering what to type;
  • plain-language answer-engine picker with a live readiness badge — no
    jargon, no config-file editing (paste a key right in the sidebar);
  • numbered, expandable source cards under every answer.

Run:
    streamlit run src/app/chatbot.py
"""

import os
import sys
import tempfile
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


# Plain-language answer-engine options → internal provider value.
ENGINE_CHOICES = {
    "✨ Best available (recommended)": "auto",
    "☁️ Cloud AI — Claude": "anthropic",
    "💻 On my computer — Ollama": "ollama",
    "📄 No AI — show document passages": "off",
}
ENGINE_HELP = {
    "auto": "Uses Claude if you've added a key below, otherwise a local "
            "model, otherwise shows passages. Good default.",
    "anthropic": "Writes answers using Claude in the cloud. Needs an API key "
                 "(below). No download.",
    "ollama": "Writes answers using a model on this computer (private, "
              "nothing leaves the machine). Needs Ollama installed.",
    "off": "No AI writing — just shows the most relevant passages from your "
           "documents, with citations.",
}
# How each answer was produced → a friendly label shown under the reply.
BACKEND_LABEL = {
    "anthropic": "☁️ Answered by Claude (cloud AI)",
    "ollama": "💻 Answered by Ollama (on-device AI)",
    "extractive": "📄 Showing document passages (no AI model connected)",
    "template": "",
}

EXAMPLE_QUESTIONS = [
    "What is the DTI cap for unsecured loans?",
    "What triggers a fraud decline?",
    "What are the scorecard risk tiers and their score cutoffs?",
    "What human oversight is required before a decline?",
]


def open_document(source: str):
    """Point the document reader at a source and expand it.

    Writes a *non-widget* key (`pending_doc`); the reader applies it to the
    selectbox before that widget is instantiated — Streamlit forbids setting
    a widget-keyed value after the widget exists.
    """
    st.session_state["pending_doc"] = source
    st.session_state["open_reader"] = True
    st.rerun()


def render_sources(ans, key_prefix=""):
    """Perplexity-style numbered, expandable source cards with 'open full doc'."""
    if not ans.sources:
        return
    with st.expander(f"🔎 Sources ({len(ans.sources)}) — click any to verify"):
        seen = set()
        for i, s in enumerate(ans.sources, 1):
            ver = s.version.get("ingested_at", "")
            st.markdown(f"**[{i}] {s.citation}**")
            st.caption(f"relevance {s.score:.2f}" +
                       (f"  ·  as-of {ver}" if ver else ""))
            body = s.text.split("]\n", 1)[-1].strip()
            st.caption(body[:800] + ("…" if len(body) > 800 else ""))
            if s.source not in seen:      # one "open" button per document
                seen.add(s.source)
                if st.button(f"📖 Read all of {s.source}",
                             key=f"open_{key_prefix}_{i}"):
                    open_document(s.source)


# ── Header ───────────────────────────────────────────────────────
st.markdown(
    """
    <div style="border-bottom:3px solid #1F3864;padding-bottom:12px;margin-bottom:8px">
      <div style="font-size:1.7rem;font-weight:700;color:#1F3864">
        📚 Credit Risk Knowledge Assistant
      </div>
      <div style="font-size:0.95rem;color:#555;margin-top:2px">
        Ask about your policies, procedures &amp; compliance rules — get
        answers with citations you can verify.
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

rag = get_pipeline()

# Deployed hosts: pick up an API key from Streamlit Secrets if one is set,
# so operators can preconfigure the cloud engine without code changes.
try:
    if "ANTHROPIC_API_KEY" in st.secrets and not os.getenv("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass  # no secrets.toml present — fine

status = rag.status()

# ── Sidebar ──────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("⚙️ Answer engine")
    choice = st.selectbox(
        "How should answers be written?",
        list(ENGINE_CHOICES.keys()),
        index=0,
        key="engine_sel",
        label_visibility="collapsed",
    )
    provider = ENGINE_CHOICES[choice]
    rag.generation = provider           # apply live, no restart needed
    st.caption(ENGINE_HELP[provider])

    # API-key box (only meaningful for the cloud engine).
    if provider in ("auto", "anthropic"):
        key_in = st.text_input(
            "Claude API key", type="password",
            placeholder="sk-ant-…",
            help="Get one at console.anthropic.com → API Keys. Stored only "
                 "for this session; never written to disk.")
        if key_in:
            os.environ["ANTHROPIC_API_KEY"] = key_in.strip()

    has_key = bool(os.getenv("ANTHROPIC_API_KEY"))

    # Live readiness badge — so the user always knows what will answer them.
    if provider == "off":
        st.info("📄 Answers will be document passages only.")
    elif provider == "ollama":
        st.info("💻 Will use a local Ollama model (passages if it isn't running).")
    elif has_key:
        st.success("✅ Ready — answers will be written by Claude.")
    elif provider == "anthropic":
        st.warning("⚠️ Add your Claude API key above to enable written answers.")
    else:  # auto, no key
        st.info("ℹ️ No key yet: will use Ollama if running, else show passages. "
                "Add a key above for polished answers with no install.")

    st.divider()
    st.subheader("📚 Knowledge base")
    c1, c2 = st.columns(2)
    c1.metric("Passages", status["num_chunks"])
    c2.metric("Documents", status["num_sources"])
    _eb = status["embedding_backend"]
    if _eb == "ollama":
        st.caption("Search: semantic (Ollama embeddings)")
    elif _eb == "voyage":
        st.caption("Search: semantic (Voyage cloud embeddings)")
    else:
        st.caption("Search: keyword (local). Run Ollama or set VOYAGE_API_KEY "
                   "for meaning-based search.")

    if st.button("🔄 (Re)load sample documents", use_container_width=True):
        with st.spinner("Indexing…"):
            stats = rag.ingest_dir(config.KNOWLEDGE_DIR, reset=True)
        st.success(f"Indexed {stats['files']} docs → {stats['chunks']} passages.")
        st.rerun()

    up = st.file_uploader("Add your own document",
                          type=["md", "txt", "csv", "pdf", "docx"])
    if up is not None and st.button("Add to knowledge base",
                                    use_container_width=True):
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
            st.success(f"Added {up.name}.")
            st.rerun()
        else:
            st.error(f"Could not read {up.name}.")
        tmp_path.unlink(missing_ok=True)

    with st.expander("Indexed documents"):
        for s in status["sources"]:
            v = status["manifest"].get(s, {})
            st.caption(f"• {s}  \n  _as-of {v.get('ingested_at', '—')}_")

    st.divider()
    st.caption(f"🧾 {status['audit_events']} questions logged (audit trail)")
    if st.session_state.get("history"):
        if st.button("🗑️ Clear chat", use_container_width=True):
            st.session_state.history = []
            st.rerun()

# ── "What is this?" explainer ────────────────────────────────────
st.session_state.setdefault("history", [])
first_visit = not st.session_state.history

with st.expander("ℹ️  What is this, and how do I use it?", expanded=first_visit):
    st.markdown(
        """
**What it is** — a private assistant that answers questions using **your own
documents** (credit policy, model card, scorecard, product & API guides). It
finds the relevant passages and writes a plain-English answer that **cites
where each fact came from**, so you can trust and verify it.

**How to use it**
1. Type a question below (or click an example).
2. Read the answer — then open **Sources** to see the exact passage behind it.
3. Want polished written answers with no install? Paste a Claude API key in
   the sidebar. Prefer fully private? Use the on-computer (Ollama) engine.

**Benefits**
- Answers are grounded in your documents and **cited** — no guessing.
- If the documents don't cover a question, it says so instead of making
  something up.
- Every question and answer is recorded in an **audit trail**.
- Runs privately: with the on-computer engine, nothing leaves your machine.

**Good to know (limitations)**
- It only knows what you've given it — add your own documents in the sidebar.
- Keyword search can miss synonyms (e.g. "TDS" vs "DTI"); Ollama's semantic
  search fixes that.
- The cloud (Claude) engine sends the question + retrieved passages to the
  Claude API — use the on-computer engine for confidential material.
        """
    )

# ── Empty knowledge base — auto-load the seed docs on first run ──
if status["num_chunks"] == 0:
    seed_files = [p for p in Path(config.KNOWLEDGE_DIR).glob("*") if p.is_file()]
    if seed_files and not st.session_state.get("_auto_ingested"):
        st.session_state["_auto_ingested"] = True   # guard against a loop
        with st.spinner("Preparing the knowledge base…"):
            rag.ingest_dir(config.KNOWLEDGE_DIR, reset=True)
        st.rerun()
    st.warning("Your knowledge base is empty. Add a document in the sidebar "
               "to get started.")
    st.stop()

# ── "What can I ask about?" — derived from the loaded documents ───
outline = rag.outline()
topic_list = rag.topics(limit=8)

with st.expander("📋  What can I ask about?", expanded=first_visit):
    st.caption("This assistant answers only from the documents below — here's "
               "what each one covers:")
    for d in outline:
        secs = " · ".join(d["sections"]) if d["sections"] else "—"
        st.markdown(f"**{d['title']}**  \n<span style='color:#666'>{secs}</span>",
                    unsafe_allow_html=True)

# ── Document reader — read any source in full to verify answers ──
docs = status["sources"]
# Apply a pending "open this document" request before the selectbox exists.
_pending_doc = st.session_state.pop("pending_doc", None)
if _pending_doc and _pending_doc in docs:
    st.session_state["doc_reader_sel"] = _pending_doc
with st.expander("📄  Read the source documents (verify answers yourself)",
                 expanded=st.session_state.pop("open_reader", False)):
    st.caption("Read a whole document top-to-bottom and check the assistant's "
               "answers against the original — this is grounded RAG: every "
               "answer traces back to text you can see here.")
    sel = st.selectbox("Document", docs, key="doc_reader_sel")
    if sel:
        v = status["manifest"].get(sel, {})
        st.caption(f"Version as-of {v.get('ingested_at', '—')}  ·  "
                   f"content hash `{v.get('sha', '—')}`")
        text = rag.document_text(sel)
        if not text:
            st.info("Full text isn't stored for this document — re-ingest to "
                    "enable the reader.")
        elif sel.lower().endswith((".md", ".markdown")):
            st.markdown(text)
        else:
            st.text(text)

# ── Chat history ─────────────────────────────────────────────────
for turn_i, turn in enumerate(st.session_state.history):
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])
        ans = turn.get("answer")
        if ans is not None:
            render_sources(ans, key_prefix=str(turn_i))
            label = BACKEND_LABEL.get(ans.backend, "")
            if label:
                st.caption(label)


def topic_chips(topics, key_prefix):
    """Render clickable topic buttons; return the clicked question or None."""
    clicked = None
    cols = st.columns(2)
    for i, t in enumerate(topics):
        if cols[i % 2].button(f"📄 {t}", use_container_width=True,
                              key=f"{key_prefix}{i}"):
            clicked = f"What does the documentation say about {t}?"
    return clicked


pending = None

# Empty-state coaching (ChatGPT/Claude style): specific examples + topics.
if first_visit:
    st.markdown("**Try a specific question:**")
    cols = st.columns(2)
    for i, ex in enumerate(EXAMPLE_QUESTIONS):
        if cols[i % 2].button(ex, use_container_width=True, key=f"ex{i}"):
            pending = ex
    if topic_list:
        st.markdown("**…or explore a topic:**")
        pending = topic_chips(topic_list[:6], "topic_") or pending

# Helpful redirect after a "not found" answer — turn dead-ends into guidance.
elif st.session_state.history:
    last = st.session_state.history[-1]
    last_ans = last.get("answer")
    if last_ans is not None and not last_ans.grounded and topic_list:
        st.markdown("**Not sure what to ask? I can help with topics like:**")
        pending = topic_chips(topic_list[:6], "retry_") or pending

# ── Input ────────────────────────────────────────────────────────
typed = st.chat_input("Ask about a policy, procedure, model, or compliance rule…")
question = typed or pending

if question:
    st.session_state.history.append({"role": "user", "content": question})
    with st.spinner("Searching your documents…"):
        ans = rag.query(question)
    if ans.grounded:
        content = ans.text
    else:
        # Friendlier refusal that points back to the corpus scope.
        hint = (" I can only answer from the loaded documents — try a topic "
                "from **📋 What can I ask about?** above.") if topic_list else ""
        content = f":orange[{ans.text}]{hint}"
    st.session_state.history.append(
        {"role": "assistant", "content": content, "answer": ans})
    st.rerun()
