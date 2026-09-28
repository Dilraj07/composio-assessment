"""Escalation rules: which fields get a second look in pass 2.

Not everything is re-verified. Targeted escalation is both cheaper and a more
honest demonstration than blanket re-running -- it shows the pipeline knows
where it is weak.

The rules encode one deliberate asymmetry (RULE 5): a false `buildable_now`
costs a wasted engineering sprint, a false `needs_outreach` costs an email.
The expensive direction is verified harder, regardless of confidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .fetch import claim_supported, is_first_party
from .schema import (
    GRADED_FIELDS,
    AccessTier,
    AppRecord,
    Confidence,
    ExtraGate,
    Protocol,
    Verdict,
    get_field,
)


@dataclass
class Trigger:
    app: str
    field: str
    rule: str
    detail: str


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

def _block_for(record: AppRecord, dotted: str):
    return getattr(record, dotted.split(".")[0])


def rule_low_confidence(record: AppRecord) -> list[Trigger]:
    """RULE 1 -- anything the pass-1 model was not sure about."""
    out = []
    for f in GRADED_FIELDS:
        block = _block_for(record, f)
        if block.confidence != Confidence.HIGH:
            out.append(Trigger(record.app, f, "low_confidence",
                               f"confidence={block.confidence.value}"))
    return out


def rule_third_party_evidence(record: AppRecord) -> list[Trigger]:
    """RULE 2 -- evidence not on the vendor's own domain.

    A half-remembered blog post cited as evidence will resolve fine and read
    plausibly. First-party docs are the standard; anything else is suspect.
    """
    out = []
    for f in GRADED_FIELDS:
        block = _block_for(record, f)
        if block.evidence_url and not is_first_party(block.evidence_url, record.website):
            out.append(Trigger(record.app, f, "third_party_evidence",
                               f"evidence off-domain: {block.evidence_url}"))
    return out


def rule_unverifiable_evidence(record: AppRecord, pages: dict | None = None) -> list[Trigger]:
    """RULE 3 -- URL missing, dead, or the claim is not on the page.

    `pages` maps url -> Page from the pass-1 fetch cache. Checking the claim
    text appears is the point: a 200 response proves the path exists, not that
    it says what the model claimed.
    """
    out = []
    for f in GRADED_FIELDS:
        block = _block_for(record, f)
        if not block.evidence_url:
            out.append(Trigger(record.app, f, "no_evidence", "evidence_url is null"))
            continue
        if pages is None:
            continue
        page = pages.get(block.evidence_url)
        if page is None or not page.ok:
            out.append(Trigger(record.app, f, "dead_evidence",
                               f"fetch failed: {block.evidence_url}"))
        elif not claim_supported(page, block.evidence_quote):
            out.append(Trigger(record.app, f, "claim_not_on_page",
                               "cited text not found in fetched page"))
    return out


def rule_selfserve_unknown_gate(record: AppRecord) -> list[Trigger]:
    """RULE 4 -- self-serve tier with an undetermined extra gate.

    The single most likely false positive in the whole schema. Google Ads,
    WhatsApp Business, Amazon SP-API and LinkedIn Ads all look self-serve at
    the credential step and are not usable in production without a further
    approval. If the gate is unknown, the buildability verdict is unsafe.
    """
    if (
        record.access.tier in (AccessTier.SELF_SERVE_FREE, AccessTier.SELF_SERVE_TRIAL)
        and record.access.extra_gate == ExtraGate.UNKNOWN
    ):
        return [Trigger(record.app, "access.extra_gate", "selfserve_unknown_gate",
                        f"tier={record.access.tier.value} with undetermined gate")]
    return []


def rule_verify_all_buildable(record: AppRecord) -> list[Trigger]:
    """RULE 5 -- every `buildable_now` verdict, even at high confidence.

    Deliberate asymmetry. False positives here are the expensive error; false
    negatives cost an outreach email. Verify the direction that hurts.
    """
    if record.verdict.value == Verdict.BUILDABLE_NOW:
        return [Trigger(record.app, "verdict.value", "buildable_always_verified",
                        "buildable_now is always re-verified (asymmetric cost)")]
    return []


def rule_contradictions(record: AppRecord) -> list[Trigger]:
    """RULE 6 -- internally inconsistent records.

    schema.py rejects the structurally impossible cases at validation time.
    These are the softer contradictions: coherent enough to parse, wrong
    enough to distrust.
    """
    out = []
    live = [p for p in record.api.protocols if p != Protocol.NONE]

    if record.verdict.value == Verdict.BUILDABLE_NOW and record.access.extra_gate not in (
        ExtraGate.NONE, ExtraGate.UNKNOWN
    ):
        out.append(Trigger(record.app, "verdict.value", "contradiction",
                           f"buildable_now despite extra_gate="
                           f"{record.access.extra_gate.value}"))

    if record.verdict.value == Verdict.BUILDABLE_NOW and record.access.tier in (
        AccessTier.PAID_PLAN_REQUIRED, AccessTier.PARTNER_GATED,
        AccessTier.APPROVAL_REQUIRED,
    ):
        out.append(Trigger(record.app, "verdict.value", "contradiction",
                           f"buildable_now despite tier={record.access.tier.value}"))

    if not live and record.verdict.value in (Verdict.BUILDABLE_NOW, Verdict.BUILDABLE_PAID):
        out.append(Trigger(record.app, "api.protocols", "contradiction",
                           "no live protocols but verdict claims buildable"))

    if record.api.endpoint_count is not None:
        n, b = record.api.endpoint_count, record.api.breadth.value
        expected = "narrow" if n < 25 else ("moderate" if n <= 100 else "broad")
        if b != "unknown" and b != expected:
            out.append(Trigger(record.app, "api.breadth", "contradiction",
                               f"endpoint_count={n} implies {expected}, got {b}"))
    return out


ALL_RULES = (
    rule_low_confidence,
    rule_third_party_evidence,
    rule_selfserve_unknown_gate,
    rule_verify_all_buildable,
    rule_contradictions,
)


def triage(record: AppRecord, pages: dict | None = None) -> list[Trigger]:
    """All triggers for one record, deduplicated by (field, rule)."""
    hits: list[Trigger] = []
    for rule in ALL_RULES:
        hits.extend(rule(record))
    hits.extend(rule_unverifiable_evidence(record, pages))

    seen, unique = set(), []
    for t in hits:
        key = (t.field, t.rule)
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique


def triage_all(records: list[AppRecord], pages: dict | None = None) -> dict:
    """Triage the full set and summarise.

    Escalation rate is a calibration signal: below ~20% the rules are too
    lax to be doing real work, above ~80% pass 2 is just pass 1 again and the
    accuracy delta will not be meaningful.
    """
    per_app, counts = {}, {}
    escalated_fields = 0  # DISTINCT fields, not (field, rule) pairs -- one
                          # field can trip several rules at once, and counting
                          # pairs pushes the rate above 100%.
    for rec in records:
        hits = triage(rec, pages)
        if hits:
            per_app[rec.app] = [asdict(h) for h in hits]
            escalated_fields += len({h.field for h in hits})
        for h in hits:
            counts[h.rule] = counts.get(h.rule, 0) + 1

    total_fields = len(records) * len(GRADED_FIELDS)
    return {
        "apps_total": len(records),
        "apps_with_triggers": len(per_app),
        "fields_total": total_fields,
        "fields_escalated": escalated_fields,
        "trigger_hits": sum(len(v) for v in per_app.values()),
        "escalation_rate": round(escalated_fields / total_fields, 3) if total_fields else 0.0,
        "by_rule": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "per_app": per_app,
    }
