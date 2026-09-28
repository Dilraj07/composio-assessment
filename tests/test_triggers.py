"""Tests for the escalation rules.

Trigger logic is the part most likely to be quietly wrong -- a rule that never
fires leaves the accuracy delta flat and nobody notices until the interview.
"""

from __future__ import annotations

import pytest

from src.schema import AppRecord, Confidence
from src.triggers import (
    rule_contradictions,
    rule_low_confidence,
    rule_selfserve_unknown_gate,
    rule_third_party_evidence,
    rule_verify_all_buildable,
    triage,
    triage_all,
)


def make(**over) -> AppRecord:
    base = {
        "app": "TestApp",
        "category": "Test",
        "website": "testapp.com",
        "auth": {"methods": ["oauth2"], "primary_for_third_party": "oauth2",
                 "evidence_url": "https://testapp.com/docs/auth",
                 "evidence_quote": "OAuth 2.0", "confidence": "high"},
        "access": {"tier": "self_serve_free", "extra_gate": "none",
                   "evidence_url": "https://testapp.com/pricing", "confidence": "high"},
        "api": {"protocols": ["rest"], "breadth": "moderate", "mcp": "none",
                "evidence_url": "https://testapp.com/docs", "confidence": "high"},
        "verdict": {"value": "buildable_paid", "blocker": "none",
                    "evidence_url": "https://testapp.com/docs", "confidence": "high"},
    }
    for k, v in over.items():
        if isinstance(v, dict) and k in base:
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return AppRecord.model_validate(base)


class TestRule1LowConfidence:
    def test_high_confidence_passes(self):
        assert rule_low_confidence(make()) == []

    def test_medium_escalates(self):
        hits = rule_low_confidence(make(access={"confidence": "medium"}))
        assert [h.field for h in hits] == ["access.tier", "access.extra_gate"]


class TestRule2ThirdPartyEvidence:
    def test_first_party_passes(self):
        assert rule_third_party_evidence(make()) == []

    def test_subdomain_counts_as_first_party(self):
        rec = make(auth={"evidence_url": "https://docs.testapp.com/auth"})
        assert rule_third_party_evidence(rec) == []

    def test_blog_escalates(self):
        rec = make(auth={"evidence_url": "https://medium.com/@someone/testapp-api"})
        assert any(h.field == "auth.methods" for h in rule_third_party_evidence(rec))


class TestRule4SelfServeUnknownGate:
    def test_known_gate_passes(self):
        assert rule_selfserve_unknown_gate(make()) == []

    def test_unknown_gate_on_self_serve_escalates(self):
        """The highest-value trigger: Google Ads, WhatsApp and SP-API all look
        self-serve at the credential step and are not usable without more."""
        rec = make(access={"tier": "self_serve_free", "extra_gate": "unknown"})
        hits = rule_selfserve_unknown_gate(rec)
        assert len(hits) == 1 and hits[0].field == "access.extra_gate"

    def test_unknown_gate_on_paid_tier_does_not_fire(self):
        rec = make(access={"tier": "paid_plan_required", "extra_gate": "unknown"})
        assert rule_selfserve_unknown_gate(rec) == []


class TestRule5AsymmetricVerification:
    def test_buildable_now_always_escalates_even_at_high_confidence(self):
        rec = make(verdict={"value": "buildable_now", "confidence": "high"})
        assert len(rule_verify_all_buildable(rec)) == 1

    def test_other_verdicts_do_not(self):
        assert rule_verify_all_buildable(make(verdict={"value": "needs_outreach"})) == []


class TestRule6Contradictions:
    def test_buildable_now_with_a_gate_is_contradictory(self):
        rec = make(verdict={"value": "buildable_now"},
                   access={"extra_gate": "developer_token"})
        assert any(h.rule == "contradiction" for h in rule_contradictions(rec))

    def test_buildable_now_on_partner_gated_tier(self):
        rec = make(verdict={"value": "buildable_now"}, access={"tier": "partner_gated"})
        assert any(h.rule == "contradiction" for h in rule_contradictions(rec))

    def test_endpoint_count_must_match_breadth_band(self):
        rec = make(api={"endpoint_count": 400, "breadth": "narrow"})
        hits = rule_contradictions(rec)
        assert any(h.field == "api.breadth" for h in hits)

    def test_endpoint_count_consistent_with_breadth_passes(self):
        assert rule_contradictions(make(api={"endpoint_count": 60,
                                             "breadth": "moderate"})) == []


class TestSchemaGuards:
    def test_no_public_api_cannot_have_protocols(self):
        with pytest.raises(ValueError, match="no_public_api"):
            make(access={"tier": "no_public_api"}, api={"protocols": ["rest"]})

    def test_no_public_api_cannot_be_buildable(self):
        with pytest.raises(ValueError, match="no_public_api"):
            make(access={"tier": "no_public_api"},
                 api={"protocols": ["none"]},
                 verdict={"value": "buildable_now"})

    def test_primary_auth_must_be_in_methods(self):
        with pytest.raises(ValueError, match="primary_for_third_party"):
            make(auth={"methods": ["api_key"], "primary_for_third_party": "oauth2"})

    def test_relative_evidence_url_rejected(self):
        with pytest.raises(ValueError, match="absolute"):
            make(auth={"evidence_url": "/docs/auth"})


class TestTriageAggregate:
    def test_clean_record_produces_no_triggers(self):
        assert triage(make()) == []

    def test_deduplicates_by_field_and_rule(self):
        rec = make(access={"tier": "self_serve_free", "extra_gate": "unknown",
                           "confidence": "low"})
        hits = triage(rec)
        assert len({(h.field, h.rule) for h in hits}) == len(hits)

    def test_escalation_rate_is_reported(self):
        summary = triage_all([make(), make(app="Other", verdict={"value": "buildable_now"})])
        assert summary["apps_total"] == 2
        assert 0.0 <= summary["escalation_rate"] <= 1.0
        assert "buildable_always_verified" in summary["by_rule"]


class TestDerivedVerdict:
    """verdict.value is a rule over tier + gate (METHODOLOGY §1)."""

    @pytest.mark.parametrize("tier,gate,protocols,expected", [
        ("self_serve_free", "none", ["rest"], "buildable_now"),
        ("self_serve_trial", "admin_consent", ["rest"], "buildable_now"),
        ("self_serve_free", "developer_token", ["rest"], "needs_outreach"),
        ("paid_plan_required", "none", ["rest"], "buildable_paid"),
        ("paid_plan_required", "sales_contact", ["rest"], "needs_outreach"),
        ("partner_gated", "none", ["rest"], "needs_outreach"),
        ("no_public_api", "none", ["cli"], "buildable_local"),
        ("no_public_api", "none", ["none"], "not_buildable"),
    ])
    def test_rule_table(self, tier, gate, protocols, expected):
        from src.schema import AccessTier, ExtraGate, Protocol, derive_verdict
        got = derive_verdict(AccessTier(tier), ExtraGate(gate),
                             [Protocol(p) for p in protocols])
        assert got.value == expected

    def test_rederive_keeps_model_verdict(self):
        rec = make(verdict={"value": "buildable_now"},
                   access={"tier": "paid_plan_required"}).rederive_verdict()
        assert rec.verdict.value.value == "buildable_paid"
        assert rec.verdict.model_verdict.value == "buildable_now"

    def test_cli_allowed_with_no_public_api(self):
        rec = make(access={"tier": "no_public_api"}, api={"protocols": ["cli"]},
                   verdict={"value": "buildable_local"})
        assert rec.verdict.value.value == "buildable_local"
