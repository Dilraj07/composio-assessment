# App Buildability Research Pipeline

Schema-first research pipeline that classifies ~100 SaaS apps for agent-toolkit
buildability, escalates low-confidence answers to a verification pass, grades
both passes against a hand-built gold set, and renders a single-page HTML case
study.

Built for the Composio AI Product Ops Intern take-home. Brief: `docs/ASSIGNMENT.md`.

---

## The core idea

Most approaches to "research 100 apps" let a model write prose per app. That
output cannot be clustered and cannot be graded. This pipeline instead forces
**one strict JSON record per app**, every judgment field enum-constrained, every
field carrying its own `evidence_url` and `confidence`.

That single decision is what makes the other two requirements possible:

- **Patterns** fall out of enum value counts instead of being asserted.
- **Accuracy** is measurable field-by-field, so pass 1 vs pass 2 is a real number.

### The design decision worth defending

`access.tier` and `access.extra_gate` are **separate fields**. Collapsing
"self-serve vs gated" into one field conflates two different questions:

| Question | Google Ads |
|---|---|
| Can I get a credential? | Yes — free, instant |
| Can I call production with it? | No — developer token needs approval |

Same shape for WhatsApp Business (Meta app review + BSP), Amazon SP-API
(developer registration), LinkedIn Ads (partner program admission). Collapse
them and you either mislabel them all self-serve — making every buildability
verdict wrong — or all gated, losing the finding.

Kept separate, the pattern emerges from the data rather than being claimed:
**the blocker is usually not auth, it's the approval step after you already have
credentials.**

---

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional: add keys for a live run

make run                      # full pipeline, stub backend, no credentials needed
open out/report.html
```

Runs end-to-end with zero credentials on the `stub` backend so you can see the
shape of every artifact before spending an API call.

### Stage by stage

```bash
make pass1          # broad discovery      → out/pass1.json   (FROZEN)
make triage         # show what escalates  → out/triage.json
make pass2          # targeted re-verify   → out/pass2.json
make grade          # accuracy vs gold set → out/accuracy.json
make report         # single-page HTML     → out/report.html
make test           # trigger logic tests
```

Each is also runnable directly with flags:

```bash
python -m src.pass1_discover --limit 5 --category "CRM & Sales"
python -m src.pass2_verify --only-triggered
python -m src.grade --pass1 out/pass1.json --pass2 out/pass2.json
```

---

## How it works

### Pass 1 — broad discovery
Search + fetch per app, fill the schema, self-report confidence per field.
Cheap and wide. Expect roughly a quarter of fields to be wrong.

**Output is frozen to `out/pass1.json` and never mutated.** It is the "before"
number in the accuracy story.

### Triage — what deserves a second look
`src/triggers.py` escalates a field on any of:

| Trigger | Rationale |
|---|---|
| `confidence != high` | baseline |
| evidence URL not on the vendor's own domain | blog/aggregator citations are where hallucination hides |
| URL 404s, or claim text absent from the fetched page | model invented a plausible docs path |
| `tier == self_serve_*` **and** `extra_gate == unknown` | most likely false positive |
| `verdict == buildable_now` | **always**, regardless of confidence |
| cross-field contradiction | e.g. `no_public_api` with protocols listed |

That fifth rule is deliberate asymmetry. A false "buildable now" costs a wasted
engineering sprint; a false "needs outreach" costs an email. The expensive
direction gets verified harder.

### Pass 2 — targeted verification
Only triggered fields re-run. Three mechanisms:

1. Fetch the cited page and confirm the claim **appears in the text** — not just
   that the URL resolves.
2. Browser-use for pricing and plan pages, which are JS-heavy and almost never
   covered in docs.
3. A second model adjudicating **from fetched text only**, no parametric memory.
   Asking the same model twice from memory is not verification.

Anything still unresolved goes to a human queue in `out/human_queue.json`. That
queue, with a count, is the literal answer to the brief's "tell us where it
needed a human."

### Grading
Field-level, not row-level: 6 graded fields × 16 gold apps = 96 judgments. Row
accuracy is both brutal and uninformative — one wrong `breadth` should not zero
out an otherwise perfect row.

`out/accuracy.json` reports per-field pass 1 vs pass 2, plus every individual
miss with the agent value, gold value and evidence. The misses go on the page.

---

## Configuration

| Env var | Values | Notes |
|---|---|---|
| `FETCH_BACKEND` | `stub` \| `direct` \| `composio` | `stub` needs no credentials |
| `ANTHROPIC_API_KEY` | — | pass 1 + pass 2 adjudication |
| `COMPOSIO_API_KEY` | — | only for `composio` backend |
| `MAX_CONCURRENCY` | int, default 6 | be polite to docs sites |

The fetch layer is deliberately pluggable. `src/fetch.py` defines one
`SearchBackend` protocol with three implementations, so swapping Composio in or
out never touches pipeline logic.

---

## Status and honest gaps

- **90 of 100 apps.** The source brief was truncated mid-way through category 10
  ("AI, Research and Media-native"). `data/apps.yaml` carries the 90 confirmed
  apps and a `TODO_CATEGORY_10` placeholder. No apps were invented to reach 100.
- **Composio SDK access unconfirmed** at time of scaffolding; `stub` and
  `direct` backends work regardless.
- Gold set is a 16-app stratified sample (~18% of the set), one obvious and one
  obscure app per category, weighted toward the traps.

---

## Repo map

```
CLAUDE.md                orientation + the three rules that are easy to break
docs/ASSIGNMENT.md       the original brief
docs/RUBRIC.md           what is actually graded, and the weighting
docs/METHODOLOGY.md      enum definitions + gold-set protocol
docs/CHECKLIST.md        step-by-step to a submittable deliverable
data/apps.yaml           the research set
data/gold/               hand-verified ground truth
src/                     pipeline
out/                     generated artifacts
```
