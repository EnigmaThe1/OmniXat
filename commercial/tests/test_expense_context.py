from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, localcontext
import unittest
from uuid import uuid4

from omnixat_core.expense_context import (
    ExpenseDraftContext, ExpenseDraftPolicy, expense_pence, validate_expense_context,
)


class ExpenseContextTests(unittest.TestCase):
    def setUp(self):
        self.tenant, self.org, self.account = uuid4(), uuid4(), uuid4()
        self.start, self.end = date(2026, 1, 1), date(2026, 12, 31)
        self.context = ExpenseDraftContext("GBP", self.start, self.account)
        self.policy = ExpenseDraftPolicy(self.tenant, self.org, self.start, self.end, frozenset({self.account}))

    def test_validates_explicit_scope_date_currency_and_account(self):
        for accounting_date in (self.start, self.end):
            validate_expense_context(self.tenant, self.org, replace(self.context, accounting_date=accounting_date),
                                     self.policy)
        for changes in ({"currency": "EUR"}, {"currency": ""}, {"expense_account_id": uuid4()},
                        {"accounting_date": date(2027, 1, 1)}, {"accounting_date": datetime(2026, 1, 1)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_expense_context(self.tenant, self.org, replace(self.context, **changes), self.policy)
        with self.assertRaises(PermissionError):
            validate_expense_context(self.tenant, uuid4(), self.context, self.policy)
        with self.assertRaises(ValueError):
            validate_expense_context(self.tenant, self.org, self.context, replace(self.policy, period_end=date(2025, 1, 1)))

    def test_pence_conversion_never_rounds_under_low_decimal_precision(self):
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(expense_pence(Decimal("999999999999999999.990000")), 99999999999999999999)
            self.assertEqual(expense_pence(Decimal("0.0100")), 1)
            for amount in ("0", "-1.00", "0.001", "12.340001", "NaN", "Infinity", "1e18"):
                with self.subTest(amount=amount), self.assertRaises(ValueError):
                    expense_pence(Decimal(amount))
