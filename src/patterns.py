"""Pattern extraction -- the headline of the deliverable.

The brief is explicit: "Do not just produce 100 rows... Insight over raw
table." Every pattern here is a COUNT over enum values, and every count
carries the list of apps behind it, so any headline on the page can be
clicked back to rows. Nothing in this file is an assertion.

    python -m src.patterns --input out/pass2.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .config import OUT, PASS2_JSON

OUTREACH_GATES = {"app_review", "developer_token", "partner_program", "sales_contact"}
VERDICT_ORDER = ["buildable_now", "buildable_paid", "needs_outreach",
                 "buildable_local", "not_buildable"]


def _pct(n: int, total: int) -> float:
    return round(100 * n / total, 1) if total else 0.0


def blocker_of(a: dict) -> str:
    """The single thing standing between a builder and a shipped toolkit.

    Derived from the same two fields as the verdict so the two can never
    disagree. Order matters: the most specific gate wins.
    """
    tier, gate = a["access"]["tier"], a["access"]["extra_gate"]
    if tier == "no_public_api":
        return "no hosted API"
    if gate in OUTREACH_GATES:
        return {"sales_contact": "sales contract", "app_review": "platform app review",
                "developer_token": "developer-token approval",
                "partner_program": "partner program"}[gate]
    if tier == "partner_gated":
        return "partnership / application"
    if tier == "approval_required":
        return "production approval"
    if tier == "paid_plan_required":
        return "paid plan (self-serve)"
    return "none"


def auth_patterns(apps: list[dict]) -> dict:
    n = len(apps)
    primary = Counter(a["auth"]["primary_for_third_party"] for a in apps)
    offers = Counter(m for a in apps for m in set(a["auth"]["methods"]))
    both = [a["app"] for a in apps
            if {"oauth2", "api_key"} <= set(a["auth"]["methods"])]
    by_cat = defaultdict(Counter)
    for a in apps:
        by_cat[a["category"]][a["auth"]["primary_for_third_party"]] += 1
    key_only = sorted(a["app"] for a in apps
                      if "oauth2" not in a["auth"]["methods"]
                      and a["access"]["tier"] != "no_public_api")
    return {
        "primary": [{"method": m, "n": c, "pct": _pct(c, n)} for m, c in primary.most_common()],
        "offers": [{"method": m, "n": c, "pct": _pct(c, n)} for m, c in offers.most_common()],
        "oauth_and_key": sorted(both),
        "no_oauth": key_only,
        "by_category": {c: dict(v.most_common()) for c, v in by_cat.items()},
    }


def gate_patterns(apps: list[dict]) -> dict:
    """The load-bearing cross-tab: tier x extra_gate.

    `free_but_gated` = a developer gets a credential for free in minutes and
    STILL cannot act on other people's accounts. If this list is long, the
    real blocker is post-credential, not auth.
    """
    cross = defaultdict(Counter)
    free_but_gated = []
    for a in apps:
        tier, gate = a["access"]["tier"], a["access"]["extra_gate"]
        cross[tier][gate] += 1
        if tier.startswith("self_serve") and gate in OUTREACH_GATES:
            free_but_gated.append({"app": a["app"], "gate": gate, "category": a["category"]})
    return {"cross_tab": {t: dict(g) for t, g in cross.items()},
            "free_but_gated": free_but_gated}


def blocker_ranking(apps: list[dict]) -> list[dict]:
    rows = defaultdict(list)
    for a in apps:
        b = blocker_of(a)
        if b != "none":
            rows[b].append(a["app"])
    return sorted(({"blocker": b, "n": len(v), "pct": _pct(len(v), len(apps)),
                    "apps": sorted(v)} for b, v in rows.items()), key=lambda r: -r["n"])


def category_matrix(apps: list[dict]) -> list[dict]:
    """Verdict mix per category -- which categories are self-serve vs gated."""
    by_cat = defaultdict(Counter)
    for a in apps:
        by_cat[a["category"]][a["verdict"]["value"]] += 1
    rows = []
    for cat, c in by_cat.items():
        n = sum(c.values())
        rows.append({"category": cat, "n": n, **{v: c.get(v, 0) for v in VERDICT_ORDER},
                     "self_serve_pct": _pct(c.get("buildable_now", 0) + c.get("buildable_paid", 0), n)})
    return sorted(rows, key=lambda r: -r["self_serve_pct"])


def mcp_patterns(apps: list[dict]) -> dict:
    by_cat = defaultdict(Counter)
    for a in apps:
        by_cat[a["category"]][a["api"]["mcp"]] += 1
    cov = []
    for cat, c in by_cat.items():
        n = sum(c.values())
        cov.append({"category": cat, "n": n, "official": c["official"],
                    "community": c["community"], "none": c["none"] + c["unknown"],
                    "official_pct": _pct(c["official"], n)})
    total = Counter(a["api"]["mcp"] for a in apps)
    # Official MCP exists, yet the API itself needs outreach: the vendor has
    # already chosen an agent surface, which is a partnership opening.
    mcp_but_gated = sorted(a["app"] for a in apps
                           if a["api"]["mcp"] == "official"
                           and a["verdict"]["value"] == "needs_outreach")
    return {"totals": dict(total), "by_category": sorted(cov, key=lambda r: -r["official_pct"]),
            "official_but_api_gated": mcp_but_gated}


def opportunity(apps: list[dict]) -> dict:
    """Easy wins vs outreach, named.

    Easy win = buildable_now AND OAuth available (multi-tenant ready: one
    toolkit serves every customer without collecting their keys).
    """
    by_v = defaultdict(list)
    for a in apps:
        by_v[a["verdict"]["value"]].append(a)
    now = by_v["buildable_now"]
    easy = sorted(a["app"] for a in now if "oauth2" in a["auth"]["methods"])
    key_only_now = sorted(a["app"] for a in now if "oauth2" not in a["auth"]["methods"])
    no_mcp_now = sorted(a["app"] for a in now if a["api"]["mcp"] in ("none", "unknown"))
    outreach = defaultdict(list)
    for a in by_v["needs_outreach"]:
        outreach[blocker_of(a)].append(a["app"])
    return {
        "counts": {v: len(by_v.get(v, [])) for v in VERDICT_ORDER},
        "easy_wins_oauth": easy,
        "buildable_key_only": key_only_now,
        "buildable_no_official_mcp": no_mcp_now,
        "outreach_by_blocker": {k: sorted(v) for k, v in
                                sorted(outreach.items(), key=lambda kv: -len(kv[1]))},
        "paid": sorted(a["app"] for a in by_v["buildable_paid"]),
        "local_skills": sorted(a["app"] for a in by_v["buildable_local"]),
        "dead_ends": sorted(a["app"] for a in by_v["not_buildable"]),
    }


def breadth_patterns(apps: list[dict]) -> dict:
    return dict(Counter(a["api"]["breadth"] for a in apps))


def extract(apps: list[dict]) -> dict:
    return {
        "n_apps": len(apps),
        "auth": auth_patterns(apps),
        "gates": gate_patterns(apps),
        "blockers": blocker_ranking(apps),
        "categories": category_matrix(apps),
        "mcp": mcp_patterns(apps),
        "opportunity": opportunity(apps),
        "breadth": breadth_patterns(apps),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract patterns from a run.")
    ap.add_argument("--input", default=str(PASS2_JSON))
    ap.add_argument("--out", default=str(OUT / "patterns.json"))
    args = ap.parse_args()

    apps = json.loads(Path(args.input).read_text(encoding="utf-8"))["apps"]
    r = extract(apps)
    Path(args.out).write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Patterns over {r['n_apps']} apps  ({args.input})\n")
    print("Verdicts:", r["opportunity"]["counts"])
    print("Primary auth:", [(x["method"], x["n"]) for x in r["auth"]["primary"]])
    print("Offer OAuth at all:", next((x["n"] for x in r["auth"]["offers"]
                                       if x["method"] == "oauth2"), 0))
    print(f"Free credential but gated production: {len(r['gates']['free_but_gated'])}")
    print("Blockers:", [(b["blocker"], b["n"]) for b in r["blockers"]])
    print("MCP:", r["mcp"]["totals"])
    print(f"\nWritten -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
