"""Pass 2 -- targeted re-verification of escalated fields only.

The verification loop, in order:

  1. EVIDENCE CHECK (deterministic, src/evidence.py). Re-download every URL
     pass 1 cited, with plain httpx, and test the quote is on the page.
  2. TRIAGE (src/triggers.py). Seven rules decide which FIELDS are suspect:
     low confidence, off-domain evidence, unverifiable evidence, self-serve
     with unknown gate, every buildable_now (asymmetric cost), contradictions,
     and every "no MCP" claim.
  3. ADJUDICATION (agent). A fresh verifier agent gets only the flagged fields,
     the reasons, and an instruction to re-derive them from primary sources
     and to COUNT endpoints rather than estimate.
  4. ACCEPTANCE GATE (deterministic). A changed value is accepted only if the
     verifier's quote is found on the page it cites -- by httpx, or for
     bot-walled pages by a recorded browser check. Otherwise the pass-1 value
     stands and the field goes to the human queue.
  5. HUMAN QUEUE. Whatever 3-4 cannot settle lands in out/human_queue.json.

    python -m src.pass2_verify triage
    python -m src.pass2_verify emit
    ... verifier agents write out/work/pass2/raw/*.json ...
    python -m src.pass2_verify ingest
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .agent_io import raw_path, read_raw, write_batches
from .config import HUMAN_QUEUE_JSON, OUT, PASS1_JSON, PASS2_JSON, ROOT, TRIAGE_JSON
from .evidence import check_claim, check_records, load_browser_checks, summarise
from .fetch import DirectBackend
from .pass1_discover import _ENUMS, load_apps
from .prompts import AGENT_RULES, PASS2_AGENT_BRIEF
from .schema import GRADED_FIELDS, AppRecord, Confidence, Protocol, get_field
from .triggers import triage_all

EVIDENCE_PASS1 = OUT / "evidence_pass1.json"
PASS2_BUDGET = 8          # web calls per app: verification is allowed to dig
BATCH_SIZE = 5

# verdict.value is derived; a trigger on it means "re-check tier + gate".
EXPAND = {"verdict.value": ("access.tier", "access.extra_gate")}


def _load_pass1() -> tuple[dict, list[AppRecord]]:
    if not PASS1_JSON.exists():
        sys.exit(f"{PASS1_JSON} not found. Run pass 1 first.")
    data = json.loads(PASS1_JSON.read_text(encoding="utf-8"))
    return data, [AppRecord.model_validate(a) for a in data["apps"]]


def _escalations(triage: dict) -> dict[str, dict[str, list[str]]]:
    """{app: {field: [reasons]}}, with the derived verdict expanded."""
    out: dict[str, dict[str, list[str]]] = {}
    for app, trigs in triage["per_app"].items():
        fields: dict[str, list[str]] = defaultdict(list)
        for t in trigs:
            for f in EXPAND.get(t["field"], (t["field"],)):
                if f in GRADED_FIELDS:
                    fields[f].append(f"{t['rule']}: {t['detail']}")
        if fields:
            out[app] = dict(fields)
    return out


# --------------------------------------------------------------------------
# triage
# --------------------------------------------------------------------------

def cmd_triage() -> int:
    data, records = _load_pass1()
    print(f"Evidence check: re-fetching every URL cited in {PASS1_JSON.name} ...")
    evidence = check_records(data["apps"])
    summary = summarise(evidence)
    EVIDENCE_PASS1.write_text(json.dumps({"summary": summary, "apps": evidence}, indent=2),
                              encoding="utf-8")
    print(f"    {summary['by_status']}  verified rate {summary['verified_rate']}")

    triage = triage_all(records, evidence)
    triage["escalations"] = _escalations(triage)
    TRIAGE_JSON.write_text(json.dumps(triage, indent=2), encoding="utf-8")
    n_fields = sum(len(v) for v in triage["escalations"].values())
    total = len(records) * len(GRADED_FIELDS)
    print(f"Triage: {n_fields}/{total} fields escalated ({n_fields/total:.0%}) "
          f"across {len(triage['escalations'])} apps")
    print(f"    by rule: {triage['by_rule']}")
    if not 0.15 <= n_fields / total <= 0.85:
        print("  ! escalation rate outside the useful band - recalibrate triggers",
              file=sys.stderr)
    return 0


# --------------------------------------------------------------------------
# emit
# --------------------------------------------------------------------------

def _app_block(app: dict, rec: AppRecord, fields: dict[str, list[str]]) -> str:
    rel = raw_path("pass2", app).relative_to(ROOT).as_posix()
    lines = [f"### {app['name']} (#{app['id']}, {app['category']})",
             f"website hint: `{app.get('website') or 'none given'}` "
             f"-> write `{rel}`", "", "Pass-1 answer for the flagged fields:"]
    for f in fields:
        blk = getattr(rec, f.split(".")[0])
        lines.append(f"- `{f}` = `{json.dumps(get_field(rec, f))}` "
                     f"(confidence {blk.confidence.value}; cited {blk.evidence_url or 'nothing'})")
        for r in fields[f]:
            lines.append(f"    - flagged because {r}")
    lines.append(f"- (context, not flagged) protocols = {[p.value for p in rec.api.protocols]}, "
                 f"one_liner = {rec.one_liner!r}")
    return "\n".join(lines)


def cmd_emit() -> int:
    if not TRIAGE_JSON.exists():
        sys.exit("Run `python -m src.pass2_verify triage` first.")
    triage = json.loads(TRIAGE_JSON.read_text(encoding="utf-8"))
    _, records = _load_pass1()
    by_name = {r.app: r for r in records}
    apps = [a for a in load_apps() if a["name"] in triage["escalations"]]

    def render(batch_id: int, group: list[dict]) -> str:
        body = "\n\n".join(_app_block(a, by_name[a["name"]], triage["escalations"][a["name"]])
                           for a in group)
        return PASS2_AGENT_BRIEF.format(batch_id=batch_id, budget=PASS2_BUDGET,
                                        rules=AGENT_RULES, apps=body)

    groups = [apps[i:i + BATCH_SIZE] for i in range(0, len(apps), BATCH_SIZE)]
    paths = write_batches("pass2", groups, render)
    print(f"Wrote {len(paths)} pass-2 briefs covering {len(apps)} apps")
    return 0


# --------------------------------------------------------------------------
# ingest
# --------------------------------------------------------------------------

def _coerce_value(field: str, value):
    if field == "auth.methods":
        return value if isinstance(value, list) else [value]
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def cmd_ingest(require_quote: bool = True) -> int:
    data, records = _load_pass1()
    triage = json.loads(TRIAGE_JSON.read_text(encoding="utf-8"))
    escalations = triage["escalations"]
    apps = {a["name"]: a for a in load_apps()}
    backend, browser = DirectBackend(), load_browser_checks()

    changes, rejected, human_queue, confirmed = [], [], [], []
    browser_needed = []
    for rec in records:
        flagged = escalations.get(rec.app)
        if not flagged:
            continue
        payload, err = read_raw(raw_path("pass2", apps[rec.app]))
        if payload is None:
            for f in flagged:
                human_queue.append({"app": rec.app, "field": f, "stage": "adjudication",
                                    "reason": f"verifier produced no result ({err})"})
            continue
        results = payload.get("fields", {})
        for f in flagged:
            r = results.get(f)
            if r is None:
                human_queue.append({"app": rec.app, "field": f, "stage": "adjudication",
                                    "reason": "verifier skipped this flagged field"})
                continue
            old = get_field(rec, f)
            new = _coerce_value(f, r.get("value"))
            if r.get("needs_human"):
                human_queue.append({"app": rec.app, "field": f, "stage": "adjudication",
                                    "reason": r.get("human_reason") or "verifier could not settle it",
                                    "pass1": old, "suggested": new})
                continue
            differs = (set(new or []) != set(old or [])) if f == "auth.methods" else new != old
            if not differs:
                confirmed.append({"app": rec.app, "field": f, "value": old})
                blk = getattr(rec, f.split(".")[0])
                if r.get("confidence") in {c.value for c in Confidence}:
                    blk.confidence = Confidence(r["confidence"])
                continue

            # ---- acceptance gate: the new value's quote must be on the page
            chk = check_claim(r.get("evidence_url"), r.get("evidence_quote"), backend, browser)
            accepted = chk["status"] == "verified" or not require_quote
            entry = {"app": rec.app, "field": f, "old": old, "new": new,
                     "url": r.get("evidence_url"), "quote": r.get("evidence_quote"),
                     "check": chk["status"], "via": chk.get("via"),
                     "reasoning": r.get("reasoning")}
            if not accepted:
                rejected.append(entry)
                if chk["status"] == "needs_browser":
                    browser_needed.append({"url": r.get("evidence_url"),
                                           "quote": r.get("evidence_quote"),
                                           "app": rec.app, "field": f})
                human_queue.append({"app": rec.app, "field": f, "stage": "acceptance_gate",
                                    "reason": f"proposed change {old!r} -> {new!r} not verifiable "
                                              f"({chk['status']})",
                                    "pass1": old, "suggested": new, "url": r.get("evidence_url")})
                continue
            block_name, attr = f.split(".")
            blk = getattr(rec, block_name)
            try:
                # Coerce through the enum: pydantic does not validate on
                # assignment, and str-Enums hash by NAME, so a raw string would
                # silently fail `in {ExtraGate...}` checks in derive_verdict.
                enum_cls = _ENUMS[(block_name, attr)]
                setattr(blk, attr, [enum_cls(v) for v in new] if isinstance(new, list)
                        else enum_cls(new))
            except Exception as exc:  # noqa: BLE001 - off-enum value from the verifier
                rejected.append({**entry, "check": f"invalid value: {exc}"})
                continue
            blk.evidence_url, blk.evidence_quote = r.get("evidence_url"), r.get("evidence_quote")
            if r.get("confidence") in {c.value for c in Confidence}:
                blk.confidence = Confidence(r["confidence"])
            changes.append(entry)

        extra = payload.get("extra") or {}
        if extra.get("protocols"):
            try:
                rec.api.protocols = [Protocol(p) for p in extra["protocols"]]
            except ValueError:
                pass
        if extra.get("one_liner") and not rec.one_liner:
            rec.one_liner = extra["one_liner"]
        rec.provenance.pass_number = 2
        rec.provenance.escalated_fields = list(flagged)
        rec.rederive_verdict()

    # Re-validate every record: a pass-2 change must not create a structurally
    # impossible record (e.g. tier=no_public_api with REST protocols).
    final = []
    for rec in records:
        try:
            final.append(AppRecord.model_validate(rec.model_dump(mode="json")))
        except Exception as exc:  # noqa: BLE001
            if rec.access.tier.value == "no_public_api":
                rec.api.protocols = [p for p in rec.api.protocols
                                     if p in (Protocol.CLI, Protocol.SDK_ONLY)] or [Protocol.NONE]
                rec.rederive_verdict()
            final.append(rec)
            print(f"  ! repaired {rec.app}: {exc}", file=sys.stderr)

    HUMAN_QUEUE_JSON.write_text(json.dumps(human_queue, indent=2, ensure_ascii=False),
                                encoding="utf-8")
    (OUT / "work" / "browser_needed.json").write_text(
        json.dumps(browser_needed, indent=2, ensure_ascii=False), encoding="utf-8")
    PASS2_JSON.write_text(json.dumps({
        "run_id": data.get("run_id"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "derived_from": PASS1_JSON.name,
        "stats": {
            "apps_escalated": len(escalations),
            "fields_escalated": sum(len(v) for v in escalations.values()),
            "confirmed": len(confirmed), "changed": len(changes),
            "rejected_by_gate": len(rejected), "human_queue": len(human_queue),
            "human_queue_by_stage": dict(Counter(h["stage"] for h in human_queue)),
        },
        "changes": changes, "rejected": rejected, "confirmed": confirmed,
        "apps": [r.model_dump(mode="json") for r in final],
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Confirmed {len(confirmed)} | changed {len(changes)} | rejected by gate "
          f"{len(rejected)} ({len(browser_needed)} need a browser check) | human queue "
          f"{len(human_queue)}")
    print(f"Written -> {PASS2_JSON}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Pass 2: targeted verification.")
    ap.add_argument("cmd", choices=["triage", "emit", "ingest"])
    ap.add_argument("--no-gate", action="store_true",
                    help="accept verifier changes without the quote check (ablation only)")
    args = ap.parse_args()
    if args.cmd == "triage":
        return cmd_triage()
    if args.cmd == "emit":
        return cmd_emit()
    return cmd_ingest(require_quote=not args.no_gate)


if __name__ == "__main__":
    raise SystemExit(main())
