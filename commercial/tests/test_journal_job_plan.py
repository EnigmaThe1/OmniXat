"""Intent must be explicit and canonical; an amount/approval is never an input."""
from dataclasses import FrozenInstanceError, replace
import unittest
from uuid import UUID, uuid4

from omnixat_core.job_tasks import JournalPreparationPlan


class JournalPreparationPlanTests(unittest.TestCase):
    def test_explicit_funding_references_round_trip_without_guessed_defaults(self):
        plan = JournalPreparationPlan(uuid4(),uuid4(),'personal_funds',uuid4())
        self.assertEqual(JournalPreparationPlan.from_payload(plan.payload()),plan)
        self.assertNotIn(str(plan.payer_id),repr(plan))
        with self.assertRaises(FrozenInstanceError):
            plan.funding_kind = 'business_funds'
        for key in ['funding_source_id','payer_id','counterpart_account_id']:
            for invalid in [UUID(int=0),str(uuid4()),None]:
                with self.subTest(key=key),self.assertRaises(ValueError):
                    replace(plan,**{key:invalid})
        for invalid in ['unknown','PERSONAL_FUNDS',None,True]:
            with self.assertRaises(ValueError):
                replace(plan,funding_kind=invalid)
        payload = plan.payload()
        for invalid in [dict(payload,amount='12.34'),dict(payload,approved=True),
                        dict(payload,payer_id=plan.payer_id),dict(payload,funding_source_id=plan.funding_source_id.hex),
                        {k:v for k,v in payload.items() if k!='funding_kind'}]:
            with self.assertRaises(ValueError):
                JournalPreparationPlan.from_payload(invalid)
