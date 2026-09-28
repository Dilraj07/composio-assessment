"""Pass 2 -- targeted re-verification of escalated fields only.

Three mechanisms, in increasing cost:

  1. Re-fetch the cited page and check the claim text is actually on it.
     A 200 response proves the path exists, not that it says what was claimed.
  2. Browser render for pricing/plan pages -- JS-heavy, rarely in docs, and the
     single biggest source of wrong `access.tier` answers.
  3. A second model adjudicating FROM FETCHED TEXT ONLY, no parametric memory.
     Asking the same model twice from memory is not verification.

Anything still unresolved goes to out/human_queue.json. That queue, with a
count, is the answer to the brief's "tell us where it needed a human".

    python -m src.pass2_verify
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from .config import HUMAN_QUEUE_JSON, PASS1_JSON, PASS2_JSON, TRIAGE_JSON, settings
from .fetch import Page, SearchBackend, claim_supported, get_backend
from .prompts import FIELD_ALLOWED_VALUES, PASS2_SYSTEM, PASS2_USER
from .schema import AppRecord, Confidence
from .triggers import triage_all

# Fields whose ground truth lives on pricing pages rather than docs. These are
# JS-rendered often enough that a plain HTTP fetch returns an empty shell, so
# they go to the browser backend when one is configured.
BROWSER_FIELDS = {"access.tier", "access.extra_gate"}


def _set_field(record: AppRecord, dotted: str, value, quote, confidence) -> None:
    block_name, attr = dotted.split(".")
    block = getattr(record, block_name)
    setattr(block, attr, value)
    if quote:
        block.evidence_quote = quote
    block.confidence = Confidence(confidence)


def _render_with_browser(url: str) -> Page | None:
    """Hook for browser-use / Playwright.

    Left as an explicit seam rather than a silent fallback: when it is not
    wired, pricing-page fields honestly fail to verify and land in the human
    queue, which is a truer result than pretending a static fetch settled them.
    """
    return None


def _adjudicate(app: str, field: str, prior, prior_conf: str, reason: str, page: Page) -> dict:
    if settings.fetch_backend == "stub":
        return {
            "value": prior, "evidence_quote": None, "confidence": "low",
            "changed": False, "reasoning": "stub run - no adjudication performed",
            "needs_human": True, "human_reason": "stub backend",
        }

    settings.require_llm()
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.model,
        max_tokens=800,
        system=PASS2_SYSTEM,
        messages=[{"role": "user", "content": PASS2_USER.format(
            app=app, field=field, prior_value=prior, prior_confidence=prior_conf,
            reason=reason, allowed_values=FIELD_ALLOWED_VALUES.get(field, "see schema.py"),
            page_text=page.text[:8000] if page.ok else "(page could not be fetched)",
        )}],
    )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    return json.loads(text)


def verify_field(backend: SearchBackend, record: AppRecord, trig: dict) -> dict:
    """Run one escalated field through the verification ladder."""
    field, reason = trig["field"], trig["rule"]
    block = getattr(record, field.split(".")[0])
    url = block.evidence_url or record.api.docs_root or record.website

    if not url:
        return {"field": field, "resolved": False,
                "needs_human": True, "human_reason": "no URL to verify against"}

    if not url.startswith("http"):
        url = f"https://{url}"

    # Step 1/2 -- fetch, escalating to a renderer for pricing-dependent fields.
    page = None
    if field in BROWSER_FIELDS:
        page = _render_with_browser(url)
    if page is None:
        try:
            page = backend.fetch(url)
        except Exception as exc:  # noqa: BLE001
            return {"field": field, "resolved": False, "needs_human": True,
                    "human_reason": f"fetch error: {exc}"}

    if not page.ok:
        return {"field": field, "resolved": False, "needs_human": True,
                "human_reason": f"page unreachable (status {page.status})"}

    # Step 3 -- adjudicate from the fetched text alone.
    prior = getattr(block, field.split(".")[1])
    prior_value = [p.value for p in prior] if isinstance(prior, list) else getattr(prior, "value", prior)

    result = _adjudicate(record.app, field, prior_value,
                         block.confidence.value, reason, page)

    if result.get("needs_human"):
        return {"field": field, "resolved": False, "needs_human": True,
                "human_reason": result.get("human_reason") or "adjudication inconclusive"}

    # Only accept a new answer if its quote is genuinely on the page.
    if result.get("evidence_quote") and not claim_supported(page, result["evidence_quote"]):
        return {"field": field, "resolved": False, "needs_human": True,
                "human_reason": "adjudicator quote not found on page"}

    return {
        "field": field, "resolved": True, "needs_human": False,
        "old": prior_value, "new": result["value"],
        "changed": result.get("changed", prior_value != result["value"]),
        "confidence": result.get("confidence", "medium"),
        "evidence_quote": result.get("evidence_quote"),
        "url": page.url,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Pass 2: targeted verification.")
    ap.add_argument("--pass1", default=str(PASS1_JSON))
    ap.add_argument("--out", default=str(PASS2_JSON))
    ap.add_argument("--backend")
    args = ap.parse_args()

    from pathlib import Path
    src = Path(args.pass1)
    if not src.exists():
        print(f"{src} not found. Run `make pass1` first.", file=sys.stderr)
        return 1

    data = json.loads(src.read_text())
    records = [AppRecord.model_validate(a) for a in data["apps"]]
    by_app = {r.app: r for r in records}

    triage = triage_all(records)
    Path(TRIAGE_JSON).write_text(json.dumps(triage, indent=2))
    print(f"Triage: {triage['fields_escalated']}/{triage['fields_total']} fields "
          f"({triage['escalation_rate']:.0%}) across {triage['apps_with_triggers']} apps")
    if not 0.15 <= triage["escalation_rate"] <= 0.85:
        print("  ! escalation rate outside the useful band - recalibrate triggers "
              "(see docs/CHECKLIST.md Phase 3)", file=sys.stderr)

    backend = get_backend(args.backend)
    human_queue, changes = [], []

    for app_name, trigs in triage["per_app"].items():
        record = by_app[app_name]
        # One verification per distinct field. A field often trips several
        # rules at once; re-fetching and re-adjudicating it per rule wastes
        # calls and can thrash the value back and forth.
        first_per_field = {}
        for t in trigs:
            first_per_field.setdefault(t["field"], t)

        for trig in first_per_field.values():
            res = verify_field(backend, record, trig)
            if res["needs_human"]:
                human_queue.append({"app": app_name, "field": res["field"],
                                    "reason": res["human_reason"], "trigger": trig["rule"]})
                continue
            if res["changed"]:
                _set_field(record, res["field"], res["new"],
                           res.get("evidence_quote"), res["confidence"])
                changes.append({"app": app_name, "field": res["field"],
                                "old": res["old"], "new": res["new"], "url": res["url"]})
            record.provenance.escalated_fields.append(res["field"])
        record.provenance.pass_number = 2

    Path(HUMAN_QUEUE_JSON).write_text(json.dumps(human_queue, indent=2))
    Path(args.out).write_text(json.dumps({
        "run_id": data.get("run_id"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "derived_from": str(src),
        "changes": changes,
        "human_queue_size": len(human_queue),
        "apps": [r.model_dump(mode="json") for r in records],
    }, indent=2))

    print(f"\nChanged {len(changes)} field values")
    print(f"Human queue: {len(human_queue)} items → {HUMAN_QUEUE_JSON}")
    print(f"Written → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
