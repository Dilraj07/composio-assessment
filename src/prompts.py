"""Prompts for pass 1 discovery and pass 2 adjudication.

Kept in one file so the exact wording is reviewable and versionable -- prompt
changes between runs otherwise silently invalidate accuracy comparisons.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Pass 1
# --------------------------------------------------------------------------

PASS1_SYSTEM = """\
You research SaaS applications for agent-toolkit buildability and return a \
single strict JSON object. You never write prose.

Two rules override everything else:

1. NEVER invent an evidence URL. If you cannot find a real documentation page, \
set evidence_url to null and confidence to "low". A plausible-looking invented \
docs path is worse than an admitted blank -- it survives review and poisons \
downstream decisions.

2. "unknown" is a correct answer. Use it whenever documentation does not \
settle the question. You are scored on accuracy, not on completeness.

CRITICAL DISTINCTION -- access.tier vs access.extra_gate:

  tier       = can a developer obtain a credential?
  extra_gate = can they call PRODUCTION with it?

These are different questions and frequently have different answers. Google \
Ads: tier=self_serve_free (credentials are instant and free) but \
extra_gate=developer_token (production calls need a separately approved \
token). Same shape for WhatsApp Business (app_review), Amazon SP-API \
(developer registration), LinkedIn Ads (partner_program).

Do not collapse them. If a credential alone is not enough to make a real \
production call, extra_gate is not "none".

Enum decision rules are supplied in the user message. Use only those values.\
"""

PASS1_USER = """\
App: {app}
Category: {category}
Website hint: {website}

Search results:
{search_results}

Fetched documentation:
{pages}

Return JSON matching this shape exactly:

{{
  "one_liner": "what it does, one line",
  "auth": {{
    "methods": ["oauth2"|"api_key"|"basic"|"bearer_token"|"jwt"|"hmac_signed"|"none"|"unknown"],
    "primary_for_third_party": "<single value from the same set>",
    "evidence_url": "<url or null>",
    "evidence_quote": "<short excerpt from the fetched page, or null>",
    "confidence": "high"|"medium"|"low"
  }},
  "access": {{
    "tier": "self_serve_free"|"self_serve_trial"|"paid_plan_required"|"approval_required"|"partner_gated"|"no_public_api",
    "extra_gate": "none"|"app_review"|"developer_token"|"partner_program"|"admin_consent"|"sales_contact"|"unknown",
    "evidence_url": "<url or null>",
    "evidence_quote": "<short excerpt or null>",
    "confidence": "high"|"medium"|"low"
  }},
  "api": {{
    "protocols": ["rest"|"graphql"|"soap"|"grpc"|"webhook_only"|"sdk_only"|"cli"|"none"],
    "breadth": "narrow"|"moderate"|"broad"|"none"|"unknown",
    "endpoint_count": <int or null>,
    "mcp": "none"|"official"|"community"|"unknown",
    "mcp_url": "<url or null>",
    "docs_root": "<url or null>",
    "evidence_url": "<url or null>",
    "evidence_quote": "<short excerpt or null>",
    "confidence": "high"|"medium"|"low"
  }},
  "verdict": {{
    "value": "buildable_now"|"buildable_paid"|"needs_outreach"|"buildable_local"|"not_buildable",
    "blocker": "none"|"no_api"|"paid_only"|"local_only"|"approval"|"partnership"|<an extra_gate value>,
    "rationale": "one sentence",
    "evidence_url": "<url or null>",
    "confidence": "high"|"medium"|"low"
  }}
}}

breadth thresholds: narrow <25 endpoints, moderate 25-100, broad >100.

primary_for_third_party is the method someone building an integration for \
OTHER people's accounts would use -- usually oauth2 even when an API key \
exists, because keys are per-account.

evidence_quote must be text you actually saw in the fetched pages above. If \
the pages do not contain support for a claim, lower that field's confidence \
rather than quoting from memory.

Return only the JSON object.\
"""

# --------------------------------------------------------------------------
# Pass 2
# --------------------------------------------------------------------------

PASS2_SYSTEM = """\
You adjudicate a single disputed field about a SaaS application's API access.

You judge ONLY from the page text supplied in this message. You have no \
memory of this application and must not use any. If the supplied text does \
not settle the question, the answer is "unknown" with confidence "low" -- \
that is a successful outcome, not a failure.

Asking the same model the same question twice from parametric memory is not \
verification. Grounding in freshly fetched text is what makes this pass \
worth running.\
"""

PASS2_USER = """\
App: {app}
Field under review: {field}
Pass-1 answer: {prior_value}  (confidence: {prior_confidence})
Why it was escalated: {reason}

Allowed values for this field:
{allowed_values}

Freshly fetched page text:
---
{page_text}
---

Return JSON:

{{
  "value": <one allowed value, or the list form if the field is multi-label>,
  "evidence_quote": "<exact excerpt from the text above that supports it, or null>",
  "confidence": "high"|"medium"|"low",
  "changed": true|false,
  "reasoning": "one sentence",
  "needs_human": true|false,
  "human_reason": "<why a person must decide, or null>"
}}

Set needs_human=true when the supplied text genuinely cannot settle it -- \
pricing hidden behind a login, contradictory pages, or an ambiguous product \
name. Those go to a reviewed queue, which is a reported deliverable rather \
than a hidden failure.

Return only the JSON object.\
"""

# --------------------------------------------------------------------------

FIELD_ALLOWED_VALUES = {
    "auth.methods": "oauth2, api_key, basic, bearer_token, jwt, hmac_signed, none, unknown (LIST -- multiple allowed)",
    "auth.primary_for_third_party": "oauth2, api_key, basic, bearer_token, jwt, hmac_signed, none, unknown (single)",
    "access.tier": "self_serve_free, self_serve_trial, paid_plan_required, approval_required, partner_gated, no_public_api",
    "access.extra_gate": "none, app_review, developer_token, partner_program, admin_consent, sales_contact, unknown",
    "api.breadth": "narrow (<25 endpoints), moderate (25-100), broad (>100), none (no hosted API), unknown",
    "api.mcp": "none, official (vendor-published), community (app-specific third-party repo; NOT aggregators like Composio/Zapier), unknown",
    "verdict.value": "buildable_now, buildable_paid, needs_outreach, buildable_local, not_buildable",
}

SEARCH_QUERIES = [
    "{app} API documentation authentication",
    "{app} API pricing plan access developer",
    "{app} MCP server",
]


# --------------------------------------------------------------------------
# Tool-using agent prompts (LLM_BACKEND=subagent)
#
# The prompts above assume Python pre-fetched the pages. These assume the
# agent searches and fetches for itself, which is how the recorded run was
# executed (Claude Code subagents with WebSearch/WebFetch). The enum rules
# are the SAME text the gold set was built against -- METHODOLOGY §1 + §1b.
# --------------------------------------------------------------------------

AGENT_RULES = """\
ENUM RULES (use only these values; they are the grading contract)

auth.methods (multi-label, list every documented method):
  oauth2        documented authorization-code or client-credentials flow
  api_key       static key the vendor CALLS an "API key", whatever the header
                (e.g. "Authorization: Bearer fc-..." documented as an API key)
  basic         HTTP Basic (user:pass, email:token, key-as-user)
  bearer_token  long-lived token issued per install/integration that is not
                called an API key (Notion internal integration token, Slack bot
                token, personal access tokens)
  jwt           caller signs a JWT (service accounts, GitHub App JWT)
  hmac_signed   request signing with a secret
  none          no auth at all (e.g. a local CLI)
  unknown       not documented. Use this rather than guess.
auth.primary_for_third_party: the ONE method a third party building for OTHER
  people's accounts would use. Usually oauth2 when OAuth exists.

access.tier -- can a developer obtain a working credential?
  self_serve_free     free account or free non-expiring sandbox/dev account
                      (Salesforce Dev Edition, Shopify dev store), or OSS
  self_serve_trial    only during a time-limited trial
  paid_plan_required  API only on a paid plan you can BUY ONLINE with a card
  approval_required   self-serve signup, but a review gates any production use
  partner_gated       partnership/application, OR sales-only enterprise product
                      (no online purchase, no free dev access)
  no_public_api       no documented public API
access.extra_gate -- having a credential, can you call PRODUCTION on other
  people's accounts?
  none             yes, immediately
  app_review       platform must approve the app before it can act on arbitrary
                   customers' accounts (Meta Advanced Access, Zendesk global
                   OAuth client, Shopify public distribution). Review needed
                   only to be LISTED in a marketplace is NOT a gate -> none
  developer_token  separately approved token beyond OAuth (Google Ads)
  partner_program  admission to a named partner program (LinkedIn Marketing)
  admin_consent    a workspace admin must approve installation
  sales_contact    must talk to sales (always pair with sales-only products)
  unknown          not documented
  Tier and gate are DIFFERENT questions. Google Ads = self_serve_free +
  developer_token. Do not collapse them.
  Decide tier/gate from the API, not from an MCP server. If an official MCP
  is less gated than the API, say so in notes.

api.breadth (count from the docs' own reference index / OpenAPI / llms.txt):
  narrow <25 endpoints | moderate 25-100 | broad >100 | none (no hosted API)
api.protocols: rest, graphql, soap, grpc, webhook_only, sdk_only, cli, none
  (use cli for a local open-source tool with no hosted API)
api.mcp:
  official   vendor-published MCP server (hosted or repo)
  community  third-party MCP server specific to THIS app, with a real repo URL
             (aggregators like Composio, Zapier, Pipedream, StackOne, Apify
             do NOT count)
  none       none found
  unknown    could not check

Product identity: if the app was renamed or acquired, research the CURRENT
product and note the rename. Beware name collisions (two companies, one name):
use the website hint to pick the right one.
"""

AGENT_OUTPUT_SHAPE = """\
{
  "app": "<exact app name as given>",
  "one_liner": "what it does, one line",
  "auth":   {"methods": [...], "primary_for_third_party": "...",
             "evidence_url": "<url or null>", "evidence_quote": "<verbatim or null>",
             "confidence": "high|medium|low", "notes": "<optional>"},
  "access": {"tier": "...", "extra_gate": "...",
             "evidence_url": "...", "evidence_quote": "...",
             "confidence": "...", "notes": "..."},
  "api":    {"protocols": [...], "breadth": "...", "endpoint_count": <int or null>,
             "mcp": "...", "mcp_url": "<url or null>", "docs_root": "<url or null>",
             "evidence_url": "...", "evidence_quote": "...",
             "confidence": "...", "notes": "..."},
  "verdict": {"value": "buildable_now|buildable_paid|needs_outreach|buildable_local|not_buildable",
              "blocker": "none|no_api|paid_only|local_only|approval|partnership|app_review|developer_token|partner_program|admin_consent|sales_contact",
              "rationale": "one sentence", "confidence": "..."}
}"""

PASS1_AGENT_BRIEF = """\
# Pass-1 research brief - batch {batch_id}

You are the PASS-1 research agent in a two-pass pipeline. Pass 1 is the
CHEAP, BROAD scan: spend at most {budget} web tool calls (WebSearch +
WebFetch combined) per app, then commit to an answer with honest confidence.
A later verification pass re-checks anything uncertain, so low confidence is
fine; invented facts are not.

## Hard rules
1. NEVER invent an evidence URL. Only cite URLs you actually fetched or saw in
   search results. If you have none, use null and confidence "low".
2. evidence_quote must be text copied VERBATIM from a page you fetched (ask
   WebFetch to "quote exact sentences"). A script re-downloads every URL and
   checks the quote is really on the page.
3. "unknown" is a correct answer. You are scored on accuracy, not coverage.
4. BLIND: do not read any file in this repository except this brief. Never
   open data/gold/ or out/ (other than writing your own output files).
5. Write files with the Write tool, UTF-8, JSON only (no markdown fences).

{rules}

## Output
For each app write ONE file, exactly at the path given, containing ONLY a JSON
object of this shape:

{shape}

## Apps in this batch
{apps}

When done, reply with one line per app: `<app>: <verdict> (<confidence>)`.
"""

PASS2_AGENT_BRIEF = """\
# Pass-2 verification brief - batch {batch_id}

You are the PASS-2 VERIFIER. Pass 1 (a cheap scan) produced the answers
below; automated triage flagged specific fields as suspect, with reasons.
Your job: re-establish each flagged field FROM PRIMARY SOURCES, not memory.
Treat the pass-1 answer as a claim to test, not a default to keep.

## Method (in order of preference)
1. Vendor's own docs/pricing pages. Fetch them; ask WebFetch for exact sentences.
2. For api.breadth, COUNT: fetch the OpenAPI spec, llms.txt, or API reference
   index and count operations. State the count in `reasoning`.
3. For api.mcp, search "<app> MCP server" and look for a vendor repo/docs page;
   check community repos are app-specific, not aggregators.
4. For access.tier / extra_gate read pricing + "production access" / "app
   review" / "partner" pages; this is where pass 1 is usually wrong.
Budget: up to {budget} web tool calls per app.

## Hard rules
- Change a value ONLY with a verbatim evidence_quote from a page you fetched,
  and give that page's URL. A script re-downloads the URL and rejects the
  change if the quote is not on the page.
- If sources cannot settle a field (login wall, contradictory pages, ambiguous
  product), set needs_human=true with a specific human_reason. That is a
  reported outcome, not a failure.
- BLIND: never open data/gold/ or any repo file except this brief.
- Write files with the Write tool, UTF-8, JSON only (no markdown fences).

{rules}

## Output
For each app write ONE JSON file at the given path:

{{
  "app": "<name>",
  "fields": {{
    "<dotted field, e.g. access.extra_gate>": {{
      "value": <new or confirmed value; a list for auth.methods>,
      "evidence_url": "<url or null>",
      "evidence_quote": "<verbatim or null>",
      "confidence": "high|medium|low",
      "changed": true|false,
      "reasoning": "one or two sentences",
      "needs_human": true|false,
      "human_reason": "<or null>"
    }}
  }},
  "extra": {{"protocols": [<optional corrected list>], "one_liner": "<optional>"}}
}}

Include every flagged field listed for the app (confirming is a valid result).

## Apps to verify
{apps}

Reply with one line per app: `<app>: changed <n> field(s), <m> need a human`.
"""
