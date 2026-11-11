import unittest
from uuid import uuid4
from omnixat_core.csv_extraction_plan import validate_extraction_plan, validate_extraction_batch
from omnixat_core.evidence_csv import AmountCell


class CSVExtractionPlanTests(unittest.TestCase):
    def plan(self):
        return {key:str(uuid4()) for key in ['tenant','organisation','evidence','job']} | {
            'selections':[{'field_name':'amount','row':2,'column':2}]}

    def test_scope_order_and_shared_cells(self):
        plan=self.plan(); value=validate_extraction_plan(plan)
        self.assertEqual(value[:4],tuple(plan[k] for k in ['tenant','organisation','evidence','job']))
        self.assertEqual(value[4],(AmountCell('amount',2,2),))
        plan['selections'][0]['row']=4
        self.assertEqual(value[4][0].row,2)

    def test_unknown_missing_and_noncanonical_identifiers(self):
        for change in [{'tenant':'bad'},{'job':None},{'scanner':'chosen'}]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_extraction_plan(self.plan()|change)
        plan=self.plan(); del plan['evidence']
        with self.assertRaises(ValueError): validate_extraction_plan(plan)

    def test_strict_coordinate_schema_and_bounds(self):
        for cell in [{'field_name':'amount','row':True,'column':2},
                     {'field_name':'amount','row':0,'column':2},
                     {'field_name':'amount','row':5001,'column':2},
                     {'field_name':'amount','row':2,'column':65},
                     {'field_name':'amount','row':2,'column':2,'amount':'invented'}]:
            plan=self.plan(); plan['selections']=[cell]
            with self.subTest(cell=cell),self.assertRaises(ValueError): validate_extraction_plan(plan)

    def test_empty_oversized_and_duplicate_fields(self):
        for count in [0,2,33]:
            plan=self.plan(); plan['selections']*=count
            with self.subTest(count=count),self.assertRaises(ValueError): validate_extraction_plan(plan)

    def test_batch_bounds_scope_jobs_and_complete_snapshot(self):
        first=self.plan()
        second=first|{'job':str(uuid4())}
        for plans in [None,{},[],[first]*6,[first,first],
                      [first,second|{'tenant':str(uuid4())}],
                      [first,second|{'organisation':str(uuid4())}],
                      [first,second|{'selections':[]}]]:
            with self.subTest(plans=plans),self.assertRaises(ValueError):
                validate_extraction_batch(plans)
        plans=[first|{'job':str(uuid4())} for _ in range(5)]
        result=validate_extraction_batch(plans)
        self.assertEqual(len(result),5)
        self.assertEqual([plan[3] for plan in result],[plan['job'] for plan in plans])
        first['selections'][0]['row']=4
        self.assertTrue(all(plan[4][0].row==2 for plan in result))
