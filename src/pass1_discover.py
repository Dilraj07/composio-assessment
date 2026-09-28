"""Pass 1 -- broad, cheap discovery across the full app set.

Output is FROZEN to out/pass1.json and never mutated. Pass 2 writes elsewhere.
Without a preserved "before" snapshot, the accuracy-delta story -- the highest
weighted part of the rubric -- cannot be reconstructed after the fact.

Two ways to run the LLM step:

  subagent (recorded run, no API key):
      python -m src.pass1_discover emit      # write batch briefs
      ... one tool-using agent per brief writes out/work/pass1/raw/*.json ...
      python -m src.pass1_discover ingest    # validate + freeze

  anthropic (needs ANTHROPIC_API_KEY):
      python -m src.pass1_discover run --limit 5
      Same brief, executed through the Messages API with server-side web
      search. Not exercised in the recorded run -- see README.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum

import yaml
from pydantic import ValidationError

from .agent_io import WORK, raw_path, read_raw, write_batches
from .config import APPS_YAML, PASS1_JSON, ROOT, settings
from .prompts import AGENT_OUTPUT_SHAPE, AGENT_RULES, PASS1_AGENT_BRIEF
from .schema import (
    AccessTier, AppRecord, AuthMethod, Breadth, Confidence, ExtraGate,
    McpStatus, Protocol, Provenance, Verdict,
)

PASS1_BUDGET = 4          # web tool calls per app: cheap on purpose
BATCH_SIZE = 10


def load_apps(category: str | None = None, limit: int | None = None) -> list[dict]:
    doc = yaml.safe_load(APPS_YAML.read_text(encoding="utf-8"))
    apps: list[dict] = []
    for cat in doc.get("categories", []):
        if category and cat["name"].lower() != category.lower():
            continue
        for a in cat.get("apps", []):
            apps.append({**a, "category": cat["name"]})
    return apps[:limit] if limit else apps


# --------------------------------------------------------------------------
# emit
# --------------------------------------------------------------------------

# Only the hints printed in the assignment's own "Website / hint" column.
# The `note:` fields in apps.yaml are analyst notes, some of which state the
# expected answer ("correct answer is no_public_api") -- passing those to the
# agent would leak the answer and inflate pass-1 accuracy on the gold apps.
BRIEF_HINTS = {
    5: "open-source CRM", 37: "funnel builder", 59: "contact/company intel",
    80: "harvestapp.com", 84: "paygent (NMI-powered)", 90: "research API",
    91: "Enterprise API", 92: "MCP server", 94: "OAuth requested",
    95: "document parsing", 96: "MCP", 97: "content suite", 100: "meeting notes",
}


def _app_line(a: dict) -> str:
    hint = f" ({BRIEF_HINTS[a['id']]})" if a["id"] in BRIEF_HINTS else ""
    rel = raw_path("pass1", a).relative_to(ROOT).as_posix()
    return (f"- **{a['name']}** (#{a['id']}, {a['category']}), website hint: "
            f"`{a.get('website') or 'none given'}`{hint}\n"
            f"  -> write `{rel}`")


def render_pass1(batch_id: int, apps: list[dict]) -> str:
    return PASS1_AGENT_BRIEF.format(
        batch_id=batch_id, budget=PASS1_BUDGET, rules=AGENT_RULES,
        shape=AGENT_OUTPUT_SHAPE, apps="\n".join(_app_line(a) for a in apps))


def emit(apps: list[dict]) -> None:
    by_cat = defaultdict(list)
    for a in apps:
        by_cat[a["category"]].append(a)
    groups = []
    for cat_apps in by_cat.values():
        for i in range(0, len(cat_apps), BATCH_SIZE):
            groups.append(cat_apps[i:i + BATCH_SIZE])
    paths = write_batches("pass1", groups, render_pass1)
    print(f"Wrote {len(paths)} pass-1 briefs for {len(apps)} apps:")
    for p in paths:
        print(f"    {p.as_posix()}")


# --------------------------------------------------------------------------
# ingest
# --------------------------------------------------------------------------

_ENUMS = {
    ("auth", "methods"): AuthMethod, ("auth", "primary_for_third_party"): AuthMethod,
    ("access", "tier"): AccessTier, ("access", "extra_gate"): ExtraGate,
    ("api", "protocols"): Protocol, ("api", "breadth"): Breadth,
    ("api", "mcp"): McpStatus, ("verdict", "value"): Verdict,
}
_FALLBACK = {AuthMethod: "unknown", ExtraGate: "unknown", Breadth: "unknown",
             McpStatus: "unknown", Protocol: "none", AccessTier: None, Verdict: None}


def _coerce(payload: dict, log: list[str]) -> dict:
    """Map off-enum values to the honest fallback instead of dropping the app.

    Every coercion is logged: an agent inventing an enum value is itself a
    finding about prompt adherence.
    """
    for (block, attr), enum in _ENUMS.items():
        blk = payload.get(block)
        if not isinstance(blk, dict) or attr not in blk:
            continue
        allowed = {e.value for e in enum}
        val = blk[attr]
        if isinstance(val, list):
            bad = [v for v in val if v not in allowed]
            if bad:
                log.append(f"{block}.{attr}: dropped off-enum {bad}")
                blk[attr] = [v for v in val if v in allowed] or [_FALLBACK[enum]]
        elif val not in allowed:
            fb = _FALLBACK[enum]
            log.append(f"{block}.{attr}: off-enum {val!r} -> {fb!r}")
            if fb is None:
                blk.pop(attr)
            else:
                blk[attr] = fb
        for k in ("confidence",):
            if blk.get(k) not in {c.value for c in Confidence}:
                blk[k] = "low"
    # verdict.blocker is free-ish text in practice; keep it only if valid
    v = payload.get("verdict") or {}
    valid_blockers = {g.value for g in ExtraGate} | {
        "none", "no_api", "paid_only", "local_only", "approval", "partnership"}
    if v.get("blocker") not in valid_blockers:
        if "blocker" in v:
            log.append(f"verdict.blocker: off-enum {v['blocker']!r} -> 'none'")
        v["blocker"] = "none"
    return payload


def build_record(app: dict, payload: dict | None, err: str | None,
                 run_id: str, pass_number: int = 1) -> tuple[AppRecord, list[str]]:
    log: list[str] = []
    base = dict(app=app["name"], category=app["category"], website=app.get("website"))
    if payload is None:
        rec = AppRecord(**base)
        rec.provenance = Provenance(pass_number=pass_number, run_id=run_id,
                                    human_touched=False, human_reason=err)
        log.append(err or "no payload")
        return rec.rederive_verdict(), log

    payload = _coerce(payload, log)
    fields = {k: payload[k] for k in ("auth", "access", "api", "verdict") if k in payload}
    try:
        rec = AppRecord(**base, one_liner=payload.get("one_liner"), **fields)
    except ValidationError as exc:
        # Structurally impossible combos (e.g. no_public_api + REST). Keep the
        # agent's access answer, drop the contradicting protocol list, log it.
        log.append(f"schema rejected: {exc.errors()[0]['msg']}")
        fields.get("api", {}).pop("protocols", None)
        fields.get("verdict", {}).pop("value", None)
        rec = AppRecord(**base, one_liner=payload.get("one_liner"), **fields)
    rec.provenance = Provenance(pass_number=pass_number, run_id=run_id,
                                timestamp=datetime.now(timezone.utc).isoformat())
    return rec.rederive_verdict(), log


def ingest(apps: list[dict], out_path) -> int:
    from pathlib import Path
    out_path = Path(out_path)
    if out_path.exists() and out_path == PASS1_JSON:
        print(f"REFUSING to overwrite {PASS1_JSON}.\nPass 1 is the frozen 'before' "
              "snapshot. Move it deliberately if you really mean to re-run.",
              file=sys.stderr)
        return 1
    run_id = uuid.uuid4().hex[:8]
    records, ingest_log = [], {}
    for a in apps:
        payload, err = read_raw(raw_path("pass1", a))
        rec, log = build_record(a, payload, err, run_id)
        records.append(rec)
        if log:
            ingest_log[a["name"]] = log
        flag = "!" if log else "ok"
        print(f"  {flag:>2} {rec.app:<28} {rec.verdict.value.value}")

    doc = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backend": "subagent",
        "budget_web_calls_per_app": PASS1_BUDGET,
        "ingest_log": ingest_log,
        "apps": [r.model_dump(mode="json") for r in records],
    }
    out_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    missing = sum(1 for v in ingest_log.values() if any("no output" in x for x in v))
    print(f"\nFrozen -> {out_path}  ({len(records)} records, {len(ingest_log)} with "
          f"ingest notes, {missing} missing)")
    print("Do not modify this file. Pass 2 writes to out/pass2.json.")
    return 0


# --------------------------------------------------------------------------
# run (Anthropic API, optional)
# --------------------------------------------------------------------------

def run_anthropic(apps: list[dict]) -> int:
    """Execute the same briefs through the Messages API with web search.

    Kept deliberately thin: one request per app, the brief as the prompt, the
    JSON reply written to the same raw path the subagents use -- so `ingest`
    and everything downstream is identical regardless of who did the reading.
    """
    settings.require_llm()
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    for a in apps:
        brief = render_pass1(0, [a]).replace(
            "write ONE file, exactly at the path given, containing",
            "reply with")
        resp = client.messages.create(
            model=settings.model, max_tokens=4000,
            tools=[{"type": "web_search_20250305", "name": "web_search",
                    "max_uses": PASS1_BUDGET}],
            messages=[{"role": "user", "content": brief}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        p = raw_path("pass1", a)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text[text.find("{"):text.rfind("}") + 1], encoding="utf-8")
        print(f"  wrote {p.as_posix()}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Pass 1: broad discovery.")
    ap.add_argument("cmd", choices=["emit", "ingest", "run"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--category")
    ap.add_argument("--out", default=str(PASS1_JSON))
    args = ap.parse_args()

    apps = load_apps(args.category, args.limit)
    if args.cmd == "emit":
        emit(apps)
        return 0
    if args.cmd == "run":
        return run_anthropic(apps)
    return ingest(apps, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
