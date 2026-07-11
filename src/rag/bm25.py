"""
src/rag/bm25.py
────────────────
BM25 keyword ranking — the industry-standard lexical retrieval algorithm
(the core of Elasticsearch/Lucene), in dependency-free Python.

It replaces the earlier hashing-cosine "local" retrieval, which was too
weak: it ranked terms by a crude signed-hash overlap and missed passages
that plainly contained the query words. BM25 scores a passage by how many
query terms it contains, weighted by how *rare* each term is across the
corpus (IDF) and damped for term repetition and passage length — so
"what capital does Basel III require" actually surfaces the Basel III
capital passages.

This runs everywhere (no model, no GPU, no API), so the offline/local
experience — including a hosted demo without Ollama — is genuinely usable.
For meaning-based matching of synonyms, use the Ollama or Voyage semantic
backends instead.
"""

from __future__ import annotations

import math
import re
from typing import List

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Common English words carry no topical signal. Dropping them means a query
# made only of stopwords + unknown terms (e.g. "airspeed velocity of a
# swallow") matches nothing and is honestly refused, instead of scraping a
# match on "of"/"the".
_STOP = frozenset("""
a an the this that these those of to in on for and or but with as at by from
is are was were be been being do does did has have had will would should could
can may might must i me my we our you your it its he she they them their what
which who whom how when where why whether tell about explain describe give show
list into over under out up down more most some any all each per not no yes
please me us
""".split())


def tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def content_tokens(text: str) -> List[str]:
    """Tokens minus stopwords — the topical terms BM25 scores on."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP]


# Everyday words users type vs. the formal words policy documents use. A person
# asks for the DTI "cap"; the policy says "Maximum Debt-to-Income". Keyword
# search can't bridge that on its own, so at query time we ADD the formal
# synonym as an extra search term (never removing the user's own words). This is
# a small, general set for threshold/product wording — ordinary queries with
# none of these words are completely unaffected. It is not a substitute for the
# semantic backends, which handle synonyms in general (e.g. TDS vs DTI).
_SYNONYMS = {
    "cap": "maximum", "caps": "maximum", "ceiling": "maximum",
    "limit": "maximum", "limits": "maximum", "max": "maximum",
    "floor": "minimum", "min": "minimum", "minimums": "minimum",
    "unsecured": "personal",
}


def expand_query(query: str) -> str:
    """Append formal synonyms for any everyday threshold/product words present."""
    extra = [_SYNONYMS[t] for t in content_tokens(query) if t in _SYNONYMS]
    return (query + " " + " ".join(extra)) if extra else query


class BM25:
    """Okapi BM25 over a fixed set of documents (passages)."""

    def __init__(self, docs: List[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_tokens = [content_tokens(d) for d in docs]
        self.doc_len = [len(t) for t in self.doc_tokens]
        self.n = len(docs)
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0

        # Per-document term frequencies + document frequency per term.
        self.tf: List[dict] = []
        df: dict = {}
        for toks in self.doc_tokens:
            freq: dict = {}
            for t in toks:
                freq[t] = freq.get(t, 0) + 1
            self.tf.append(freq)
            for t in freq:
                df[t] = df.get(t, 0) + 1

        # BM25 IDF (with +1 so common terms never go negative).
        self.idf = {
            t: math.log(1 + (self.n - d + 0.5) / (d + 0.5))
            for t, d in df.items()
        }

    def scores(self, query: str) -> List[float]:
        """BM25 score for every document against ``query`` (aligned by index)."""
        q_terms = [t for t in content_tokens(query) if t in self.idf]
        out = [0.0] * self.n
        if not q_terms or self.avgdl == 0:
            return out
        for i in range(self.n):
            freq = self.tf[i]
            dl = self.doc_len[i]
            denom_len = self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            s = 0.0
            for t in q_terms:
                tf = freq.get(t, 0)
                if tf:
                    s += self.idf[t] * (tf * (self.k1 + 1)) / (tf + denom_len)
            out[i] = s
        return out
