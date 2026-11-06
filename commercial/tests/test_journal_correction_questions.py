import unittest

from omnixat_core.journal_correction_questions import journal_correction_questions


class JournalCorrectionQuestionTests(unittest.TestCase):
    def test_empty_reasons_return_no_questions(self):
        self.assertEqual(journal_correction_questions(()), ())

    def test_each_reason_has_a_distinct_question_in_first_seen_order(self):
        reasons = ("source_evidence", "amount", "account", "funding", "accounting_date")
        questions = journal_correction_questions(iter((*reasons, "amount", "source_evidence")))
        self.assertEqual(tuple(item.reason for item in questions), reasons)
        self.assertEqual(len({item.question for item in questions}), len(reasons))
        subjects = ("document", "amount", "ledger account", "funding source", "accounting date")
        for item, subject in zip(questions, subjects, strict=True):
            with self.subTest(reason=item.reason):
                self.assertIn(subject, item.question)
                self.assertTrue(item.question.endswith("?"))
