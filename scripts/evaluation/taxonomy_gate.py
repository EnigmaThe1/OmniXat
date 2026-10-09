"""Offline research gate for HMRC taxonomy dates; never authorises filing.

Snapshot: HMRC 'Taxonomies accepted by HMRC', updated 17 April 2026.
This intentionally rejects unknown versions. Always re-check live rules before a filing.
"""
from datetime import date

PUBLISHED_ON = date(2026, 4, 17)

# Minimum accounting period start and last permitted accounting period end.
# None = HMRC lists 'To be advised' (not unlimited legal permission).
COMP_TAXONOMIES = {
    2024: (date(2015, 4, 1), date(2026, 3, 31)),
    2025: (date(2015, 4, 1), None),
}
FRC_TAXONOMIES = {
    2024: (date(2015, 4, 1), date(2027, 3, 31)),
    2025: (date(2015, 4, 1), None),
    2026: (date(2015, 4, 1), None),
}


def assess(kind: str, version: int, start: date, end: date) -> tuple[str, str]:
    """Return status and explanation, not a determination of live HMRC acceptance."""
    if not isinstance(start, date) or not isinstance(end, date):
        return 'blocked', 'Missing or invalid accounting-period date.'
    if start > end:
        return 'blocked', 'Accounting period begins after it ends.'
    versions = {'corporation_tax_computation': COMP_TAXONOMIES, 'frc_accounts': FRC_TAXONOMIES}.get(kind)
    if versions is None or version not in versions:
        return 'blocked', 'Unknown taxonomy type or version in this snapshot.'
    lower, upper = versions[version]
    if start < lower:
        return 'blocked', 'Accounting period starts before the published minimum.'
    if upper is not None and end > upper:
        return 'blocked', f'Taxonomy expired for periods ending after {upper.isoformat()}.'
    if upper is None:
        return 'published_end_unset', 'HMRC has not published an ending date; verify currently accepted artefacts.'
    return 'in_published_window', 'Within the HMRC-published dates; HMRC gateway validation is still required.'


def upstream_ct600_2024_gate(start: date, end: date) -> dict[str, tuple[str, str]]:
    """Assess hard-coded ct600-filing constants: CT=2024, FRC=2024."""
    return {
        'ct_comp_2024': assess('corporation_tax_computation', 2024, start, end),
        'frc_2024': assess('frc_accounts', 2024, start, end),
    }
