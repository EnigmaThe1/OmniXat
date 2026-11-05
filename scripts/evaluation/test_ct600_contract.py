"""OmniXat diagnostic contract tests for pinned upstream CT600 renderer.

A passing test here can expose that upstream does NOT validate accounting
figures or redact authentication. This suite NEVER contacts HMRC.
"""
import base64
import copy

from lxml import etree
from ct600.build import build_xml
from tests.test_build import SAMPLE
from tests.test_ixbrl import FULL

CT_NS = "http://www.govtalk.gov.uk/taxation/CT/5"
C = f"{{{CT_NS}}}"


def test_renderer_accepts_contradictory_user_supplied_tax_figures():
    """Document builder is not a tax calculator; OmniXat must reject bad inputs."""
    data = copy.deepcopy(SAMPLE)
    data["corporation_tax"]["total"] = 0.0
    data["calculation"]["tax_payable"] = 123456.78
    root = etree.fromstring(build_xml(data))
    assert root.findtext(f".//{C}CorporationTax") == "0.00"
    assert root.findtext(f".//{C}TaxPayable") == "123456.78"


def test_renderer_embeds_synthetic_plaintext_gateway_password():
    """XML is sensitive: do not store or send it to logs/agents or GitHub."""
    data = copy.deepcopy(SAMPLE)
    data["credentials"]["password"] = "SYNTHETIC_FAKE_PASSWORD_NEVER_REAL"
    xml = build_xml(data)
    assert b"SYNTHETIC_FAKE_PASSWORD_NEVER_REAL" in xml


def test_renderer_can_emit_inconsistent_account_equity():
    """Well-formed attachments do NOT establish balanced statutory accounts."""
    data = copy.deepcopy(FULL)
    data["accounts"]["balance_sheet"]["current"]["net_assets"] = 5000
    data["accounts"]["balance_sheet"]["current"]["equity"] = 4000
    root = etree.fromstring(build_xml(data))
    attachments = root.findall(f".//{C}EncodedInlineXBRLDocument")
    assert len(attachments) == 2
    assert all(etree.fromstring(base64.b64decode(a.text)) is not None for a in attachments)


def test_upstream_uses_fixed_2024_computation_taxonomy():
    """Pinned 2024 taxonomy is expired for periods ending after March 2026."""
    from ct600.computation import CT_YEAR
    from ct600.accounts import FRC_VERSION
    assert CT_YEAR == "2024"
    assert FRC_VERSION == "2024-01-01"

def test_renderer_uses_float_and_can_misround_subpenny_values():
    """Demonstrate renderer behaviour; this MUST NOT become tax calculation logic."""
    from decimal import Decimal, ROUND_HALF_UP
    data = copy.deepcopy(SAMPLE)
    data["calculation"]["tax_payable"] = "1.005"
    root = etree.fromstring(build_xml(data))
    upstream_amount = root.findtext(f".//{C}TaxPayable")
    expected_exact = format(Decimal("1.005").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")
    assert upstream_amount == "1.00"
    assert expected_exact == "1.01"
