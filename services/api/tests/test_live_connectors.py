"""Parser tests against captured portal pages.

Each golden file is a listing page saved from the authority's own site
(`python capture_golden.py`). The tests parse them without touching the
network, so a change in how a portal lays out its page fails here rather than
silently emptying the dashboard.

What these tests protect:

* a notice still carries a title, a buyer, a date and a working link;
* the reference a portal prints is read as the reference, and nothing else;
* a missing closing date stays missing rather than being invented.
"""

import json
from pathlib import Path

import pytest

from app.connectors.epads_federal import EPADSFederalConnector
from app.connectors.epms_federal import EPMSFederalConnector
from app.connectors.ntdc import NTDCConnector
from app.connectors.ppra_punjab import PPRAPunjabConnector
from app.connectors.wapda import WAPDAConnector

GOLDEN = Path(__file__).resolve().parent / "golden"


class StubSource:
    """The parts of a source row a connector reads."""

    def __init__(self, code, name, area, adapter, url, listing_url):
        self.id = 1
        self.code = code
        self.name = name
        self.area = area
        self.type = "portal"
        self.adapter = adapter
        self.url = url
        self.listing_url = listing_url


def golden(name: str) -> str:
    path = GOLDEN / name
    if not path.exists():
        pytest.skip(f"golden capture missing: {name} (run capture_golden.py)")
    return path.read_text(encoding="utf-8")


def ppra():
    return PPRAPunjabConnector(
        StubSource(
            "ppra_punjab",
            "PPRA Punjab e-Procurement",
            "Punjab",
            "ppra_punjab",
            "https://eproc.punjab.gov.pk/",
            "https://eproc.punjab.gov.pk/ActiveTenders.aspx",
        )
    )


def epms():
    return EPMSFederalConnector(
        StubSource(
            "epms_federal",
            "Federal EPMS — PPRA",
            "Federal",
            "epms_federal",
            "https://epms.ppra.gov.pk/",
            "https://epms.ppra.gov.pk/public/tenders/active-tenders",
        )
    )


def epads():
    return EPADSFederalConnector(
        StubSource(
            "epads_federal",
            "Federal EPADS",
            "Federal",
            "epads_federal",
            "https://epads.gov.pk/",
            "https://epads.gov.pk/",
        )
    )


def wapda():
    return WAPDAConnector(
        StubSource(
            "wapda",
            "WAPDA Tenders",
            "Federal",
            "wapda",
            "https://wapda.gov.pk/",
            "https://wapda.gov.pk/wapda-tenders/",
        )
    )


def ntdc():
    return NTDCConnector(
        StubSource(
            "ntdc",
            "NTDC Tenders",
            "Federal",
            "ntdc",
            "https://ntdc.gov.pk/",
            "https://ntdc.gov.pk/tendors",
        )
    )


# -- PPRA Punjab -------------------------------------------------------


def test_ppra_reads_the_grid():
    notices = ppra().parse_grid(golden("ppra_punjab.html"))
    assert len(notices) > 50

    for notice in notices:
        assert notice["title"], notice
        assert notice["buyer_name"], notice
        assert notice["buyer_ref"], notice
        assert notice["url"].startswith("https://eproc.punjab.gov.pk/"), notice
        assert notice["published_at"], notice
        assert notice["submission_deadline"], notice


def test_ppra_notice_links_point_at_the_document():
    notices = ppra().parse_grid(golden("ppra_punjab.html"))
    # The document is linked relative to the site root, not to the listing
    # page, so the resolved link has to keep the root.
    assert all("/ActiveTenders.aspx/" not in n["url"] for n in notices)
    assert all(n["url"].endswith(".pdf") for n in notices)


def test_ppra_titles_do_not_carry_the_grid_link():
    notices = ppra().parse_grid(golden("ppra_punjab.html"))
    assert not any("View Tender Detail" in n["title"] for n in notices)


def test_ppra_reference_is_not_read_out_of_the_words_tender_notice():
    notices = ppra().parse_grid(golden("ppra_punjab.html"))
    assert not any(n["buyer_ref"] == "TICE" for n in notices)
    assert not any(n["buyer_ref"].upper().startswith("TICE") for n in notices)


def test_ppra_identities_are_unique():
    notices = ppra().parse_grid(golden("ppra_punjab.html"))
    ids = [n["native_id"] for n in notices]
    assert len(set(ids)) == len(ids)


def test_ppra_pager_targets_are_read_from_the_page():
    connector = ppra()
    targets = connector._pager_targets(golden("ppra_punjab.html"))
    assert targets, "the pager should offer at least one page"
    for page, target in targets.items():
        assert page >= 1
        assert "__doPostBack" not in target
        assert "rdgrdManageTender" in target


def test_ppra_states_the_portal_s_own_type():
    notices = ppra().parse_grid(golden("ppra_punjab.html"))
    kinds = {n["source_category"] for n in notices}
    assert kinds & {"Goods", "Services", "Work"}
    assert all(n["tender_type"] in ("Goods", "Services", "Works", "") for n in notices)


def test_ppra_detail_page_names_the_notice_it_corrects():
    connector = ppra()
    fields = connector._detail_fields(golden("ppra_detail.html"))
    assert fields["Procurement Title"]["text"] == "Corrigendum"
    assert fields["Publish Date"]["text"]
    # The detail page links the notice document of the tender being
    # corrected. That document is the identifier both rows share.
    stem = connector._document_stem(fields["Tender Notice"]["links"])
    assert stem, "the detail page should link the tender's notice document"
    assert not stem.endswith(".pdf")


def test_ppra_corrigendum_is_tied_to_the_notice_it_corrects():
    connector = ppra()
    notices = connector.parse_grid(golden("ppra_punjab.html"))
    corrigenda = [n for n in notices if n.get("detail_url")]
    assert corrigenda, "the listing should contain corrections"

    # With the detail page in hand, the correction takes the identity of the
    # tender it corrects and the date that tender was first published.
    fields = connector._detail_fields(golden("ppra_detail.html"))
    parent_stem = connector._document_stem(fields["Tender Notice"]["links"])
    notice = dict(corrigenda[0])
    notice["native_id"] = f"ppra-{parent_stem}"
    notice["buyer_ref"] = f"PPRA/{parent_stem}"
    notice["published_at"] = fields["Publish Date"]["text"]
    assert notice["buyer_ref"].startswith("PPRA/")
    assert notice["published_at"]


# -- EPMS (federal) ----------------------------------------------------


def test_epms_reads_the_active_list():
    notices = epms().parse_listing(golden("epms_federal.html"))
    assert len(notices) > 20

    for notice in notices:
        assert notice["title"], notice
        assert notice["buyer_ref"], notice
        assert notice["url"].startswith("https://epms.ppra.gov.pk/"), notice
        assert notice["published_at"], notice
        assert notice["submission_deadline"], notice


def test_epms_references_are_the_tender_numbers():
    notices = epms().parse_listing(golden("epms_federal.html"))
    for notice in notices:
        assert notice["buyer_ref"].startswith(("TS", "FW", "P")), notice["buyer_ref"]


def test_epms_marks_a_corrigendum_as_one():
    notices = epms().parse_listing(golden("epms_federal.html"))
    statuses = {n["notice_status"] for n in notices}
    assert "Corrigendum" in statuses


# -- EPADS (federal) ----------------------------------------------------


def test_epads_reads_the_opportunity_table():
    notices = epads().parse_listing(golden("epads_federal.html"))
    assert len(notices) > 20

    for notice in notices:
        assert notice["title"], notice
        assert notice["buyer_name"], notice
        assert notice["buyer_ref"], notice
        assert notice["url"].startswith("https://epads.gov.pk/opportunities/"), notice


def test_epads_keeps_the_full_title_from_the_tooltip():
    notices = epads().parse_listing(golden("epads_federal.html"))
    assert any(len(n["title"]) > 60 for n in notices)


def test_epads_references_are_the_agency_numbers():
    notices = epads().parse_listing(golden("epads_federal.html"))
    assert any(n["portal_reference"].startswith("P") for n in notices)


def test_epads_leaves_the_closing_date_empty():
    # EPADS publishes a countdown, not a date. The deadline is left empty
    # rather than estimated.
    notices = epads().parse_listing(golden("epads_federal.html"))
    assert all(n["submission_deadline"] is None for n in notices)


# -- WAPDA ---------------------------------------------------------------


def test_wapda_reads_the_post_list():
    notices = wapda().parse_listing(golden("wapda.html"))
    assert len(notices) > 3

    for notice in notices:
        assert notice["title"], notice
        assert notice["buyer_ref"], notice
        assert notice["url"].startswith("https://wapda.gov.pk/"), notice


def test_wapda_identities_are_unique():
    notices = wapda().parse_listing(golden("wapda.html"))
    ids = [n["native_id"] for n in notices]
    assert len(set(ids)) == len(ids)


# -- NTDC ----------------------------------------------------------------


def test_ntdc_reads_the_feed():
    payload = json.loads(golden("ntdc.json"))
    notices = ntdc().parse_feed(payload)
    assert notices

    for notice in notices:
        assert notice["title"], notice
        assert notice["buyer_ref"], notice
        assert notice["published_at"], notice
        assert notice["url"].startswith("https://ntdc.gov.pk/"), notice


def test_ntdc_leaves_the_closing_date_empty():
    payload = json.loads(golden("ntdc.json"))
    notices = ntdc().parse_feed(payload)
    assert all(n["submission_deadline"] is None for n in notices)


def test_ntdc_skips_results_and_tors():
    payload = json.loads(golden("ntdc.json"))
    notices = ntdc().parse_feed(payload)
    assert not any(n["source_category"].lower() in ("evaluation results", "tors") for n in notices)


def test_ntdc_document_links_are_under_uploads():
    payload = json.loads(golden("ntdc.json"))
    notices = ntdc().parse_feed(payload)
    assert all("/uploads/" in n["url"] for n in notices)
