"""Focused questions for structured expense journal corrections."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

JournalCorrectionReason = Literal["amount", "account", "funding", "accounting_date", "source_evidence"]

_QUESTIONS: dict[JournalCorrectionReason, str] = {
    "amount": "What amount should this expense record, and where is it shown in the source evidence?",
    "account": "Which ledger account should this expense use, and what was the expense for?",
    "funding": "Which funding source paid this expense, and what record confirms the payment?",
    "accounting_date": "What accounting date should this expense use, and what evidence supports that date?",
    "source_evidence": "Which document or record supports this expense, and where are the relevant details shown?",
}


@dataclass(frozen=True)
class ExpenseJournalFollowUpQuestion:
    reason: JournalCorrectionReason
    question: str


def journal_correction_questions(
    reasons: Iterable[JournalCorrectionReason],
) -> tuple[ExpenseJournalFollowUpQuestion, ...]:
    """Return one question per supplied reason in order of first appearance."""
    return tuple(ExpenseJournalFollowUpQuestion(reason, _QUESTIONS[reason]) for reason in dict.fromkeys(reasons))
