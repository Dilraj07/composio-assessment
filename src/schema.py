"""Record schema for app buildability research.

FREEZE THIS BEFORE RUNNING PASS 1. The gold set is hand-built against these
enums; changing them afterwards invalidates every accuracy number.

Decision rules for each enum value live in docs/METHODOLOGY.md §1. When a value
is ambiguous for a given app, consult that file rather than deciding fresh --
the gold set was built against those definitions.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------

class AuthMethod(str, Enum):
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    BASIC = "basic"
    BEARER_TOKEN = "bearer_token"
    JWT = "jwt"
    HMAC_SIGNED = "hmac_signed"
    NONE = "none"
    UNKNOWN = "unknown"


class AccessTier(str, Enum):
    SELF_SERVE_FREE = "self_serve_free"
    SELF_SERVE_TRIAL = "self_serve_trial"
    PAID_PLAN_REQUIRED = "paid_plan_required"
    APPROVAL_REQUIRED = "approval_required"
    PARTNER_GATED = "partner_gated"
    NO_PUBLIC_API = "no_public_api"


class ExtraGate(str, Enum):
    """What stands between HAVING a credential and CALLING production.

    Deliberately separate from AccessTier. Google Ads is self_serve_free +
    developer_token: credentials are instant and free, but production calls
    need a separately approved token. Collapsing these into one field makes
    every buildability verdict for that class of app wrong.
    """

    NONE = "none"
    APP_REVIEW = "app_review"
    DEVELOPER_TOKEN = "developer_token"
    PARTNER_PROGRAM = "partner_program"
    ADMIN_CONSENT = "admin_consent"
    SALES_CONTACT = "sales_contact"
    UNKNOWN = "unknown"


class Protocol(str, Enum):
    REST = "rest"
    GRAPHQL = "graphql"
    SOAP = "soap"
    GRPC = "grpc"
    WEBHOOK_ONLY = "webhook_only"
    SDK_ONLY = "sdk_only"
    CLI = "cli"          # local open-source tool, no hosted API (Sherlock, Mermaid CLI)
    NONE = "none"


# Surfaces that exist without a hosted API. Allowed alongside no_public_api.
LOCAL_PROTOCOLS = {Protocol.CLI, Protocol.SDK_ONLY, Protocol.NONE}


class Breadth(str, Enum):
    """Numeric so it is scoreable. See METHODOLOGY §1.

    narrow   < 25 documented endpoints / GraphQL root fields
    moderate 25-100
    broad    > 100
    """

    NARROW = "narrow"
    MODERATE = "moderate"
    BROAD = "broad"
    NONE = "none"        # no hosted API at all
    UNKNOWN = "unknown"


class McpStatus(str, Enum):
    """official   = vendor-published MCP server (hosted or repo).
    community  = a third-party server specific to THIS app, with a real repo.
                 Multi-app aggregators (Composio, Zapier, Pipedream) do not
                 count -- otherwise nearly every app would be "community".
    """

    NONE = "none"
    OFFICIAL = "official"
    COMMUNITY = "community"
    UNKNOWN = "unknown"


class Verdict(str, Enum):
    BUILDABLE_NOW = "buildable_now"
    BUILDABLE_PAID = "buildable_paid"
    NEEDS_OUTREACH = "needs_outreach"
    BUILDABLE_LOCAL = "buildable_local"  # no hosted API; wrap the OSS CLI/library as a local skill
    NOT_BUILDABLE = "not_buildable"


OUTREACH_GATES = {
    ExtraGate.APP_REVIEW, ExtraGate.DEVELOPER_TOKEN,
    ExtraGate.PARTNER_PROGRAM, ExtraGate.SALES_CONTACT,
}


def derive_verdict(tier: AccessTier, gate: ExtraGate,
                   protocols: list[Protocol]) -> Verdict:
    """The verdict is a RULE over tier + extra_gate, not a model judgment.

    METHODOLOGY §1 "verdict.value". Deriving it removes a whole class of
    agent/gold disagreement that would otherwise be about wording, and makes
    every verdict explainable from two evidenced fields.
    """
    if tier == AccessTier.NO_PUBLIC_API:
        local = {Protocol.CLI, Protocol.SDK_ONLY}
        return Verdict.BUILDABLE_LOCAL if local & set(protocols) else Verdict.NOT_BUILDABLE
    if tier in (AccessTier.APPROVAL_REQUIRED, AccessTier.PARTNER_GATED) or gate in OUTREACH_GATES:
        return Verdict.NEEDS_OUTREACH
    if tier == AccessTier.PAID_PLAN_REQUIRED:
        return Verdict.BUILDABLE_PAID
    return Verdict.BUILDABLE_NOW


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DisagreementClass(str, Enum):
    """Not every gold-set mismatch is an agent error. METHODOLOGY §2."""

    AGENT_WRONG = "agent_wrong"
    GOLD_WRONG = "gold_wrong"
    BOTH_DEFENSIBLE = "both_defensible"
    STALE = "stale"


# --------------------------------------------------------------------------
# Field blocks
#
# Every judgment block carries its OWN evidence_url and confidence. This is
# what makes field-level grading possible -- and field-level is the only
# grading that produces a useful signal. One wrong `breadth` should not zero
# out an otherwise perfect row.
# --------------------------------------------------------------------------

class EvidencedBlock(BaseModel):
    evidence_url: str | None = None
    evidence_quote: str | None = Field(
        default=None,
        description=(
            "Short excerpt from the fetched page supporting the claim. Pass 2 "
            "checks this text actually appears on the page -- confirming the "
            "URL merely resolves is not verification."
        ),
    )
    confidence: Confidence = Confidence.LOW
    notes: str | None = None

    @field_validator("evidence_url")
    @classmethod
    def _no_invented_urls(cls, v: str | None) -> str | None:
        """A null URL is an honest answer. A plausible-looking invented docs
        path is the single most expensive failure mode in this pipeline."""
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"evidence_url must be absolute, got: {v!r}")
        return v


class AuthBlock(EvidencedBlock):
    methods: list[AuthMethod] = Field(
        default_factory=lambda: [AuthMethod.UNKNOWN],
        description=(
            "Multi-label by design. Many apps offer an API key for "
            "server-to-server AND OAuth for third-party apps; forcing a single "
            "label is where accuracy silently dies."
        ),
    )
    primary_for_third_party: AuthMethod = AuthMethod.UNKNOWN

    @model_validator(mode="after")
    def _primary_within_methods(self) -> AuthBlock:
        if (
            self.primary_for_third_party != AuthMethod.UNKNOWN
            and self.methods
            and AuthMethod.UNKNOWN not in self.methods
            and self.primary_for_third_party not in self.methods
        ):
            raise ValueError(
                f"primary_for_third_party={self.primary_for_third_party.value} "
                f"not in methods={[m.value for m in self.methods]}"
            )
        return self


class AccessBlock(EvidencedBlock):
    tier: AccessTier = AccessTier.NO_PUBLIC_API
    extra_gate: ExtraGate = ExtraGate.UNKNOWN


class ApiBlock(EvidencedBlock):
    protocols: list[Protocol] = Field(default_factory=lambda: [Protocol.NONE])
    breadth: Breadth = Breadth.UNKNOWN
    endpoint_count: int | None = Field(
        default=None,
        description="Counted from the docs reference index where available.",
    )
    mcp: McpStatus = McpStatus.UNKNOWN
    mcp_url: str | None = None
    docs_root: str | None = None


class VerdictBlock(EvidencedBlock):
    value: Verdict = Verdict.NOT_BUILDABLE
    blocker: ExtraGate | Literal["none", "no_api", "paid_only", "local_only", "approval", "partnership"] = "none"
    rationale: str | None = None
    model_verdict: Verdict | None = Field(
        default=None,
        description="What the model itself said, kept for the record. The "
                    "graded `value` is always re-derived from tier + gate.",
    )


class Provenance(BaseModel):
    pass_number: int = 1
    escalated_fields: list[str] = Field(default_factory=list)
    human_touched: bool = False
    human_reason: str | None = None
    fetched_urls: list[str] = Field(default_factory=list)
    run_id: str | None = None
    timestamp: str | None = None


# --------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------

class AppRecord(BaseModel):
    app: str
    category: str
    website: str | None = None
    one_liner: str | None = None

    auth: AuthBlock = Field(default_factory=AuthBlock)
    access: AccessBlock = Field(default_factory=AccessBlock)
    api: ApiBlock = Field(default_factory=ApiBlock)
    verdict: VerdictBlock = Field(default_factory=VerdictBlock)

    provenance: Provenance = Field(default_factory=Provenance)

    @model_validator(mode="after")
    def _cross_field_consistency(self) -> AppRecord:
        """Contradictions that should never survive into the output.

        Caught here rather than in triggers.py because these are structurally
        impossible, not merely suspicious.
        """
        if self.access.tier == AccessTier.NO_PUBLIC_API:
            live = [p for p in self.api.protocols if p not in LOCAL_PROTOCOLS]
            if live:
                raise ValueError(
                    f"{self.app}: tier=no_public_api but protocols="
                    f"{[p.value for p in live]}"
                )
            if self.verdict.value in (Verdict.BUILDABLE_NOW, Verdict.BUILDABLE_PAID,
                                      Verdict.NEEDS_OUTREACH):
                raise ValueError(
                    f"{self.app}: tier=no_public_api but verdict="
                    f"{self.verdict.value}"
                )
        return self

    def rederive_verdict(self) -> AppRecord:
        """Recompute verdict.value from tier + gate. Call after any change."""
        if self.verdict.model_verdict is None:
            self.verdict.model_verdict = self.verdict.value
        self.verdict.value = derive_verdict(
            self.access.tier, self.access.extra_gate, self.api.protocols)
        return self


# Fields graded against the gold set. 7 fields x 20 apps = 140 judgments.
GRADED_FIELDS: tuple[str, ...] = (
    "auth.methods",
    "auth.primary_for_third_party",
    "access.tier",
    "access.extra_gate",
    "api.breadth",
    "api.mcp",
    "verdict.value",
)


def get_field(record: AppRecord | dict, dotted: str):
    """Read a dotted field path off a record or plain dict."""
    cur = record
    for part in dotted.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else getattr(cur, part)
        if cur is None:
            return None
    if isinstance(cur, list):
        return [c.value if isinstance(c, Enum) else c for c in cur]
    return cur.value if isinstance(cur, Enum) else cur
