"""Pass 1 -- broad, cheap discovery across the full app set.

Output is FROZEN to out/pass1.json and never mutated. Pass 2 writes elsewhere.
Without a preserved "before" snapshot, the accuracy-delta story -- the highest
weighted part of the rubric -- cannot be reconstructed after the fact.

    python -m src.pass1_discover --limit 5
    python -m src.pass1_discover --category "CRM & Sales"
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import yaml

from .config import APPS_YAML, PASS1_JSON, settings
from .fetch import SearchBackend, get_backend
from .prompts import PASS1_SYSTEM, PASS1_USER, SEARCH_QUERIES
from .schema import AppRecord, Provenance


def load_apps(category: str | None = None, limit: int | None = None) -> list[dict]:
    doc = yaml.safe_load(APPS_YAML.read_text())
    apps: list[dict] = []
    for cat in doc.get("categories", []):
        if category and cat["name"].lower() != category.lower():
            continue
        for a in cat.get("apps", []):
            apps.append({**a, "category": cat["name"]})
    return apps[:limit] if limit else apps


def _gather(backend: SearchBackend, app: dict) -> tuple[list, dict]:
    """Search, then fetch the top hits. Returns (hits, {url: Page})."""
    hits, pages = [], {}
    for template in SEARCH_QUERIES:
        try:
            hits.extend(backend.search(template.format(app=app["name"]), limit=3))
        except NotImplementedError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad query must not kill the run
            print(f"  ! search failed for {app['name']}: {exc}", file=sys.stderr)

    for h in hits[:6]:
        if h.url in pages:
            continue
        try:
            pages[h.url] = backend.fetch(h.url)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! fetch failed {h.url}: {exc}", file=sys.stderr)
    return hits, pages


def _call_model(system: str, user: str) -> dict:
    """Single structured call. Swap for the Composio/Anthropic client of choice."""
    if settings.fetch_backend == "stub":
        # Deterministic skeleton so the pipeline is runnable with no credentials.
        # Deliberately low-confidence and evidence-free: it should trip nearly
        # every trigger, which is how you sanity-check triage wiring.
        return {
            "one_liner": None,
            "auth": {"methods": ["unknown"], "primary_for_third_party": "unknown",
                     "evidence_url": None, "evidence_quote": None, "confidence": "low"},
            "access": {"tier": "no_public_api", "extra_gate": "unknown",
                       "evidence_url": None, "evidence_quote": None, "confidence": "low"},
            "api": {"protocols": ["none"], "breadth": "unknown", "endpoint_count": None,
                    "mcp": "unknown", "mcp_url": None, "docs_root": None,
                    "evidence_url": None, "evidence_quote": None, "confidence": "low"},
            "verdict": {"value": "not_buildable", "blocker": "no_api",
                        "rationale": "stub run - no research performed",
                        "evidence_url": None, "confidence": "low"},
        }

    settings.require_llm()
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.model,
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    return json.loads(text)


def research_app(backend: SearchBackend, app: dict, run_id: str) -> AppRecord:
    hits, pages = _gather(backend, app)

    payload = _call_model(
        PASS1_SYSTEM,
        PASS1_USER.format(
            app=app["name"],
            category=app["category"],
            website=app.get("website") or "unknown",
            search_results="\n".join(f"- {h.title} :: {h.url}" for h in hits) or "(none)",
            # Truncated per page: enough to ground a claim, not enough to blow
            # the context budget across 6 pages x 90 apps.
            pages="\n\n".join(
                f"### {u}\n{p.text[:4000]}" for u, p in pages.items() if p.ok
            ) or "(none)",
        ),
    )

    record = AppRecord(
        app=app["name"],
        category=app["category"],
        website=app.get("website"),
        one_liner=payload.get("one_liner"),
        **{k: payload[k] for k in ("auth", "access", "api", "verdict") if k in payload},
    )
    record.provenance = Provenance(
        pass_number=1,
        fetched_urls=list(pages),
        run_id=run_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description="Pass 1: broad discovery.")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--category")
    ap.add_argument("--backend", help="override FETCH_BACKEND")
    ap.add_argument("--out", default=str(PASS1_JSON))
    args = ap.parse_args()

    if PASS1_JSON.exists() and args.out == str(PASS1_JSON):
        print(
            f"REFUSING to overwrite {PASS1_JSON}.\n"
            "Pass 1 is the frozen 'before' snapshot for the accuracy story. "
            "Move or delete it deliberately if you really mean to re-run.",
            file=sys.stderr,
        )
        return 1

    backend = get_backend(args.backend)
    apps = load_apps(args.category, args.limit)
    run_id = uuid.uuid4().hex[:8]
    print(f"Pass 1: {len(apps)} apps, backend={args.backend or settings.fetch_backend}, run={run_id}")

    records: list[AppRecord] = []
    with ThreadPoolExecutor(max_workers=settings.max_concurrency) as pool:
        for rec in pool.map(lambda a: research_app(backend, a, run_id), apps):
            records.append(rec)
            print(f"  ✓ {rec.app:<28} {rec.verdict.value.value}")

    out = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backend": args.backend or settings.fetch_backend,
        "apps": [r.model_dump(mode="json") for r in records],
    }
    from pathlib import Path
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\nFrozen → {args.out}  ({len(records)} records)")
    print("Do not modify this file. Pass 2 writes to out/pass2.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
