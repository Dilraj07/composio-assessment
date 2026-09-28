"""Pattern extraction -- the headline of the deliverable.

The brief is explicit: "Do not just produce 100 rows... Insight over raw
table." Every pattern here is a COUNT derived from enum values, never an
assertion. That is the whole reason the schema is enum-constrained: patterns
fall out of the data instead of being claimed on top of it.

    python -m src.patterns
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .config import PASS2_JSON


def _pct(n: int, total: int) -> float:
    return round(100 * n / total, 1) if total else 0.0


def auth_distribution(apps: list[dict]) -> dict:
    """Which auth dominates -- overall and by category."""
    overall = Counter()
    by_cat = defaultdict(Counter)
    for a in apps:
        primary = a["auth"]["primary_for_third_party"]
        overall[primary] += 1
        by_cat[a["category"]][primary] += 1
    total = len(apps)
    return {
        "overall": [{"method": m, "n": n, "pct": _pct(n, total)}
                    for m, n in overall.most_common()],
        "by_category": {c: dict(v.most_common()) for c, v in by_cat.items()},
    }


def gate_analysis(apps: list[dict]) -> dict:
    """The load-bearing cross-tab: tier x extra_gate.

    Tests the central thesis -- that the real blocker is usually NOT auth and
    NOT credential acquisition, but an approval step that sits after you
    already have credentials. `self_serve_blocked` is the count of apps where
    a developer can get a credential in seconds and still cannot make a
    production call.
    """
    cross = defaultdict(Counter)
    self_serve_blocked = []
    for a in apps:
        tier, gate = a["access"]["tier"], a["access"]["extra_gate"]
        cross[tier][gate] += 1
        if tier.startswith("self_serve") and gate not in ("none", "unknown"):
            self_serve_blocked.append({"app": a["app"], "gate": gate,
                                       "category": a["category"]})
    return {
        "cross_tab": {t: dict(g) for t, g in cross.items()},
        "self_serve_but_gated": self_serve_blocked,
        "self_serve_but_gated_count": len(self_serve_blocked),
        "thesis": (
            f"{len(self_serve_blocked)} apps hand out credentials freely and "
            "still block production access behind a separate approval. The "
            "blocker is post-credential, not auth."
        ),
    }


def blocker_ranking(apps: list[dict]) -> list[dict]:
    """Most common blocker, counted."""
    c = Counter(a["verdict"]["blocker"] for a in apps
                if a["verdict"]["blocker"] not in ("none", None))
    total = len(apps)
    return [{"blocker": b, "n": n, "pct": _pct(n, total)} for b, n in c.most_common()]


def mcp_coverage(apps: list[dict]) -> dict:
    """Is existing MCP coverage concentrated in dev-tools?

    If so, the easy wins for a NEW toolkit are precisely where coverage is
    thin -- which inverts the naive reading of the buildability column.
    """
    by_cat = defaultdict(Counter)
    for a in apps:
        by_cat[a["category"]][a["api"]["mcp"]] += 1
    rows = []
    for cat, counts in by_cat.items():
        n = sum(counts.values())
        covered = counts["official"] + counts["community"]
        rows.append({"category": cat, "apps": n, "with_mcp": covered,
                     "pct": _pct(covered, n)})
    return {"by_category": sorted(rows, key=lambda r: -r["pct"])}


def opportunity_split(apps: list[dict]) -> dict:
    """Easy wins vs needs-outreach -- named, not just counted."""
    buckets = defaultdict(list)
    for a in apps:
        buckets[a["verdict"]["value"]].append(a["app"])

    easy = buckets.get("buildable_now", [])
    no_mcp_yet = [a["app"] for a in apps
                  if a["verdict"]["value"] == "buildable_now"
                  and a["api"]["mcp"] in ("none", "unknown")]
    return {
        "counts": {k: len(v) for k, v in buckets.items()},
        "easy_wins": sorted(easy),
        # The sharpest actionable list: buildable today AND nobody has built
        # an MCP server for it yet.
        "highest_value_gaps": sorted(no_mcp_yet),
        "needs_outreach": sorted(buckets.get("needs_outreach", [])),
        "dead_ends": sorted(buckets.get("not_buildable", [])),
    }


def category_difficulty(apps: list[dict]) -> list[dict]:
    """Which categories are self-serve vs gated, ranked."""
    by_cat = defaultdict(lambda: {"n": 0, "buildable": 0, "gated": 0})
    for a in apps:
        c = by_cat[a["category"]]
        c["n"] += 1
        if a["verdict"]["value"] in ("buildable_now", "buildable_paid"):
            c["buildable"] += 1
        if a["verdict"]["value"] == "needs_outreach":
            c["gated"] += 1
    rows = [{"category": k, **v, "buildable_pct": _pct(v["buildable"], v["n"])}
            for k, v in by_cat.items()]
    return sorted(rows, key=lambda r: -r["buildable_pct"])


def extract(apps: list[dict]) -> dict:
    return {
        "n_apps": len(apps),
        "auth": auth_distribution(apps),
        "gates": gate_analysis(apps),
        "blockers": blocker_ranking(apps),
        "mcp": mcp_coverage(apps),
        "opportunity": opportunity_split(apps),
        "category_difficulty": category_difficulty(apps),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract patterns from a graded run.")
    ap.add_argument("--input", default=str(PASS2_JSON))
    ap.add_argument("--out", default="out/patterns.json")
    args = ap.parse_args()

    apps = json.loads(Path(args.input).read_text())["apps"]
    result = extract(apps)
    Path(args.out).write_text(json.dumps(result, indent=2))

    print(f"Patterns over {result['n_apps']} apps\n")
    print("Auth (primary for third-party):")
    for r in result["auth"]["overall"][:5]:
        print(f"    {r['method']:<18} {r['n']:>3}  ({r['pct']}%)")
    print(f"\n{result['gates']['thesis']}")
    print("\nTop blockers:")
    for r in result["blockers"][:5]:
        print(f"    {r['blocker']:<22} {r['n']:>3}  ({r['pct']}%)")
    print(f"\nEasy wins: {len(result['opportunity']['easy_wins'])}")
    print(f"Buildable today with no MCP yet: "
          f"{len(result['opportunity']['highest_value_gaps'])}")
    print(f"\nWritten → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
