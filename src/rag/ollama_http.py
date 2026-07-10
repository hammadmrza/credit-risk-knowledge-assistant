"""
src/rag/ollama_http.py
───────────────────────
Tiny HTTP helper for talking to a local Ollama server from the RAG
pipeline.

Prefers httpx (already a project dependency) but falls back to the
standard-library ``urllib`` so the RAG core has *no* hard third-party
dependency and can run in a bare environment. Every call is wrapped so a
missing/offline Ollama server never raises — callers get ``None`` and
apply their own fallback.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

log = logging.getLogger(__name__)


def post_json(url: str, payload: dict, timeout: float = 60.0) -> Optional[dict]:
    """POST ``payload`` as JSON to ``url``; return parsed JSON or ``None``.

    Never raises on network/HTTP errors — returns ``None`` so the caller
    can fall back. Uses httpx when importable, else stdlib urllib.
    """
    try:
        import httpx  # type: ignore

        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except ImportError:
        pass  # httpx not installed — fall through to urllib
    except Exception as e:  # httpx present but call failed
        log.debug("httpx POST %s failed: %s", url, e)
        return None

    # ── stdlib fallback ──────────────────────────────────────────
    import urllib.error
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.debug("urllib POST %s failed: %s", url, e)
        return None


def get_json(url: str, timeout: float = 5.0) -> Optional[Any]:
    """GET JSON from ``url``; return parsed body or ``None`` on any error."""
    try:
        import httpx  # type: ignore

        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
    except ImportError:
        pass
    except Exception as e:
        log.debug("httpx GET %s failed: %s", url, e)
        return None

    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.debug("urllib GET %s failed: %s", url, e)
        return None
