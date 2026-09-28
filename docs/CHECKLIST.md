# CHECKLIST — scaffold to submittable

Budget is 6–8 hours. Ordered by rubric weight, so if you run out of time you
lose the least valuable thing. Do **not** reorder to do all the rows first.

---

### Phase 0 — Setup (20 min)
- [ ] `pip install -r requirements.txt`, `cp .env.example .env`
- [ ] `make run` on the `stub` backend — confirm the pipeline runs end to end
- [ ] Skim `docs/RUBRIC.md` and `docs/METHODOLOGY.md`
- [ ] Ask the user for apps 91–100 (category 10 was truncated in the brief)
- [ ] Confirm whether Composio SDK access exists → sets `FETCH_BACKEND`
- [ ] `git init && git commit` the scaffold — you need timestamped history

### Phase 1 — Freeze the contract (30 min)
- [ ] Review enums in `src/schema.py` against `docs/METHODOLOGY.md`
- [ ] Adjust now if at all — after the gold set exists, changes invalidate it
- [ ] `make test` passes
- [ ] Commit: "freeze schema"

### Phase 2 — Gold set, BLIND (90 min) ⚠️ before any agent run
- [ ] Pick 16 apps: one obvious + one obscure per category
- [ ] Hand-research each against real docs. Do not use the pipeline.
- [ ] Fill `data/gold/gold_set.json`
- [ ] **Commit before running pass 1.** This timestamp is your integrity proof.
- [ ] Note any app where you yourself could not decide — that is a finding

### Phase 3 — Pass 1 (60 min)
- [ ] `make pass1` — full run
- [ ] Confirm `out/pass1.json` written and **never touched again**
- [ ] `make triage` — sanity-check the escalation rate
- [ ] If < 20% or > 80% escalates, trigger thresholds are miscalibrated
- [ ] Commit: "pass 1 frozen"

### Phase 4 — Pass 2 (75 min)
- [ ] `make pass2`
- [ ] Spot-check 3 escalations by hand: did verification actually change the answer?
- [ ] Review `out/human_queue.json` — this is a deliverable, not a failure log
- [ ] Commit

### Phase 5 — Grade (45 min)
- [ ] `make grade`
- [ ] Per-field pass 1 vs pass 2 — does it match the prediction in METHODOLOGY §3?
- [ ] Classify every miss: `agent_wrong` / `gold_wrong` / `both_defensible` / `stale`
- [ ] If `both_defensible` > 3, tighten that enum definition and say so on the page
- [ ] **Pick the single most embarrassing miss.** It goes on the page. Honesty
      here is worth more than a higher number.

### Phase 6 — Patterns (45 min)
The actual point. Do not skip because time is short.
- [ ] Auth distribution overall and **by category**
- [ ] `tier` × `extra_gate` cross-tab — does the "gate is post-credential" thesis hold?
- [ ] Most common blocker, counted
- [ ] MCP coverage by category — is it concentrated in dev-tools?
- [ ] Easy wins vs needs-outreach, named apps not just counts
- [ ] Write each as **a claim with a number behind it**, not a hedge

### Phase 7 — The page (90 min)
- [ ] `make report`
- [ ] Patterns at top. Table below. Verification section with real numbers.
- [ ] Agent flow diagram + human-intervention count
- [ ] Honesty section: 90-of-100, apps that defeated it, the worst miss
- [ ] **Two-minute test:** hand it to someone cold. Do they get the headline
      without you speaking? If not, the page is not done.
- [ ] Deploy (GitHub Pages / Vercel / Netlify) — the brief wants a live link

### Phase 8 — Submit (20 min)
- [ ] README explains how to run the agent — the brief asks for this by name
- [ ] Repo public, or access shared
- [ ] Re-read `docs/RUBRIC.md` "Interview-proofing" — can you answer all six?
- [ ] Submit early. The brief rewards it explicitly.

---

## If you are running out of time

Cut in this order:
1. App coverage — 80 good rows beat 100 rushed ones
2. Pass-2 mechanisms — keep claim-in-text checking, drop browser-use
3. Page polish

**Never cut:** the blind gold set, the pass-1 freeze, or the honesty section.
Those are the three things that cannot be reconstructed afterwards and carry the
most weight.
