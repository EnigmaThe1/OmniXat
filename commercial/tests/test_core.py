from datetime import date, datetime, timezone
from decimal import Decimal
from dataclasses import FrozenInstanceError
import unittest

from omnixat_core.access import Principal, require_staff, require_tenant
from omnixat_core.filings import approve, approval_matches
from omnixat_core.pricing import PriceCatalogue
from omnixat_core.rules import (catalogue, mtd_it_screen, mtd_it_threshold,
    mtd_standard_updates, micro_size_thresholds, revised_accounts_requirements,
    ordinary_private_company_deadlines, small_company_ct_payment, sa_deadlines)


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.owner = Principal("alice", "tenant-a", "owner", mfa_verified=True)

    def test_owner_cannot_cross_tenants(self):
        with self.assertRaises(PermissionError):
            require_tenant(self.owner, "tenant-b", "records:read")

    def test_staff_is_not_a_customer_data_bypass(self):
        staff = Principal("staff", None, staff_role="platform_owner", mfa_verified=True)
        with self.assertRaises(PermissionError):
            require_tenant(staff, "tenant-a", "records:read")

    def test_viewer_cannot_write(self):
        with self.assertRaises(PermissionError):
            require_tenant(Principal("bob", "tenant-a", "viewer"), "tenant-a", "records:write")

    def test_customer_cannot_change_platform_prices(self):
        with self.assertRaises(PermissionError):
            require_staff(self.owner, "prices:write")

    def test_api_scopes_intersect_membership(self):
        api = Principal("alice", "tenant-a", "owner", api_scopes=frozenset({"records:read"}))
        require_tenant(api, "tenant-a", "records:read")
        with self.assertRaises(PermissionError):
            require_tenant(api, "tenant-a", "records:write")

    def test_api_cannot_access_staff_even_if_roles_are_present(self):
        api = Principal("staff", None, staff_role="platform_owner", mfa_verified=True, api_scopes=frozenset())
        with self.assertRaises(PermissionError):
            require_staff(api, "prices:write")


class PricingTests(unittest.TestCase):
    def setUp(self):
        self.actor = Principal("staff", None, staff_role="billing_admin", mfa_verified=True)
        self.catalogue = PriceCatalogue()

    def create(self, amount=1200):
        return self.catalogue.create(self.actor, plan="Starter", amount_minor=amount,
            interval="month", trial_days=14, api_allowance=500,
            effective_at=datetime(2027, 1, 1, tzinfo=timezone.utc))

    def test_price_change_creates_new_version_preserves_existing_reference(self):
        old = self.create()
        subscription_price_id = old.id
        new = self.create(1500)
        self.assertNotEqual(old.id, new.id)
        self.assertEqual(self.catalogue.get(subscription_price_id).amount_minor, 1200)
        self.assertEqual(len(self.catalogue.audit), 2)

    def test_price_record_is_immutable(self):
        old = self.create()
        with self.assertRaises(FrozenInstanceError):
            old.amount_minor = 999

    def test_float_and_boolean_money_refused(self):
        for amount in (12.00, True, -1):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.create(amount)

    def test_staff_price_change_requires_mfa(self):
        self.actor = Principal("staff", None, staff_role="billing_admin")
        with self.assertRaises(PermissionError):
            self.create()


class FilingTests(unittest.TestCase):
    def setUp(self):
        self.actor = Principal("alice", "tenant-a", "owner", mfa_verified=True)

    def test_changed_artifact_invalidates_approval(self):
        approval = approve(self.actor, "tenant-a", b"reviewed", destination="hmrc", environment="sandbox")
        self.assertTrue(approval_matches(approval, "tenant-a", b"reviewed", destination="hmrc", environment="sandbox"))
        self.assertFalse(approval_matches(approval, "tenant-a", b"changed", destination="hmrc", environment="sandbox"))

    def test_destination_environment_and_tenant_cannot_be_reused(self):
        approval = approve(self.actor, "tenant-a", b"reviewed", destination="hmrc", environment="sandbox")
        for tenant, destination, environment in (("tenant-b", "hmrc", "sandbox"),
                ("tenant-a", "companies_house", "sandbox"), ("tenant-a", "hmrc", "live")):
            self.assertFalse(approval_matches(approval, tenant, b"reviewed", destination=destination, environment=environment))

    def test_approval_requires_step_up(self):
        with self.assertRaises(PermissionError):
            approve(Principal("alice", "tenant-a", "owner"), "tenant-a", b"x", destination="hmrc", environment="live")

    def test_agent_cannot_approve_even_with_owner_role_mfa_and_scope(self):
        agent = Principal("agent-1", "tenant-a", "owner", mfa_verified=True,
            api_scopes=frozenset({"filings:approve", "records:write"}), actor_kind="agent")
        require_tenant(agent, "tenant-a", "records:write")
        with self.assertRaises(PermissionError):
            approve(agent, "tenant-a", b"x", destination="hmrc", environment="live")

    def test_api_key_cannot_replace_interactive_human_review(self):
        api = Principal("alice", "tenant-a", "owner", mfa_verified=True,
                        api_scopes=frozenset({"filings:approve"}))
        with self.assertRaises(PermissionError):
            approve(api, "tenant-a", b"x", destination="companies_house", environment="live")

    def test_agent_cannot_escalate_membership_or_use_staff_powers(self):
        agent = Principal("agent-1", "tenant-a", "owner", staff_role="platform_owner",
                          mfa_verified=True, actor_kind="agent")
        with self.assertRaises(PermissionError):
            require_tenant(agent, "tenant-a", "members:manage")
        with self.assertRaises(PermissionError):
            require_staff(agent, "prices:write")


class RulesTests(unittest.TestCase):
    def test_mtd_rollout_uses_reference_income_year(self):
        self.assertEqual(mtd_it_threshold(2026), (2024, Decimal("50000")))
        self.assertEqual(mtd_it_threshold(2027), (2025, Decimal("30000")))
        self.assertEqual(mtd_it_threshold(2028), (2026, Decimal("20000")))

    def test_mtd_threshold_is_strict_and_not_complete_eligibility(self):
        self.assertEqual(mtd_it_screen(2026, Decimal("50000"), exemption=False), "threshold_not_exceeded_check_existing_mandation")
        self.assertEqual(mtd_it_screen(2026, Decimal("50000.01"), exemption=None), "exemption_review_required")
        self.assertEqual(mtd_it_screen(2026, Decimal("50001"), exemption=True), "exempt_on_supplied_facts")
        self.assertEqual(mtd_it_screen(2026, Decimal("50001"), exemption=False), "threshold_exceeded_verify_remaining_conditions")

    def test_invalid_income_and_unresearched_years(self):
        for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-1"), 50000.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                mtd_it_screen(2026, value, exemption=False)
        self.assertEqual(mtd_it_screen(2030, Decimal("999999"), exemption=False), "outside_researched_years")

    def test_mtd_updates_are_cumulative(self):
        quarters = mtd_standard_updates(2026)
        self.assertEqual({q["start"] for q in quarters}, {date(2026, 4, 6)})
        self.assertEqual(quarters[1]["end"], date(2026, 10, 5))
        self.assertEqual(quarters[1]["due"], date(2026, 11, 7))
        self.assertEqual(quarters[-1]["due"], date(2027, 5, 7))

    def test_company_size_uses_period_start_not_filing_date(self):
        self.assertEqual(micro_size_thresholds(date(2025, 4, 5))["turnover"], Decimal("632000"))
        self.assertEqual(micro_size_thresholds(date(2025, 4, 6))["turnover"], Decimal("1000000"))

    def test_deadline_month_end_and_payment_separation(self):
        accounts, ct = ordinary_private_company_deadlines(date(2026, 5, 31), confirmed_ordinary=True)
        self.assertEqual(accounts.due, date(2027, 2, 28))
        self.assertEqual(ct.due, date(2027, 5, 31))
        self.assertEqual(small_company_ct_payment(date(2026, 5, 31), instalments_excluded=True).due, date(2027, 3, 1))

    def test_special_periods_require_review(self):
        with self.assertRaises(ValueError):
            ordinary_private_company_deadlines(date(2026, 2, 28), confirmed_ordinary=False)
        with self.assertRaises(ValueError):
            small_company_ct_payment(date(2026, 2, 28), instalments_excluded=False)

    def test_self_assessment_year_boundary(self):
        paper, online = sa_deadlines(2025)
        self.assertEqual(paper.due, date(2026, 10, 31))
        self.assertEqual(online.due, date(2027, 1, 31))

    def revision(self, **overrides):
        values = dict(original_start=date(2023, 2, 8), original_end=date(2024, 2, 29),
            replacement_start=date(2023, 2, 8), replacement_end=date(2024, 2, 29),
            original_approval=date(2024, 6, 6), revision_approval=date(2026, 11, 5),
            has_profit_loss=True, has_revision_statements=True)
        return revised_accounts_requirements(**(values | overrides))

    def test_revised_document_requires_visible_profit_loss(self):
        self.assertEqual(self.revision(), ())
        self.assertIn("replacement_profit_loss_required", self.revision(has_profit_loss=False))

    def test_revision_does_not_fabricate_approval_or_change_period(self):
        self.assertIn("actual_revision_approval_required", self.revision(revision_approval=None))
        self.assertIn("original_period_must_be_preserved", self.revision(replacement_end=date(2026, 2, 28)))

    def test_every_catalogue_rule_has_source_date_and_explicit_support(self):
        data = catalogue()
        ids = [r["id"] for r in data["rules"]]
        self.assertEqual(len(ids), len(set(ids)))
        for rule in data["rules"]:
            self.assertTrue(rule["sources"])
            self.assertEqual(rule["checked_on"], "2026-11-05")
            self.assertFalse(rule["live_filing_enabled"])
            self.assertIn(rule["implementation"], ("bounded_function", "research_only"))


if __name__ == "__main__":
    unittest.main()
