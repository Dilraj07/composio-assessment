# CLAUDE.md — orientation for Claude Code

Read this first. It tells you what this repo is, what "done" means, and the
three rules that are easy to break and expensive to break.

## What this is

A take-home for a Composio AI Product Ops Intern role. The job: research ~100
SaaS apps for agent-toolkit buildability, find the *patterns*, and prove the
findings are accurate. Full brief in `docs/ASSIGNMENT.md`.

## What is actually graded

Read `docs/RUBRIC.md` before writing any code. Short version, because it is
counterintuitive:

- The 100-row table is **table stakes**, not the deliverable.
- The **verification story** (pass-1 accuracy → pass-2 accuracy, with honest
  misses shown) carries the most weight. The brief says "Accuracy is what
  matters most" and asks explicitly to "show how accuracy moved from a lower
  first pass to a higher one."
- The **patterns** are the headline and go at the top of the page.
- Clarity of the single HTML page is worth more than row count.

A candidate with 80 excellent rows, a real accuracy number and a sharp pattern
beats one with 100 mediocre rows and no verification.

## Three rules that are easy to break

**1. Freeze pass 1 before you run pass 2.**
`out/pass1.json` is your "before" number. Once pass 2 overwrites records in
place, you cannot reconstruct it, and the entire accuracy-delta story — the
highest-weighted part of the rubric — is gone. `pass1_discover.py` writes it
and `pass2_verify.py` reads it and writes to a *separate* file by design. Do
not "simplify" this into one file.

**2. Build the gold set blind.**
Hand-research the 16 sample apps and commit `data/gold/gold_set.json` **before**
running the agent on them, with a real git commit so the timestamp is
verifiable. If you grade after seeing agent output you will unconsciously
rubber-stamp it, the number is worthless, and the interviewer will ask how you
avoided exactly this.

**3. Never invent an evidence URL.**
Every claim carries `evidence_url`. If the pipeline cannot find a real one, the
correct value is `null` with `confidence: "low"` — not a plausible-looking
docs path. `fetch.py` verifies URLs resolve *and* that the claim text appears
on the page. A confident wrong answer costs more than an honest blank.

## Repo map

```
docs/           read RUBRIC.md and METHODOLOGY.md before coding
data/apps.yaml  the research set (see "Known gap" below)
data/gold/      hand-verified ground truth — the blind sample
src/schema.py   enums + validation. Freeze this before pass 1.
src/fetch.py    search/fetch layer. Pluggable: Composio, direct, or stub.
src/pass1_discover.py   broad, cheap, first pass
src/triggers.py         decides what gets escalated to pass 2
src/pass2_verify.py     targeted re-verification
src/grade.py            field-level accuracy, pass 1 vs pass 2
src/report.py           builds the single-page HTML deliverable
out/            generated artifacts (pass1.json, pass2.json, report.html)
```

## Known gaps — do not silently paper over these

1. **The app list is incomplete.** The source brief was truncated mid-way
   through category 10 ("AI, Research and Media-native"). `data/apps.yaml`
   has 90 apps and a `TODO_CATEGORY_10` block. Ask the user for the final ~10
   before claiming a 100-app run. If they are never supplied, say "90 of 100,
   list truncated in the source brief" on the page. Do not invent apps.
2. **Composio SDK access is unconfirmed.** `fetch.py` has three backends
   selected by env var; `stub` works with no credentials so the pipeline is
   runnable end-to-end today.

## Working style for this repo

- Python 3.11+, stdlib + `pydantic`, `httpx`, `pyyaml`. Keep dependencies thin.
- Every module runnable standalone: `python -m src.pass1_discover --limit 5`.
- Commit after each pipeline stage works, so the run is reproducible.
- When a judgment call comes up (is this "gated" or "paid plan"?), check the
  enum definitions in `docs/METHODOLOGY.md` rather than deciding fresh — the
  gold set was built against those definitions.
