from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN
import unittest
from money_precision import format_money

class MoneyPrecisionTests(unittest.TestCase):
    def test_half_up(self):
        self.assertEqual(format_money('1.005', rounding=ROUND_HALF_UP), '1.01')
    def test_half_even_differs(self):
        self.assertEqual(format_money('1.005', rounding=ROUND_HALF_EVEN), '1.00')
    def test_2675_exact(self):
        self.assertEqual(format_money('2.675', rounding=ROUND_HALF_UP), '2.68')
    def test_negative(self):
        self.assertEqual(format_money('-1.005', rounding=ROUND_HALF_UP), '-1.01')
    def test_decimal_instead_of_float(self):
        self.assertEqual(format_money(Decimal('23.75'), rounding=ROUND_HALF_UP), '23.75')
    def test_float_is_rejected(self):
        with self.assertRaises(TypeError):
            format_money(1.005, rounding=ROUND_HALF_UP)
    def test_non_finite_rejected(self):
        with self.assertRaises(ValueError):
            format_money('NaN', rounding=ROUND_HALF_UP)
    def test_binary_float_precision_examples_are_not_used(self):
        self.assertNotEqual(f'{float("2.675"):.2f}', format_money('2.675', rounding=ROUND_HALF_UP))

if __name__ == '__main__':
    unittest.main()
