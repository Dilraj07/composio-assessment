# Pass-1 research brief - batch 10

You are the PASS-1 research agent in a two-pass pipeline. Pass 1 is the
CHEAP, BROAD scan: spend at most 4 web tool calls (WebSearch +
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


## Output
For each app write ONE file, exactly at the path given, containing ONLY a JSON
object of this shape:

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
}

## Apps in this batch
- **NotebookLM** (#91, AI, Research & Media-native), website hint: `cloud.google.com/gemini` (Enterprise API)
  -> write `out/work/pass1/raw/091_notebooklm.json`
- **Otter AI** (#92, AI, Research & Media-native), website hint: `help.otter.ai` (MCP server)
  -> write `out/work/pass1/raw/092_otter-ai.json`
- **Fathom** (#93, AI, Research & Media-native), website hint: `fathom.video`
  -> write `out/work/pass1/raw/093_fathom.json`
- **Consensus** (#94, AI, Research & Media-native), website hint: `consensus.app` (OAuth requested)
  -> write `out/work/pass1/raw/094_consensus.json`
- **Reducto** (#95, AI, Research & Media-native), website hint: `reducto.ai` (document parsing)
  -> write `out/work/pass1/raw/095_reducto.json`
- **Devin** (#96, AI, Research & Media-native), website hint: `docs.devin.ai` (MCP)
  -> write `out/work/pass1/raw/096_devin.json`
- **higgsfield** (#97, AI, Research & Media-native), website hint: `higgsfield.ai/cli` (content suite)
  -> write `out/work/pass1/raw/097_higgsfield.json`
- **Mermaid CLI** (#98, AI, Research & Media-native), website hint: `github.com/mermaid-js/mermaid-cli`
  -> write `out/work/pass1/raw/098_mermaid-cli.json`
- **YouTube Transcript** (#99, AI, Research & Media-native), website hint: `transcriptapi.com`
  -> write `out/work/pass1/raw/099_youtube-transcript.json`
- **Grain** (#100, AI, Research & Media-native), website hint: `grain.com` (meeting notes)
  -> write `out/work/pass1/raw/100_grain.json`

When done, reply with one line per app: `<app>: <verdict> (<confidence>)`.
