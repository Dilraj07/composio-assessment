# RUBRIC — what is actually being graded

Derived from the brief's own emphasis. Read before writing code; it changes
where you spend your hours.

## The trap

The assignment *looks* like "research 100 apps." It says otherwise in three
places:

> "Do not just produce 100 rows... **Insight over raw table.**"

> "**Accuracy is what matters most.**"

> "show how accuracy moved from a lower first pass to a higher one because of
> those loops"

Most candidates will spend 6 hours on rows and 30 minutes on the page. The
weighting rewards the opposite.

## Estimated weighting

| Component | Weight | Why |
|---|---|---|
| Verification story (pass-1 → pass-2 delta, honest misses) | ~35% | Stated as the top priority, and explicitly asked for as a *movement*, not a single number |
| Patterns / clustering | ~25% | "The actual point." Must be the page headline |
| Page clarity — 2 minutes, no narration | ~20% | "Clarity and presentation are the point" |
| The agent itself + where a human was needed | ~15% | Asked for by name, including the human-intervention question |
| Raw table coverage | ~5% | Table stakes. Necessary, not differentiating |

**Implication:** 80 excellent rows with a real accuracy number and a sharp
pattern beats 100 mediocre rows with no verification. Do not trade verification
time for coverage.

## Scoring checklist

Findings
- [ ] Skimmable table/matrix, filterable or at least sortable
- [ ] Every row's claims carry an evidence URL
- [ ] Blanks shown as blanks, never filled with plausible guesses

Patterns — **top of page**
- [ ] Stated plainly as claims, not hedged observations
- [ ] Which auth dominates, and in which categories
- [ ] Which categories are self-serve vs gated
- [ ] The single most common blocker
- [ ] Easy wins vs needs-outreach, named explicitly
- [ ] Each pattern backed by a count from the data, not vibes

The agent
- [ ] What it does, in a diagram or short flow
- [ ] Where a human was needed — **with a count**, from `out/human_queue.json`
- [ ] Runnable: live link or trigger a reviewer can actually hit

Verification
- [ ] Sample size and how it was stratified
- [ ] Gold set built **blind**, before agent output was seen — say so
- [ ] Per-field accuracy, pass 1 vs pass 2
- [ ] Individual misses shown, with agent value vs gold value
- [ ] At least one case where the agent was confidently wrong, shown honestly

Honesty
- [ ] Apps that defeated the pipeline named explicitly
- [ ] The 90-of-100 truncation disclosed
- [ ] Gated apps reported as findings, not failures — the brief says so directly

## Interview-proofing

The brief warns: *"understand and be able to explain everything you submit; the
interview will probe it."* Expect these:

- Why field-level accuracy rather than row-level?
- How did you avoid grading yourself favourably on the gold set?
- Why verify `buildable_now` even at high confidence?
- Which field did the agent do worst on, and why that one specifically?
- Where did the pipeline need a human, and could that be automated away?
- Why separate `tier` from `extra_gate`?

If any answer is "the model decided," that is a gap to close before submitting.
