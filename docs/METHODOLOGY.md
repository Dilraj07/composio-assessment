# METHODOLOGY

Enum definitions and the verification protocol. **Freeze this before running
pass 1** — the gold set is built against these definitions, and changing them
afterwards invalidates every accuracy number.

---

## 1. Enum definitions

Ambiguous enums are the main source of fake disagreement between agent and gold
set. Each value below has a decision rule, not just a name.

### `auth.methods` — multi-label

| Value | Decision rule |
|---|---|
| `oauth2` | Documented authorization-code or client-credentials flow |
| `api_key` | Static key in header or query, no token exchange |
| `basic` | HTTP Basic, user:pass or key-as-user |
| `bearer_token` | Long-lived opaque token, not OAuth-issued (e.g. Slack bot tokens, Notion integration tokens) |
| `jwt` | Caller signs/constructs a JWT (service accounts, app-level auth) |
| `hmac_signed` | Request signing with a secret (common in exchanges, webhooks) |
| `none` | Public, unauthenticated endpoints |
| `unknown` | No documentation found — **use this, do not guess** |

**Multi-label is required.** Many apps offer an API key for server-to-server and
OAuth for third-party apps. Forcing one label is where accuracy silently dies.

`auth.primary_for_third_party` = the single method a third party building an
integration for *other people's* accounts would use. For most apps that is
`oauth2` even when an API key exists, because keys are per-account.

### `access.tier`

| Value | Decision rule |
|---|---|
| `self_serve_free` | Free account → credentials, no human in the loop, no card |
| `self_serve_trial` | Credentials during a time-limited trial; lapses to paid |
| `paid_plan_required` | API only on a paid tier, but purchasable online without talking to anyone |
| `approval_required` | Signup is self-serve, but a human/automated review gates production use |
| `partner_gated` | Requires partnership, reseller status, or an accepted application |
| `no_public_api` | No documented public API at all |

### `access.extra_gate` — the load-bearing field

What stands between *having a credential* and *calling production*.

| Value | Decision rule |
|---|---|
| `none` | Credential works in production immediately |
| `app_review` | Platform reviews the app before production access (Meta, Pinterest) |
| `developer_token` | A separately-approved token beyond OAuth credentials (Google Ads) |
| `partner_program` | Admission to a named partner program (LinkedIn Marketing) |
| `admin_consent` | A workspace/org admin must approve installation |
| `sales_contact` | Must talk to sales to get access |
| `unknown` | Not documented |

`tier: self_serve_free` + `extra_gate: developer_token` is a valid and common
combination. That is the point of splitting them.

### `api.breadth` — numeric, so it is scoreable

| Value | Rule |
|---|---|
| `narrow` | < 25 documented endpoints / GraphQL root fields |
| `moderate` | 25–100 |
| `broad` | > 100 |

Count from the docs' own reference index. If uncounted, estimate from section
count and mark `confidence: medium`.

### `api.mcp`

`none` | `official` (vendor-published) | `community` (third-party) | `unknown`.
Community servers must have a real repo URL to count.

### `verdict.value`

| Value | Rule |
|---|---|
| `buildable_now` | A dev could ship a toolkit this week with a free account |
| `buildable_paid` | Same, but needs a purchasable paid plan |
| `needs_outreach` | Blocked on approval, partnership or sales contact |
| `not_buildable` | No public API, or API cannot support agent actions |

---

## 2. Gold set protocol

### Stratification
16 apps — roughly 18% of the set. Per category: one **obvious** app (well
documented, high prior) and one **obscure** app (thin or absent docs). Skewed
toward apps likely to defeat the pipeline, because that is where the
informative errors are.

Candidate traps in the set: Sherlock (a CLI project, not an API at all),
iPayX, fanbasis, Waterfall.io, Paygent Connect, PitchBook, Gladly, DealCloud.

### Blind procedure — non-negotiable

1. Pick the 16 apps. Commit the list.
2. Hand-research each. Read real docs. Fill `data/gold/gold_set.json` yourself.
3. **Commit the gold set.** The git timestamp is your proof it predates the run.
4. *Then* run pass 1.
5. Grade by diff.

Grading after seeing agent output produces a number nobody should believe,
including you. The interviewer will ask how you avoided it; the commit history
is the answer.

### Recording disagreements

Not every mismatch is an agent error. Classify each:

| Class | Meaning | Counts against agent? |
|---|---|---|
| `agent_wrong` | Agent's answer is false | Yes |
| `gold_wrong` | Hand research was wrong; fix gold, note it | No — but disclose |
| `both_defensible` | Enum genuinely ambiguous for this app | No — tighten the enum definition and say so |
| `stale` | Both right at different times; vendor changed | No — note the date |

`both_defensible` appearing more than 2–3 times means an enum definition is too
loose. Fix the definition, not the data.

---

## 3. Accuracy metric

Field-level across 6 graded fields:

`auth.methods` · `auth.primary_for_third_party` · `access.tier` ·
`access.extra_gate` · `api.breadth` · `verdict.value`

6 × 16 = 96 judgments. `auth.methods` is multi-label, scored as exact set match
(strict) with Jaccard overlap reported alongside (informative).

Report **per-field**, pass 1 vs pass 2. The shape matters more than the
headline number.

### Prior expectation

Written down in advance so the result is a test rather than a description:

| Field | Expected pass 1 | Expected pass 2 |
|---|---|---|
| `auth.methods` | ~85–90% | ~95% |
| `api.breadth` | ~70% | ~80% |
| `access.tier` | ~65% | ~85% |
| `access.extra_gate` | ~55% | ~85% |
| `verdict.value` | ~60% | ~85% |

The predicted shape: **the model reads documentation well and infers commercial
gating badly.** If the results contradict this, that is a more interesting
finding than confirming it — report it either way.

---

## 4. Human-intervention log

Every escalation that pass 2 cannot resolve is appended to
`out/human_queue.json` with app, field, and reason. Categories seen so far:

- Pricing page behind JS/geo-gating that browser-use could not read
- Vendor with no docs site at all (verdict requires a judgment call)
- Docs contradicting the pricing page
- App name ambiguous (multiple products share it)

This file *is* the answer to "tell us where it needed a human." Report the count
and the breakdown, not a vague sentence.
