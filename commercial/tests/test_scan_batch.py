import unittest
from uuid import uuid4
from omnixat_core.scan_batch import validate_evidence_batch


class ScanBatchTests(unittest.TestCase):
    def test_bounded_ordered_snapshot(self):
        items=[str(uuid4()) for _ in range(5)]
        result=validate_evidence_batch(items)
        items.clear()
        self.assertEqual(len(result),5)

    def test_invalid_or_oversized_manifest(self):
        for items in [[],None,{},'id',[str(uuid4())]*6,[42],['bad'],[str(uuid4()).upper()]]:
            with self.subTest(items=items),self.assertRaises(ValueError): validate_evidence_batch(items)

    def test_duplicates_rejected(self):
        item=str(uuid4())
        with self.assertRaises(ValueError): validate_evidence_batch([item,item])
