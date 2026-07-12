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
import re
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
def get_pipeline(build_version: str) -> RAGPipeline:
    """Cached pipeline, keyed on the app's build version.

    Streamlit keeps @st.cache_resource objects alive across code redeploys on a
    warm host. Without a cache key, a code update that changes retrieval would
    keep serving the *old* pipeline object (old methods) until a manual reboot —
    silently negating the update. Passing the build version makes a new version
    mint a fresh pipeline automatically, no reboot needed.
    """
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

# Plain-language glossary of common credit-risk terms. Only entries whose term
# actually appears in the loaded documents are shown (see matched_glossary), so
# the glossary stays honest for any corpus — it never defines something the
# documents don't use. Each entry: (display term, detection regex, definition).
GLOSSARY = [
    ("PD — Probability of Default", r"\bPD\b|probabilit(?:y|ies) of default",
     "The chance a borrower fails to repay over a set period (usually 12 "
     "months). Higher PD means higher risk."),
    ("LGD — Loss Given Default", r"\bLGD\b|loss given default",
     "The share of the money you'd actually lose if a borrower defaults, after "
     "any recoveries or collateral."),
    ("EAD — Exposure at Default", r"\bEAD\b|exposure at default",
     "How much is owed at the moment of default — the amount actually at risk."),
    ("DTI — Debt-to-Income", r"\bDTI\b|debt[- ]to[- ]income",
     "Monthly debt payments as a share of income. A core affordability check; "
     "above the policy cap it triggers a decline."),
    ("TDS / GDS — Debt-service ratios", r"\bTDS\b|\bGDS\b|debt service",
     "Canadian affordability ratios — GDS covers housing costs, TDS covers all "
     "debt, each as a share of income. Close cousins of DTI."),
    ("LTV — Loan-to-Value", r"\bLTV\b|loan[- ]to[- ]value",
     "The loan amount divided by the value of the collateral (e.g. a home). "
     "Higher LTV means less cushion and more risk."),
    ("Basel III", r"basel\s*(?:iii|3)",
     "The international framework setting how much capital a lender must hold "
     "against its risks."),
    ("IFRS 9", r"ifrs\s*9",
     "The accounting standard that makes lenders reserve for *expected* future "
     "credit losses, not just losses already incurred."),
    ("ECL — Expected Credit Loss", r"\bECL\b|expected credit loss",
     "The reserve a lender books for likely future losses — roughly PD × LGD × "
     "EAD."),
    ("Scorecard", r"scorecard",
     "A points-based model that ranks applicants by risk (here, 300–850). A "
     "higher score means lower risk."),
    ("Risk tier", r"risk tier|tier\s*[A-E]\b",
     "Letter grades (A–E here) that bucket applicants by score band, used for "
     "pricing and decisions."),
    ("WoE / IV", r"\bWoE\b|weight of evidence|information value|\bIV\b",
     "Weight of Evidence and Information Value — statistics used to build and "
     "sanity-check scorecard features."),
    ("SHAP", r"\bSHAP\b",
     "An explainability method showing how much each factor pushed a decision "
     "up or down — used to produce adverse-action reasons."),
    ("Adverse action", r"adverse action",
     "The notice and reasons a lender must give when it declines someone — a "
     "fair-lending requirement."),
    ("OSFI / E-23", r"\bOSFI\b|E-?23",
     "OSFI is Canada's federal banking regulator; its Guideline E-23 sets "
     "expectations for managing model risk."),
    ("PIT / TTC", r"\bPIT\b|\bTTC\b|point[- ]in[- ]time|through[- ]the[- ]cycle",
     "Point-in-Time vs Through-the-Cycle — whether a risk estimate reflects "
     "today's conditions or a long-run average."),
    ("Override", r"\boverride\b",
     "A manual reversal of the system's decision by an authorised analyst, "
     "recorded with a reason."),
]


def matched_glossary(corpus_text: str):
    """Glossary entries whose term actually appears in the loaded documents."""
    return [(term, defn) for term, pat, defn in GLOSSARY
            if re.search(pat, corpus_text, re.IGNORECASE)]


def topic_chips(topics, key_prefix):
    """Render clickable topic buttons; return the clicked question or None.

    The generated query is just "Tell me about {topic}" — a plain phrasing
    whose only content words are the topic itself. An earlier template ("What
    does the documentation say about {topic}?") injected the word
    "documentation", which polluted keyword retrieval by pulling in
    Document-Control / Product-Guide passages ahead of the actual section.
    """
    clicked = None
    cols = st.columns(2)
    for i, t in enumerate(topics):
        if cols[i % 2].button(f"📄 {t}", use_container_width=True,
                              key=f"{key_prefix}{i}"):
            clicked = f"Tell me about {t}"
    return clicked


def open_document(source: str):
    """Point the document reader (in the 📄 Documents tab) at a source.

    Writes a *non-widget* key (`pending_doc`); the reader applies it to the
    selectbox before that widget is instantiated — Streamlit forbids setting
    a widget-keyed value after the widget exists. Streamlit can't switch tabs
    programmatically, so we also set a flag to show a "opened below" hint.
    """
    st.session_state["pending_doc"] = source
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
                if st.button(f"📖 Open {s.source} in the 📄 Documents tab",
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

# getattr fallback: on a warm Streamlit host a redeploy can re-run this script
# while an older `config` module is still cached in memory (Streamlit doesn't
# reload imported modules on rerun). Tolerate that gracefully instead of
# crashing; a full app reboot loads every module fresh.
rag = get_pipeline(getattr(config, "INDEX_BUILD_VERSION", "bootstrap"))

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

# ── Orientation ──────────────────────────────────────────────────
st.session_state.setdefault("history", [])
first_visit = not st.session_state.history

# ── Knowledge base: seed on first run, and self-heal a stale index ──
# A hosted deploy persists the index on disk. When a code update changes
# chunking/retrieval, that saved index would otherwise keep being served —
# giving wrong "I can't find that" answers. So we rebuild automatically when
# the stored build version is older than the current one. User-uploaded docs
# are protected: we only auto-rebuild the *seed-only* corpus; if custom docs
# are present we show a one-click Rebuild prompt instead of wiping them.
seed_names = {p.name for p in Path(config.KNOWLEDGE_DIR).glob("*") if p.is_file()}
_stale = status.get("index_build_version") != status.get("current_build_version")
_only_seed = bool(status["sources"]) and set(status["sources"]).issubset(seed_names)

if status["num_chunks"] == 0:
    if seed_names and not st.session_state.get("_auto_ingested"):
        st.session_state["_auto_ingested"] = True   # guard against a loop
        with st.spinner("Preparing the knowledge base…"):
            rag.ingest_dir(config.KNOWLEDGE_DIR, reset=True)
        st.rerun()
    st.warning("Your knowledge base is empty. Add a document in the sidebar "
               "to get started.")
    st.stop()
elif _stale and _only_seed and not st.session_state.get("_healed_index"):
    # Stale index built by an older version, seed-only → rebuild silently.
    st.session_state["_healed_index"] = True
    with st.spinner("Updating the knowledge base to the latest version…"):
        rag.ingest_dir(config.KNOWLEDGE_DIR, reset=True)
    st.rerun()
elif _stale and not _only_seed:
    # Custom docs present — don't wipe them; offer a one-click rebuild.
    st.warning("This knowledge base was built by an older version. Answers may "
               "be less accurate until it's rebuilt.")
    if st.button("🔄 Rebuild index now (re-indexes current documents)"):
        with st.spinner("Rebuilding…"):
            rag.ingest_dir(config.KNOWLEDGE_DIR, reset=True)
        st.rerun()

outline = rag.outline()
topic_list = rag.topics(limit=8)
docs = status["sources"]

# Apply a pending "open this document" request before the reader selectbox
# exists (a Sources card was clicked). Streamlit can't switch tabs for us, so
# flag it to show an "opened below" hint inside the Documents tab.
_pending_doc = st.session_state.pop("pending_doc", None)
if _pending_doc and _pending_doc in docs:
    st.session_state["doc_reader_sel"] = _pending_doc
    st.session_state["_jumped_to_doc"] = _pending_doc

# Full corpus text, for glossary term-detection (small corpus, cheap to build).
_corpus_text = "\n".join(rag.document_text(s) or "" for s in docs)

# The conversation lives in its own tab; the rest are reference panels, so the
# chat page stays clean instead of sharing a scroll with the About text.
(_tab_chat, _tab_about, _tab_ask, _tab_strength,
 _tab_glossary, _tab_docs) = st.tabs(
    ["💬 Chat", "ℹ️ About", "📋 What can I ask?", "✅ Strengths & limits",
     "📖 Glossary", "📄 Documents"])

with _tab_about:
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

with _tab_ask:
    st.caption("This assistant answers only from the documents below — here's "
               "what each one covers:")
    for d in outline:
        secs = " · ".join(d["sections"]) if d["sections"] else "—"
        st.markdown(f"**{d['title']}**  \n<span style='color:#666'>{secs}</span>",
                    unsafe_allow_html=True)

with _tab_strength:
    st.caption("What this assistant does well, and where it's limited — shown "
               "for its **current setup**, so you always know what you're "
               "getting. Being explicit about limits is deliberate: for model "
               "risk (e.g. OSFI E-23), a documented boundary is a strength, "
               "not a weakness.")

    semantic_on = _eb in ("ollama", "voyage")
    ai_on = has_key and provider in ("auto", "anthropic")

    st.markdown("#### ✅ Where it excels")
    st.markdown(
        "- **Grounded & cited** — every answer is drawn only from your "
        "documents, with clickable sources you can open and verify.\n"
        "- **Won't make things up** — if the documents don't cover a question, "
        "it says so instead of guessing.\n"
        "- **Auditable** — every question, answer, and cited source (with the "
        "document's version) is written to an audit trail.\n"
        "- **Finds the right passage** — keyword ranking (BM25) reliably "
        "surfaces the section that contains your terms.")

    st.markdown("#### ⚠️ Where it needs care (this setup)")

    # Search mode — flips to a green ✓ once semantic search is on.
    if semantic_on:
        st.success(f"**Search: semantic ({_eb}).** Matches by meaning, so "
                   "synonyms like *TDS* vs *DTI* are handled.")
    else:
        st.warning("**Search: keyword only (local).** Matches words, not "
                   "meaning — it can miss synonyms (e.g. *TDS* vs *DTI*) or "
                   "an unfamiliar acronym.  \n*Fix:* run Ollama, or set a "
                   "Voyage API key, for meaning-based search.")

    # Answer mode — reflects the engine actually in effect.
    if ai_on:
        st.success("**Answers: written by Claude.** Polished plain-language "
                   "prose on top of the cited sources.")
    elif provider == "ollama":
        st.info("**Answers: local Ollama** when it's running, otherwise the "
                "quoted passages below.")
    elif provider == "off":
        st.info("**Answers: quoted passages only** (you picked *No AI*). Real, "
                "cited text — occasionally clipped, never invented.")
    else:
        st.warning("**Answers: quoted passages** (no Claude key set). Real "
                   "cited text, but sometimes choppy and not woven together "
                   "across documents.  \n*Fix:* paste a Claude API key in the "
                   "sidebar for written answers.")

    # Always-true boundaries.
    st.markdown(
        "- **Knows only what's loaded** — the documents in the sidebar, and "
        "nothing outside them (no web, no live systems).\n"
        "- **Not legal or credit advice** — it reports what your documents "
        "say; a qualified person still makes the decision.\n"
        "- **Answers are as-of dated** — they reflect the document versions "
        "shown; re-ingest after a policy update to stay current.")

with _tab_glossary:
    st.caption("Plain-language definitions of terms that appear in your "
               "documents — so anyone can follow the answers, whatever their "
               "credit-risk background. Only terms actually used in the loaded "
               "documents are listed.")
    _hits = matched_glossary(_corpus_text)
    if not _hits:
        st.info("No known glossary terms were detected in the current "
                "documents.")
    else:
        for term, defn in _hits:
            st.markdown(
                f"**{term}**  \n<span style='color:#666'>{defn}</span>",
                unsafe_allow_html=True)

with _tab_docs:
    _jumped = st.session_state.pop("_jumped_to_doc", None)
    if _jumped:
        st.success(f"Opened **{_jumped}** below.")
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

# ── 💬 Chat tab — the actual conversation, on its own page ───────
with _tab_chat:
    # Chat history
    for turn_i, turn in enumerate(st.session_state.history):
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])
            ans = turn.get("answer")
            if ans is not None:
                render_sources(ans, key_prefix=str(turn_i))
                label = BACKEND_LABEL.get(ans.backend, "")
                if label:
                    st.caption(label)

    pending = None

    # Empty-state coaching (ChatGPT/Claude style): specific examples + topics.
    if first_visit:
        st.markdown("👋 **Ask a question to get started** — or tap an example:")
        cols = st.columns(2)
        for i, ex in enumerate(EXAMPLE_QUESTIONS):
            if cols[i % 2].button(ex, use_container_width=True, key=f"ex{i}"):
                pending = ex
        if topic_list:
            st.markdown("**…or explore a topic:**")
            pending = topic_chips(topic_list[:6], "topic_") or pending
        st.caption("New here? The **ℹ️ About**, **📋 What can I ask?** and "
                   "**📖 Glossary** tabs above explain what this can do.")

    # Helpful redirect after a "not found" answer — turn dead-ends into guidance.
    elif st.session_state.history:
        last = st.session_state.history[-1]
        last_ans = last.get("answer")
        if last_ans is not None and not last_ans.grounded and topic_list:
            st.markdown("**Not sure what to ask? I can help with topics like:**")
            pending = topic_chips(topic_list[:6], "retry_") or pending

    # Input
    typed = st.chat_input(
        "Ask about a policy, procedure, model, or compliance rule…")
    question = typed or pending

    if question:
        st.session_state.history.append({"role": "user", "content": question})
        with st.spinner("Searching your documents…"):
            ans = rag.query(question)
        if ans.grounded:
            content = ans.text
        else:
            # Friendlier refusal that points back to the corpus scope.
            hint = (" I can only answer from the loaded documents — try the "
                    "**📋 What can I ask?** tab.") if topic_list else ""
            content = f":orange[{ans.text}]{hint}"
        st.session_state.history.append(
            {"role": "assistant", "content": content, "answer": ans})
        st.rerun()
