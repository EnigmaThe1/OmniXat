import unittest
from datetime import date
from taxonomy_gate import assess, upstream_ct600_2024_gate

class TaxonomyGateTests(unittest.TestCase):
    def test_upstream_2024_2025_period_within_published_window(self):
        got = upstream_ct600_2024_gate(date(2024, 10, 1), date(2025, 9, 30))
        self.assertEqual(got['ct_comp_2024'][0], 'in_published_window')
        self.assertEqual(got['frc_2024'][0], 'in_published_window')

    def test_exact_ct2024_end_boundary(self):
        self.assertEqual(assess('corporation_tax_computation', 2024, date(2025, 4, 1), date(2026, 3, 31))[0], 'in_published_window')

    def test_ct2024_expires_for_period_end_april_2026(self):
        self.assertEqual(assess('corporation_tax_computation', 2024, date(2025, 4, 2), date(2026, 4, 1))[0], 'blocked')

    def test_expired_ct2024_despite_frc2024_still_accepted(self):
        got = upstream_ct600_2024_gate(date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(got['ct_comp_2024'][0], 'blocked')
        self.assertEqual(got['frc_2024'][0], 'in_published_window')

    def test_2025_ct_end_date_not_published(self):
        got = assess('corporation_tax_computation', 2025, date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(got[0], 'published_end_unset')

    def test_frc2024_expires_after_march_2027(self):
        self.assertEqual(assess('frc_accounts', 2024, date(2026, 4, 1), date(2027, 4, 1))[0], 'blocked')

    def test_unrecognised_taxonomy_blocks(self):
        self.assertEqual(assess('corporation_tax_computation', 2099, date(2026, 1, 1), date(2026, 12, 31))[0], 'blocked')

    def test_reversed_dates_block(self):
        self.assertEqual(assess('frc_accounts', 2024, date(2026, 12, 31), date(2026, 1, 1))[0], 'blocked')

    def test_start_before_published_minimum_blocks(self):
        self.assertEqual(assess('frc_accounts', 2024, date(2014, 12, 31), date(2015, 12, 31))[0], 'blocked')

if __name__ == '__main__':
    unittest.main()
