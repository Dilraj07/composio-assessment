"""Independent evidence check -- the deterministic half of verification.

For every evidence URL a record cites, re-download it with plain httpx (NOT
the agent's own fetch tool) and test whether the quoted text is really on the
page. This is the check the model cannot talk its way past: it either finds
the words or it does not.

Outcomes per cited block:

    verified        URL fetched, quote found on the page
    quote_missing   URL fetched, quote NOT on the page (paraphrase or invention)
    no_quote        URL fetched, but the record gave no quote to check
    needs_browser   403/429/JS shell -- a plain fetch cannot see the page;
                    escalated to a real browser check (out/work/browser_checks.json)
    dead            404 / DNS / connection error
    no_url          record cites nothing

    python -m src.evidence --input out/pass1.json --out out/evidence_pass1.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import OUT, settings
from .fetch import DirectBackend, Page, claim_supported

CACHE = OUT / "cache"
BROWSER_CHECKS = OUT / "work" / "browser_checks.json"
BLOCKS = ("auth", "access", "api")

# A page this short after tag-stripping is almost always a JS shell or a bot
# wall, not documentation.
MIN_REAL_TEXT = 400


def _cache_path(url: str) -> Path:
    return CACHE / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".json")


def fetch_cached(url: str, backend: DirectBackend | None = None) -> Page:
    CACHE.mkdir(parents=True, exist_ok=True)
    cp = _cache_path(url)
    if cp.exists():
        d = json.loads(cp.read_text(encoding="utf-8"))
        return Page(**d)
    page = (backend or DirectBackend()).fetch(url)
    cp.write_text(json.dumps(page.__dict__), encoding="utf-8")
    return page


def load_browser_checks() -> dict[tuple[str, str], bool]:
    """Manual browser verifications: {(url, quote): found}."""
    if not BROWSER_CHECKS.exists():
        return {}
    rows = json.loads(BROWSER_CHECKS.read_text(encoding="utf-8"))
    return {(r["url"], r["quote"]): bool(r["found"]) for r in rows}


def check_claim(url: str | None, quote: str | None,
                backend: DirectBackend | None = None,
                browser: dict | None = None) -> dict:
    """Classify one (url, quote) claim. See module docstring for outcomes."""
    if not url:
        return {"status": "no_url"}
    page = fetch_cached(url, backend)
    blocked = page.status in (401, 403, 429, 503) or (
        page.ok and len(page.text) < MIN_REAL_TEXT)
    if blocked:
        if browser and quote and (url, quote) in browser:
            found = browser[(url, quote)]
            return {"status": "verified" if found else "quote_missing",
                    "http": page.status, "via": "browser"}
        return {"status": "needs_browser", "http": page.status}
    if not page.ok:
        return {"status": "dead", "http": page.status, "error": page.error}
    if not quote:
        return {"status": "no_quote", "http": page.status}
    ok = claim_supported(page, quote)
    return {"status": "verified" if ok else "quote_missing", "http": page.status,
            "via": "httpx"}


def check_records(apps: list[dict]) -> dict:
    """{app: {block: result}} for every cited block of every record."""
    backend = DirectBackend()
    browser = load_browser_checks()
    jobs = []
    for a in apps:
        for b in BLOCKS:
            blk = a.get(b) or {}
            jobs.append((a["app"], b, blk.get("evidence_url"), blk.get("evidence_quote")))

    def run(job):
        app, b, url, quote = job
        try:
            res = check_claim(url, quote, backend, browser)
        except Exception as exc:  # noqa: BLE001 - one bad URL must not kill the run
            res = {"status": "dead", "error": str(exc)}
        return app, b, {"url": url, "quote": quote, **res}

    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=settings.max_concurrency) as pool:
        for app, b, res in pool.map(run, jobs):
            out.setdefault(app, {})[b] = res
    return out


def summarise(result: dict) -> dict:
    counts: dict[str, int] = {}
    for blocks in result.values():
        for r in blocks.values():
            counts[r["status"]] = counts.get(r["status"], 0) + 1
    cited = sum(v for k, v in counts.items() if k != "no_url")
    return {"by_status": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
            "cited_claims": cited,
            "verified_rate": round(counts.get("verified", 0) / cited, 3) if cited else None}


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-fetch cited URLs and check quotes.")
    ap.add_argument("--input", default=str(OUT / "pass1.json"))
    ap.add_argument("--out", default=str(OUT / "evidence_pass1.json"))
    args = ap.parse_args()
    apps = json.loads(Path(args.input).read_text(encoding="utf-8"))["apps"]
    result = check_records(apps)
    summary = summarise(result)
    Path(args.out).write_text(json.dumps({"summary": summary, "apps": result}, indent=2),
                              encoding="utf-8")
    print(f"Evidence check over {len(apps)} records -> {args.out}")
    for k, v in summary["by_status"].items():
        print(f"    {k:<14} {v}")
    print(f"    verified rate  {summary['verified_rate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
