"""Explicit expense intent must survive canonical serialization without defaults."""
from dataclasses import replace
from datetime import date, datetime
import unittest
from uuid import UUID, uuid4

from omnixat_core.evidence_csv import AmountCell
from omnixat_core.expense_context import ExpenseDraftContext
from omnixat_core.job_tasks import ExpensePreparationPlan


class ExpensePreparationPlanTests(unittest.TestCase):
    def setUp(self):
        self.plan = ExpensePreparationPlan(AmountCell('gross',1,2),
            ExpenseDraftContext('GBP',date(2026,11,7),uuid4()),uuid4())

    def test_explicit_plan_round_trips_and_rejects_implicit_or_unsupported_inputs(self):
        self.assertEqual(ExpensePreparationPlan.from_payload(self.plan.payload()),self.plan)
        for context in [replace(self.plan.context,currency='USD'),
                        replace(self.plan.context,accounting_date=datetime(2026,11,7)),
                        replace(self.plan.context,expense_account_id=UUID(int=0))]:
            with self.subTest(context=context),self.assertRaises(ValueError):
                replace(self.plan,context=context)
        for field,value in [('period_id',UUID(int=0)),('source_cell',AmountCell('gross',True,2))]:
            with self.assertRaises(ValueError):
                replace(self.plan,**{field:value})
        for payload in [dict(self.plan.payload(),accounting_date='20261107'),
                        dict(self.plan.payload(),amount='12.34'),
                        dict(self.plan.payload(),period_id=None)]:
            with self.assertRaises(ValueError):
                ExpensePreparationPlan.from_payload(payload)
