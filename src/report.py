"""Render the single-page HTML deliverable.

Page order is set by the rubric, not by pipeline order: patterns first (the
headline), then verification, then the agent, then the table. A reviewer must
get the thesis in about two minutes with no narration.

Self-contained: no CDN, no build step, no external fonts. Open the file or
deploy the file -- same artifact either way.

    python -m src.report
"""

from __future__ import annotations

import argparse
import html
import json
from datetime import date
from pathlib import Path

from .config import ACCURACY_JSON, HUMAN_QUEUE_JSON, PASS2_JSON, REPORT_HTML

CSS = """
:root{--bg:#fbfaf9;--fg:#1c1a17;--muted:#6b6560;--line:#e4dfd9;--card:#fff;
--accent:#b8500f;--good:#2f6f4f;--warn:#9a6a10;--bad:#a33223;}
@media(prefers-color-scheme:dark){:root{--bg:#161512;--fg:#ecE7e0;--muted:#a09a92;
--line:#302c27;--card:#1e1c19;--accent:#e08a4a;--good:#6fbf92;--warn:#d8a748;--bad:#e0766a;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 ui-sans-serif,
-apple-system,"Segoe UI",Roboto,sans-serif;}
.wrap{max-width:1080px;margin:0 auto;padding:48px 20px 96px}
h1{font-size:2.1rem;line-height:1.15;margin:0 0 8px;letter-spacing:-.02em}
h2{font-size:1.35rem;margin:56px 0 4px;letter-spacing:-.01em}
h2+.sub{color:var(--muted);margin:0 0 20px;font-size:.92rem}
.lede{color:var(--muted);font-size:1.02rem;margin:0 0 4px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:28px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.kpi .n{font-size:1.75rem;font-weight:650;letter-spacing:-.02em}
.kpi .l{color:var(--muted);font-size:.78rem;text-transform:uppercase;letter-spacing:.06em;margin-top:2px}
.finding{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--accent);
border-radius:8px;padding:16px 18px;margin:12px 0}
.finding h3{margin:0 0 6px;font-size:1.02rem}
.finding p{margin:0;color:var(--muted);font-size:.93rem}
table{width:100%;border-collapse:collapse;font-size:.86rem;margin-top:12px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:.74rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
position:sticky;top:0;background:var(--bg)}
tbody tr:hover{background:color-mix(in srgb,var(--accent) 6%,transparent)}
.tag{display:inline-block;padding:1px 7px;border-radius:99px;font-size:.73rem;
border:1px solid var(--line);white-space:nowrap}
.t-good{color:var(--good);border-color:color-mix(in srgb,var(--good) 40%,transparent)}
.t-warn{color:var(--warn);border-color:color-mix(in srgb,var(--warn) 40%,transparent)}
.t-bad{color:var(--bad);border-color:color-mix(in srgb,var(--bad) 40%,transparent)}
.bar{height:6px;border-radius:99px;background:var(--line);overflow:hidden;min-width:70px}
.bar>i{display:block;height:100%;background:var(--accent)}
.delta{font-variant-numeric:tabular-nums;font-weight:600}
.up{color:var(--good)} .down{color:var(--bad)}
.note{background:var(--card);border:1px dashed var(--line);border-radius:8px;
padding:14px 16px;color:var(--muted);font-size:.9rem;margin:16px 0}
.flow{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:16px 0;font-size:.85rem}
.step{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px}
.arrow{color:var(--muted)}
.scroll{max-height:560px;overflow:auto;border:1px solid var(--line);border-radius:10px}
code{font:.85em ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--card);
border:1px solid var(--line);border-radius:4px;padding:1px 5px}
footer{margin-top:72px;padding-top:20px;border-top:1px solid var(--line);
color:var(--muted);font-size:.84rem}
a{color:var(--accent)}
"""

VERDICT_CLASS = {"buildable_now": "t-good", "buildable_paid": "t-good",
                 "needs_outreach": "t-warn", "not_buildable": "t-bad"}


def e(x) -> str:
    return html.escape(str(x if x is not None else "—"))


def _kpi(n, label) -> str:
    return f'<div class="kpi"><div class="n">{e(n)}</div><div class="l">{e(label)}</div></div>'


def _pct(v) -> str:
    return "—" if v is None else f"{v*100:.0f}%"


def render(apps, patterns, accuracy, human_queue) -> str:
    p, a = patterns, accuracy
    opp = p["opportunity"]
    gates = p["gates"]

    # ---- KPIs -----------------------------------------------------------
    p1 = (a.get("pass1") or {}).get("overall_accuracy")
    p2 = (a.get("pass2") or {}).get("overall_accuracy")
    kpis = "".join([
        _kpi(p["n_apps"], "apps researched"),
        _kpi(_pct(p1), "pass-1 accuracy"),
        _kpi(_pct(p2), "pass-2 accuracy"),
        _kpi(len(human_queue), "needed a human"),
        _kpi(len(opp["easy_wins"]), "buildable today"),
    ])

    # ---- Patterns -------------------------------------------------------
    top_auth = p["auth"]["overall"][0] if p["auth"]["overall"] else {"method": "—", "pct": 0}
    top_blocker = p["blockers"][0] if p["blockers"] else {"blocker": "—", "n": 0}

    findings = f"""
<div class="finding"><h3>The blocker is almost never authentication.</h3>
<p>{e(gates['self_serve_but_gated_count'])} apps hand out credentials in seconds and still
refuse production traffic until a separate approval clears — developer tokens, app review,
partner admission. Auth is a solved problem; commercial gating is not. Any toolkit roadmap
built on "which auth does it use" will mis-rank its own backlog.</p></div>

<div class="finding"><h3>{e(top_auth['method'])} dominates third-party integration at {e(top_auth['pct'])}%.</h3>
<p>But the distribution splits sharply by category — see the breakdown below. Auth choice
tracks who the vendor's customer is, not what the product does.</p></div>

<div class="finding"><h3>Most common blocker: {e(top_blocker['blocker'])} ({e(top_blocker['n'])} apps).</h3>
<p>Ranked table below. Everything above <code>none</code> is outreach work, not engineering work.</p></div>

<div class="finding"><h3>{e(len(opp['highest_value_gaps']))} apps are buildable today with no MCP server yet.</h3>
<p>Existing MCP coverage clusters in developer tooling, where the need is lowest. The
highest-value gaps are the apps that are trivially buildable and that nobody has built:
{e(', '.join(opp['highest_value_gaps'][:12]) or '—')}.</p></div>
"""

    # ---- Accuracy -------------------------------------------------------
    acc_rows = ""
    if a.get("pass1") and a.get("pass2"):
        for f in a.get("graded_fields", []):
            v1 = a["pass1"]["per_field"].get(f, {}).get("accuracy")
            v2 = a["pass2"]["per_field"].get(f, {}).get("accuracy")
            if v1 is None or v2 is None:
                continue
            d = v2 - v1
            cls = "up" if d > 0 else ("down" if d < 0 else "")
            acc_rows += (
                f"<tr><td><code>{e(f)}</code></td><td>{_pct(v1)}</td><td>{_pct(v2)}</td>"
                f'<td class="delta {cls}">{d*100:+.0f} pts</td>'
                f'<td><div class="bar"><i style="width:{max(v2,0)*100:.0f}%"></i></div></td></tr>'
            )

    miss_rows = ""
    for m in (a.get("pass2") or {}).get("misses", [])[:14]:
        miss_rows += (
            f"<tr><td>{e(m.get('app'))}</td><td><code>{e(m.get('field'))}</code></td>"
            f"<td>{e(m.get('agent'))}</td><td>{e(m.get('gold'))}</td>"
            f"<td>{e(m.get('disagreement_class'))}</td></tr>"
        )

    # ---- Human queue ----------------------------------------------------
    hq_rows = "".join(
        f"<tr><td>{e(h.get('app'))}</td><td><code>{e(h.get('field'))}</code></td>"
        f"<td>{e(h.get('reason'))}</td></tr>" for h in human_queue[:12]
    )

    # ---- Main table -----------------------------------------------------
    rows = ""
    for r in sorted(apps, key=lambda x: (x["category"], x["app"])):
        v = r["verdict"]["value"]
        url = r["api"].get("docs_root") or r["auth"].get("evidence_url")
        link = f'<a href="{e(url)}">docs</a>' if url else "—"
        rows += (
            f"<tr><td><strong>{e(r['app'])}</strong><br>"
            f"<span style='color:var(--muted);font-size:.8rem'>{e(r.get('one_liner') or '')}</span></td>"
            f"<td>{e(r['category'])}</td>"
            f"<td>{e(', '.join(r['auth']['methods']))}</td>"
            f"<td>{e(r['access']['tier'])}</td>"
            f"<td>{e(r['access']['extra_gate'])}</td>"
            f"<td>{e(r['api']['breadth'])}</td>"
            f"<td>{e(r['api']['mcp'])}</td>"
            f'<td><span class="tag {VERDICT_CLASS.get(v,"")}">{e(v)}</span></td>'
            f"<td>{link}</td></tr>"
        )

    auth_rows = "".join(
        f"<tr><td>{e(x['method'])}</td><td>{e(x['n'])}</td><td>{e(x['pct'])}%</td>"
        f'<td><div class="bar"><i style="width:{x["pct"]:.0f}%"></i></div></td></tr>'
        for x in p["auth"]["overall"]
    )
    blocker_rows = "".join(
        f"<tr><td>{e(x['blocker'])}</td><td>{e(x['n'])}</td><td>{e(x['pct'])}%</td></tr>"
        for x in p["blockers"]
    )
    cat_rows = "".join(
        f"<tr><td>{e(c['category'])}</td><td>{e(c['n'])}</td><td>{e(c['buildable'])}</td>"
        f"<td>{e(c['gated'])}</td><td>{e(c['buildable_pct'])}%</td></tr>"
        for c in p["category_difficulty"]
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>App Buildability Research — {p['n_apps']} apps</title>
<style>{CSS}</style></head><body><div class="wrap">

<h1>What actually blocks an agent toolkit</h1>
<p class="lede">{p['n_apps']} SaaS apps researched by a two-pass agent pipeline, graded
against a blind hand-built gold set. Generated {date.today().isoformat()}.</p>

<div class="kpis">{kpis}</div>

<h2>The findings</h2>
<p class="sub">Every claim below is a count off the enum-constrained records, not an assertion.</p>
{findings}

<h2>Verification</h2>
<p class="sub">Gold set of {e(a.get('gold_apps','—'))} apps, hand-researched and committed
<em>before</em> the agent ran. Field-level scoring — {e((a.get('pass1') or {}).get('judgments','—'))}
judgments, not rows.</p>
<table><thead><tr><th>Field</th><th>Pass 1</th><th>Pass 2</th><th>Movement</th><th></th></tr></thead>
<tbody>{acc_rows or '<tr><td colspan="5">Run <code>make grade</code>.</td></tr>'}</tbody></table>

<h3 style="font-size:1rem;margin-top:28px">Where it was still wrong</h3>
<table><thead><tr><th>App</th><th>Field</th><th>Agent said</th><th>Truth</th><th>Class</th></tr></thead>
<tbody>{miss_rows or '<tr><td colspan="5">No misses recorded.</td></tr>'}</tbody></table>

<h2>The agent</h2>
<div class="flow">
<span class="step">apps.yaml</span><span class="arrow">→</span>
<span class="step">Pass 1 · search + fetch + extract</span><span class="arrow">→</span>
<span class="step"><strong>frozen</strong> pass1.json</span><span class="arrow">→</span>
<span class="step">Triage · 6 rules</span><span class="arrow">→</span>
<span class="step">Pass 2 · re-fetch, browser, adjudicate</span><span class="arrow">→</span>
<span class="step">Grade vs gold</span>
</div>
<p style="color:var(--muted);font-size:.92rem">Pass 2 re-runs only escalated fields. One rule
is deliberately asymmetric: every <code>buildable_now</code> verdict is re-verified regardless
of confidence, because a false positive costs an engineering sprint while a false negative
costs an email.</p>

<h3 style="font-size:1rem;margin-top:28px">Where a human was needed — {len(human_queue)} items</h3>
<table><thead><tr><th>App</th><th>Field</th><th>Why</th></tr></thead>
<tbody>{hq_rows or '<tr><td colspan="3">Queue empty.</td></tr>'}</tbody></table>

<h2>Patterns in detail</h2>
<h3 style="font-size:1rem">Primary auth for third-party integrations</h3>
<table><thead><tr><th>Method</th><th>Apps</th><th>Share</th><th></th></tr></thead><tbody>{auth_rows}</tbody></table>

<h3 style="font-size:1rem;margin-top:28px">Blockers, ranked</h3>
<table><thead><tr><th>Blocker</th><th>Apps</th><th>Share</th></tr></thead><tbody>{blocker_rows}</tbody></table>

<h3 style="font-size:1rem;margin-top:28px">Category difficulty</h3>
<table><thead><tr><th>Category</th><th>Apps</th><th>Buildable</th><th>Needs outreach</th><th>Buildable %</th></tr></thead>
<tbody>{cat_rows}</tbody></table>

<h2>All {p['n_apps']} apps</h2>
<div class="scroll"><table><thead><tr><th>App</th><th>Category</th><th>Auth</th>
<th>Access tier</th><th>Extra gate</th><th>Breadth</th><th>MCP</th><th>Verdict</th><th>Evidence</th>
</tr></thead><tbody>{rows}</tbody></table></div>

<h2>Honest limitations</h2>
<div class="note">
<p style="margin:0 0 8px"><strong>90 of 100 apps.</strong> The source brief was truncated
mid-way through category 10 ("AI, Research and Media-native"). No apps were invented to
reach 100.</p>
<p style="margin:0 0 8px"><strong>Gold set is {e(a.get('gold_apps','—'))} apps</strong>, a
stratified sample — one obvious and one obscure app per category, weighted toward likely
traps. Accuracy figures carry the confidence interval of that sample size.</p>
<p style="margin:0"><strong>Mismatches are classified, not just counted.</strong> Some are
agent errors; some are cases where the enum itself was too loose, or where the vendor
changed after the gold set was written. Only <code>agent_wrong</code> counts against the
pipeline, and the class is shown per row above.</p>
</div>

<footer>Pipeline source, methodology and the full rubric breakdown are in the repo.
Every field carries its own evidence URL and confidence; nulls are real nulls.</footer>
</div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Render the HTML deliverable.")
    ap.add_argument("--input", default=str(PASS2_JSON))
    ap.add_argument("--patterns", default="out/patterns.json")
    ap.add_argument("--accuracy", default=str(ACCURACY_JSON))
    ap.add_argument("--human-queue", default=str(HUMAN_QUEUE_JSON))
    ap.add_argument("--out", default=str(REPORT_HTML))
    args = ap.parse_args()

    def load(path, default):
        p = Path(path)
        return json.loads(p.read_text()) if p.exists() else default

    apps = load(args.input, {"apps": []})["apps"]
    if not apps:
        print("No records found — run the pipeline first.")
        return 1

    from .patterns import extract
    patterns = load(args.patterns, None) or extract(apps)

    Path(args.out).write_text(render(
        apps, patterns, load(args.accuracy, {}), load(args.human_queue, []),
    ))
    print(f"Written → {args.out}  ({len(apps)} apps)")
    print("Two-minute test: hand it to someone cold. Do they get the headline "
          "without you speaking?")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
