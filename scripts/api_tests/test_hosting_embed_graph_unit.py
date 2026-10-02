#!/usr/bin/env python3
# contract-test-file: tooling
"""Offline invariants for the private Hosting parent/child graph probe."""

from __future__ import annotations

import unittest

from test_hosting_embed_graph import _validate_parent
from test_hosting_requirements import ProbeFailure


def _fixture():
    children = {
        "checked-available": {
            "appId": "hosting", "skillId": "hosting_domain", "type": "hosting_domain",
            "content": {
                "type": "hosting_domain", "app_id": "hosting", "skill_id": "search_domains",
                "domain_ascii": "meet-there.com", "domain_unicode": "meet-there.com",
                "availability": "available", "provider": "Gandi", "checked_at": "2026-10-01T12:00:00Z",
                "country": "DE", "currency": "EUR",
                "registration_tiers": [{"unit": "year", "duration_range": {"minimum": 1, "maximum": 1},
                                        "price_including_tax": 13.09}],
                "renewal_tiers": [{"unit": "year", "duration_range": {"minimum": 1, "maximum": 9},
                                   "price_including_tax": 38.06}],
            },
        },
        "checked-unknown": {
            "appId": "hosting", "skillId": "hosting_domain", "type": "hosting_domain",
            "content": {
                "type": "hosting_domain", "app_id": "hosting", "skill_id": "search_domains",
                "domain_ascii": "meet-there.net", "domain_unicode": "meet-there.net",
                "availability": "unknown", "provider": "Gandi", "checked_at": "2026-10-01T12:00:00Z",
                "country": "DE", "currency": "EUR", "registration_tiers": [], "renewal_tiers": [],
            },
        },
    }
    parent = {
        "appId": "hosting", "skillId": "search_domains", "type": "app_skill_use",
        "embedId": "search-parent",
        "content": {
            "app_id": "hosting", "skill_id": "search_domains", "provider": "Gandi",
            "query": "meet-there", "country": "DE", "currency": "EUR",
            "status": "finished", "checked_at": "2026-10-01T12:00:00Z",
            "availability": "prefer_available", "max_results": 1,
            "embed_ids": ["checked-available", "checked-unknown"],
            "selected_embed_ids": ["checked-available"], "result_count": 1,
            "checked_count": 2, "available_count": 1, "unavailable_count": 0,
            "unknown_count": 1, "partial": True, "warnings": ["one check was inconclusive"],
            "preview_starting_registration": {"amount": 13.09, "currency": "EUR",
                                              "tax_basis": "including", "unit": "year", "duration": 1},
        },
    }
    return parent, children


class HostingEmbedGraphTests(unittest.TestCase):
    def test_checked_unknown_remains_a_child_but_not_selected(self):
        parent, children = _fixture()
        receipt = _validate_parent(parent, children.__getitem__)
        self.assertEqual(receipt["checked_embed_ids"], ["checked-available", "checked-unknown"])
        self.assertEqual(receipt["selected_embed_ids"], ["checked-available"])
        self.assertEqual(receipt["availability_counts"], {"available": 1, "unavailable": 0, "unknown": 1})

    def test_rejects_unknown_selected_or_missing_child_reference(self):
        parent, children = _fixture()
        parent["content"]["selected_embed_ids"] = ["checked-unknown"]
        with self.assertRaises(ProbeFailure):
            _validate_parent(parent, children.__getitem__)
        parent["content"]["selected_embed_ids"] = ["missing-child"]
        with self.assertRaises(ProbeFailure):
            _validate_parent(parent, children.__getitem__)

    def test_rejects_status_count_drift(self):
        parent, children = _fixture()
        parent["content"]["unavailable_count"] = 1
        parent["content"]["unknown_count"] = 0
        with self.assertRaises(ProbeFailure):
            _validate_parent(parent, children.__getitem__)


if __name__ == "__main__":
    unittest.main()
