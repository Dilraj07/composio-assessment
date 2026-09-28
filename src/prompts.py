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
    "protocols": ["rest"|"graphql"|"soap"|"grpc"|"webhook_only"|"sdk_only"|"none"],
    "breadth": "narrow"|"moderate"|"broad"|"unknown",
    "endpoint_count": <int or null>,
    "mcp": "none"|"official"|"community"|"unknown",
    "mcp_url": "<url or null>",
    "docs_root": "<url or null>",
    "evidence_url": "<url or null>",
    "evidence_quote": "<short excerpt or null>",
    "confidence": "high"|"medium"|"low"
  }},
  "verdict": {{
    "value": "buildable_now"|"buildable_paid"|"needs_outreach"|"not_buildable",
    "blocker": "none"|"no_api"|"paid_only"|<an extra_gate value>,
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
    "api.breadth": "narrow (<25 endpoints), moderate (25-100), broad (>100), unknown",
    "verdict.value": "buildable_now, buildable_paid, needs_outreach, not_buildable",
}

SEARCH_QUERIES = [
    "{app} API documentation authentication",
    "{app} API pricing plan access developer",
    "{app} MCP server",
]
