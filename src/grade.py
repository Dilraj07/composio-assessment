"""Grade pass 1 and pass 2 against the hand-built gold set.

Field-level, not row-level: 7 graded fields x 20 gold apps = 140 judgments.
Row accuracy is both brutal and uninformative -- one wrong `breadth` should
not zero out an otherwise perfect row, and a per-field breakdown tells you
WHERE the pipeline is weak, which is the actually useful signal.

    python -m src.grade
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ACCURACY_JSON, DATA, GOLD, OUT, PASS1_JSON, PASS2_JSON
from .schema import GRADED_FIELDS, get_field

# Written down in advance (METHODOLOGY §3) so the result is a test rather than
# a description. Predicted shape: the model reads documentation well and infers
# commercial gating badly.
PRIOR = {
    "auth.methods": (0.875, 0.95),
    "auth.primary_for_third_party": (0.85, 0.95),
    "access.tier": (0.65, 0.85),
    "access.extra_gate": (0.55, 0.85),
    "api.breadth": (0.70, 0.80),
    # Added at schema freeze: MCP availability moves monthly, so parametric
    # memory should be the stalest here of any field.
    "api.mcp": (0.60, 0.85),
    "verdict.value": (0.60, 0.85),
}


def _jaccard(a: list, b: list) -> float:
    sa, sb = set(a or []), set(b or [])
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb) if (sa | sb) else 0.0


def compare(agent, gold, field: str) -> dict:
    """Exact match for scoring; Jaccard reported alongside for multi-label."""
    if field == "auth.methods":
        a, g = agent or [], gold or []
        return {"exact": set(a) == set(g), "jaccard": round(_jaccard(a, g), 3)}
    return {"exact": agent == gold, "jaccard": 1.0 if agent == gold else 0.0}


# Hand classification of each miss (METHODOLOGY §2), keyed "app|field".
# Written AFTER grading, which is exactly why it is a separate, committed,
# reviewable file: every reclassification is visible, none is silent.
MISS_CLASSES = DATA / "gold" / "miss_classes.json"

# verdict.value lives on the access block for confidence purposes (derived).
_CONF_BLOCK = {"verdict.value": "access"}


def _confidence(rec: dict, field: str) -> str | None:
    blk = rec.get(_CONF_BLOCK.get(field, field.split(".")[0])) or {}
    return blk.get("confidence")


def grade_run(records: dict, gold: dict, classes: dict | None = None) -> dict:
    """Score one pass against gold. `records` and `gold` are {app: record}."""
    classes = classes or {}
    per_field = {f: {"n": 0, "hits": 0, "jaccard_sum": 0.0} for f in GRADED_FIELDS}
    per_slot: dict[str, list[int]] = {}
    per_conf: dict[str, list[int]] = {}
    misses = []

    for app, gold_rec in gold.items():
        agent_rec = records.get(app)
        if agent_rec is None:
            misses.append({"app": app, "field": "*", "note": "app missing from run"})
            continue
        for f in GRADED_FIELDS:
            gold_val = get_field(gold_rec, f)
            if gold_val is None:
                continue  # gold left blank -> not scored
            agent_val = get_field(agent_rec, f)
            res = compare(agent_val, gold_val, f)

            per_field[f]["n"] += 1
            per_field[f]["jaccard_sum"] += res["jaccard"]
            conf = _confidence(agent_rec, f) or "low"
            for bucket, key in ((per_slot, gold_rec.get("_slot", "?")), (per_conf, conf)):
                bucket.setdefault(key, [0, 0])
                bucket[key][0] += 1
                bucket[key][1] += int(res["exact"])
            if res["exact"]:
                per_field[f]["hits"] += 1
            else:
                cls = classes.get(f"{app}|{f}", {})
                misses.append({
                    "app": app, "field": f,
                    "agent": agent_val, "gold": gold_val,
                    "agent_confidence": conf,
                    "jaccard": res["jaccard"],
                    # Classified by hand in data/gold/miss_classes.json:
                    # agent_wrong / gold_wrong / both_defensible / stale.
                    "disagreement_class": cls.get("class", "UNCLASSIFIED"),
                    "class_note": cls.get("note"),
                    "gold_uncertain": bool(gold_rec.get("_gold_uncertain")),
                    "gold_evidence": (gold_rec.get(f.split(".")[0], {}) or {}).get("evidence_url"),
                    "agent_evidence": (agent_rec.get(_CONF_BLOCK.get(f, f.split(".")[0]), {})
                                       or {}).get("evidence_url"),
                })

    summary, total_n, total_hits = {}, 0, 0
    for f, s in per_field.items():
        n = s["n"]
        summary[f] = {
            "n": n,
            "accuracy": round(s["hits"] / n, 3) if n else None,
            "mean_jaccard": round(s["jaccard_sum"] / n, 3) if n else None,
        }
        total_n += n
        total_hits += s["hits"]

    def _rate(d):
        return {k: {"n": n, "accuracy": round(h / n, 3)} for k, (n, h) in d.items()}

    return {
        "overall_accuracy": round(total_hits / total_n, 3) if total_n else None,
        "judgments": total_n,
        "hits": total_hits,
        "per_field": summary,
        "per_slot": _rate(per_slot),
        # Calibration: is "high" confidence actually more accurate than "low"?
        "per_confidence": _rate(per_conf),
        "confidently_wrong": sum(1 for m in misses if m.get("agent_confidence") == "high"),
        "misses": misses,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Grade passes against the gold set.")
    ap.add_argument("--pass1", default=str(PASS1_JSON))
    ap.add_argument("--pass2", default=str(PASS2_JSON))
    ap.add_argument("--gold", default=str(GOLD))
    ap.add_argument("--out", default=str(ACCURACY_JSON))
    args = ap.parse_args()

    gold_path = Path(args.gold)
    if not gold_path.exists():
        print(f"{gold_path} not found.\n"
              "Build the gold set BY HAND and commit it BEFORE running the "
              "agent (docs/CHECKLIST.md Phase 2). Grading against a gold set "
              "written after seeing agent output is not a real measurement.",
              file=sys.stderr)
        return 1

    gold_doc = json.loads(gold_path.read_text(encoding="utf-8"))
    # Unfilled template rows carry an empty app name -- excluding them here
    # means a half-filled gold set grades honestly on what it does contain,
    # instead of silently scoring every blank as an agent error.
    gold = {a["app"]: a for a in gold_doc["apps"]
            if not a.get("_template") and a.get("app", "").strip()}
    if not gold:
        print("Gold set contains only unfilled template rows.\n"
              "Fill in at least a few apps by hand first "
              "(docs/CHECKLIST.md Phase 2).", file=sys.stderr)
        return 1

    result = {"gold_apps": len(gold), "graded_fields": list(GRADED_FIELDS)}
    classes = (json.loads(MISS_CLASSES.read_text(encoding="utf-8"))
               if MISS_CLASSES.exists() else {})

    runs = [("pass1", args.pass1), ("pass2", args.pass2)]
    # Ablation: pass 2 with the acceptance gate switched off, if it was run.
    nogate = OUT / "pass2_nogate.json"
    if nogate.exists():
        runs.append(("pass2_nogate", str(nogate)))
    for label, path in runs:
        p = Path(path)
        if not p.exists():
            print(f"  (skipping {label}: {p} not found)")
            continue
        recs = {a["app"]: a for a in json.loads(p.read_text(encoding="utf-8"))["apps"]}
        result[label] = grade_run(recs, gold, classes)

    # The headline the rubric actually asks for: movement, not a single number.
    if "pass1" in result and "pass2" in result:
        deltas = {}
        for f in GRADED_FIELDS:
            a = result["pass1"]["per_field"][f]["accuracy"]
            b = result["pass2"]["per_field"][f]["accuracy"]
            if a is not None and b is not None:
                deltas[f] = round(b - a, 3)
        result["delta"] = {
            "overall": round(
                (result["pass2"]["overall_accuracy"] or 0)
                - (result["pass1"]["overall_accuracy"] or 0), 3),
            "per_field": deltas,
        }
        result["prior_expectation"] = {
            f: {"predicted_pass1": p1, "predicted_pass2": p2,
                "actual_pass1": result["pass1"]["per_field"][f]["accuracy"],
                "actual_pass2": result["pass2"]["per_field"][f]["accuracy"]}
            for f, (p1, p2) in PRIOR.items()
        }

    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False),
                              encoding="utf-8")

    print(f"\nGold apps: {len(gold)}   Graded fields: {len(GRADED_FIELDS)}")
    for label in ("pass1", "pass2"):
        if label in result:
            r = result[label]
            acc = r["overall_accuracy"]
            if acc is None:
                print(f"\n{label}: no scoreable judgments "
                      "(gold fields are all null, or apps did not match by name)")
                continue
            print(f"\n{label}: {acc:.1%} over {r['judgments']} judgments")
            for f, s in r["per_field"].items():
                if s["accuracy"] is not None:
                    print(f"    {f:<34} {s['accuracy']:.1%}  (n={s['n']})")
    if "delta" in result:
        print(f"\nOverall movement: {result['delta']['overall']:+.1%}")
    print(f"\nWritten → {args.out}")
    print("Now classify each miss in `misses[]` "
          "(agent_wrong / gold_wrong / both_defensible / stale).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
