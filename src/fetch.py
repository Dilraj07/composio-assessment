"""Search + fetch layer.

One protocol, three backends. Pipeline logic never imports a vendor SDK
directly, so swapping Composio in or out is a one-line env change and touches
nothing in pass1/pass2.

    stub      canned responses, no credentials, full pipeline dry run
    direct    httpx + a search API
    composio  Composio SDK tools (set COMPOSIO_API_KEY)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

import httpx

from .config import settings


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str = ""


@dataclass
class Page:
    url: str
    text: str
    status: int = 200
    ok: bool = True
    error: str | None = None
    rendered: bool = field(
        default=False,
        metadata={"doc": "True if fetched via a JS-capable browser backend."},
    )


@runtime_checkable
class SearchBackend(Protocol):
    def search(self, query: str, *, limit: int = 5) -> list[SearchHit]: ...
    def fetch(self, url: str) -> Page: ...


# --------------------------------------------------------------------------
# Evidence helpers -- the core of what makes pass 2 real verification
# --------------------------------------------------------------------------

def registrable_domain(url: str) -> str:
    """Rough eTLD+1. Good enough to tell docs.stripe.com from a blog post."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    # crude multi-part TLD handling (co.uk, com.au, ...)
    if parts[-2] in {"co", "com", "org", "net", "ac", "gov"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_first_party(url: str | None, app_website: str | None) -> bool:
    """Is the evidence on the vendor's own domain?

    Third-party blogs and aggregators are where hallucinated claims hide: the
    model half-remembers a Medium post, cites it, and the URL resolves fine.
    First-party docs are the standard.
    """
    if not url or not app_website:
        return False
    vendor = registrable_domain(
        app_website if "://" in app_website else f"https://{app_website}"
    )
    return bool(vendor) and registrable_domain(url).endswith(vendor)


def _normalise(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def claim_supported(page: Page, quote: str | None, *, min_overlap: float = 0.6) -> bool:
    """Does the claim text actually appear on the fetched page?

    Confirming a URL returns 200 proves nothing -- a model can invent a docs
    path that happens to exist. This checks the cited words are really there,
    tolerating minor whitespace and truncation differences.
    """
    if not quote or not page.ok:
        return False
    hay, needle = _normalise(page.text), _normalise(quote)
    if not needle:
        return False
    if needle in hay:
        return True
    tokens = [t for t in re.findall(r"[a-z0-9]+", needle) if len(t) > 3]
    if not tokens:
        return False
    hits = sum(1 for t in set(tokens) if t in hay)
    return hits / len(set(tokens)) >= min_overlap


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------

class StubBackend:
    """Deterministic canned responses. No network, no credentials.

    Exists so `make run` works end to end before a single API call is spent --
    you can see the shape of every artifact, and the trigger/grading logic is
    testable without burning budget or rate limits.
    """

    def search(self, query: str, *, limit: int = 5) -> list[SearchHit]:
        return [
            SearchHit(
                title=f"[stub] {query} — API documentation",
                url="https://example.com/docs/api",
                snippet="Stub result. Set FETCH_BACKEND=direct for live search.",
            )
        ][:limit]

    def fetch(self, url: str) -> Page:
        return Page(
            url=url,
            text=(
                "Stub page body. Authentication uses OAuth 2.0 authorization "
                "code flow. A free developer account is available."
            ),
        )


class DirectBackend:
    """Plain httpx + a search API.

    Slot your search provider into `search()`. Fetch is deliberately dumb:
    strip tags, keep text. Docs sites are mostly static; pricing pages are not,
    which is exactly why pass 2 escalates those to a browser.
    """

    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=settings.request_timeout,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        )

    def search(self, query: str, *, limit: int = 5) -> list[SearchHit]:
        raise NotImplementedError(
            "Wire a search provider here (Brave/Serper/Tavily), or use "
            "FETCH_BACKEND=composio."
        )

    def fetch(self, url: str) -> Page:
        try:
            r = self._client.get(url)
        except httpx.HTTPError as exc:
            return Page(url=url, text="", status=0, ok=False, error=str(exc))
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r.text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return Page(url=url, text=text, status=r.status_code, ok=r.is_success)


class ComposioBackend:
    """Composio SDK tools.

    Using Composio's own SDK here is in the spirit of the role -- the brief
    says so directly. Left as a thin adapter so the rest of the pipeline never
    learns which backend it is talking to.
    """

    def __init__(self) -> None:
        if not settings.composio_api_key:
            raise RuntimeError("COMPOSIO_API_KEY unset.")
        # from composio import Composio
        # self._client = Composio(api_key=settings.composio_api_key)
        raise NotImplementedError(
            "Wire the Composio search/fetch tools here once SDK access is "
            "confirmed. Until then FETCH_BACKEND=stub or =direct."
        )

    def search(self, query: str, *, limit: int = 5) -> list[SearchHit]: ...
    def fetch(self, url: str) -> Page: ...


_BACKENDS = {"stub": StubBackend, "direct": DirectBackend, "composio": ComposioBackend}


def get_backend(name: str | None = None) -> SearchBackend:
    key = (name or settings.fetch_backend).lower()
    if key not in _BACKENDS:
        raise ValueError(f"Unknown FETCH_BACKEND={key!r}. Choose: {list(_BACKENDS)}")
    return _BACKENDS[key]()
