"""The authorized source registry.

Every channel we read from is an official publication: a government portal
owned by the body that publishes the tender, or one of our own desks. There is
no aggregator and no scraped mirror.

This module is the single definition of that registry, and it is applied on
every application start. The registry carries the authoritative portal URLs, so
a correction — a portal moved to its real government domain, an authority name
filled in — has to reach databases that were seeded before the correction, not
just fresh installs.

Columns per row:
    code, name, area, type, adapter, url, schedule, authority, tier, access,
    listing_url
"""

SOURCES = [
    (
        "ppra_punjab",
        "PPRA Punjab e-Procurement",
        "Punjab",
        "portal",
        "ppra_punjab",
        "https://eproc.punjab.gov.pk/",
        12,
        "Punjab Procurement Regulatory Authority (PPRA), Government of Punjab",
        "P0",
        "public",
        "https://eproc.punjab.gov.pk/ActiveTenders.aspx",
    ),
    (
        "epms_federal",
        "Federal EPMS — PPRA",
        "Federal",
        "portal",
        "epms_federal",
        "https://epms.ppra.gov.pk/",
        24,
        "Federal Public Procurement Regulatory Authority (PPRA), Government of Pakistan",
        "P1",
        "public",
        "https://epms.ppra.gov.pk/public/tenders/active-tenders",
    ),
    (
        "ntdc",
        "NTDC Tenders",
        "Federal",
        "portal",
        "fixture_json",
        "https://ntdc.gov.pk/",
        24,
        "National Transmission & Despatch Company Limited (NTDC)",
        "P1",
        "public",
        "https://ntdc.gov.pk/tendors",
    ),
    (
        "wapda",
        "WAPDA Tenders",
        "Federal",
        "portal",
        "fixture_json",
        "https://wapda.gov.pk/",
        24,
        "Pakistan Water and Power Development Authority (WAPDA)",
        "P1",
        "public",
        "https://wapda.gov.pk/wapda-tenders/",
    ),
    (
        "email_plan",
        "Email Inbox — Budget Signals",
        "Punjab",
        "email",
        "email_inbox",
        "",
        48,
        "AHTE bid desk — inbound tender alerts",
        "P2",
        "email",
        "",
    ),
    (
        "annual_plan",
        "Published Annual Procurement Plans",
        "",
        "plan",
        "fixture_json",
        "",
        0,
        "Discos and public-sector buyers (published annual procurement plans)",
        "P2",
        "published-document",
        "",
    ),
    (
        "manual",
        "Manual Entries",
        "",
        "manual",
        "fixture_json",
        "",
        0,
        "AHTE bid desk — analyst entry",
        "",
        "manual",
        "",
    ),
]


def sync_source_registry(db) -> tuple:
    """Create missing source rows and refresh the provenance on existing ones.

    Returns (created, refreshed).
    """
    from sqlalchemy import select

    from app.models import Source

    created = 0
    refreshed = 0
    for (
        code,
        name,
        area,
        type_,
        adapter,
        url,
        schedule,
        authority,
        tier,
        access,
        listing_url,
    ) in SOURCES:
        row = db.execute(select(Source).where(Source.code == code)).scalars().first()
        if row is None:
            db.add(
                Source(
                    code=code,
                    name=name,
                    area=area,
                    type=type_,
                    adapter=adapter,
                    url=url,
                    listing_url=listing_url,
                    authority=authority,
                    tier=tier,
                    access=access,
                    schedule_hours=schedule,
                    enabled=True,
                    approved=True,
                )
            )
            created += 1
            continue
        changed = False
        for field, value in (
            ("name", name),
            ("area", area),
            ("type", type_),
            ("adapter", adapter),
            ("url", url),
            ("listing_url", listing_url),
            ("authority", authority),
            ("tier", tier),
            ("access", access),
            ("schedule_hours", schedule),
        ):
            if getattr(row, field, None) != value:
                setattr(row, field, value)
                changed = True
        if changed:
            refreshed += 1
    db.commit()
    return created, refreshed
