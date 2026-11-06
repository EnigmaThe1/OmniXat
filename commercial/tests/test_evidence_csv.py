from decimal import Decimal
import unittest

from omnixat_core.evidence_csv import AmountCell, EvidenceCSVError, read_csv_amounts


class EvidenceCSVTests(unittest.TestCase):
    def test_preserves_exact_amounts_and_one_based_logical_coordinates(self):
        cells = (AmountCell("gross", 3, 2), AmountCell("net", 2, 2))
        original = b'\xef\xbb\xbflabel,amount\r\n"Fictional\r\nitem",-012.3400\r\nTotal,+0.00\r\n'
        gross, net = read_csv_amounts(original, cells)
        self.assertEqual((gross.cell, net.cell), cells)
        self.assertEqual((gross.status, net.status), ("found", "found"))
        self.assertEqual(gross.amount.as_tuple(), Decimal("0.00").as_tuple())
        self.assertEqual(net.amount.as_tuple(), Decimal("-12.3400").as_tuple())

    def test_blank_missing_ambiguous_and_zero_are_distinct(self):
        data = b'0, ,"1,234.50",1e2,GBP 2,NaN,1.1234567\n'
        selections = tuple(AmountCell(f"field_{i}", 1, i) for i in range(1, 9))
        values = read_csv_amounts(data, selections)
        self.assertEqual([v.status for v in values], [
            "found", "blank", "ambiguous", "ambiguous", "ambiguous", "ambiguous", "ambiguous", "missing",
        ])
        self.assertEqual(values[0].amount, Decimal(0))
        self.assertTrue(all(value.amount is None for value in values[1:]))

    def test_rejects_bad_encoding_malformed_csv_and_oversized_input(self):
        selection = (AmountCell("net", 1, 1),)
        for data in (
            b"\xff", b'"unfinished', b"1\x00", b"", b"0" * (512 * 1024 + 1),
            b"1\n" * 5001, b"1," * 64 + b"1\n", b"1" * 4097,
        ):
            with self.subTest(size=len(data)), self.assertRaises(EvidenceCSVError):
                read_csv_amounts(data, selection)

    def test_rejects_unsafe_or_duplicate_plan(self):
        valid = AmountCell("net", 1, 1)
        for plan in (
            (), (valid, valid), (AmountCell("bad field", 1, 1),),
            (AmountCell("net", True, 1),), (AmountCell("net", 1, 65),), (valid,) * 33,
        ):
            with self.subTest(size=len(plan)), self.assertRaises(EvidenceCSVError):
                read_csv_amounts(b"1\n", plan)
