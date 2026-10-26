from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import (
    CategoryMapping,
    CompanyCertificate,
    CompanyProfile,
    EquipmentItem,
    FinancialYear,
    Lead,
    License,
    LibraryDocument,
    Opportunity,
    Personnel,
    ProjectExperience,
    Source,
    User,
)
from app.security import hash_password
from app.source_registry import SOURCES, sync_source_registry
from app.services import leads as leads_service, scorer

USERS = [
    ("admin@ahte.local", "System Admin", "admin", "admin123"),
    ("bm@ahte.local", "Bid Manager", "bid_manager", "bid123"),
    ("engineer@ahte.local", "Proposal Engineer", "proposal_engineer", "prop123"),
    ("finance@ahte.local", "Finance Officer", "finance", "fin123"),
    ("mgmt@ahte.local", "Management", "management", "mgmt123"),
    ("viewer@ahte.local", "Viewer", "viewer", "view123"),
]

ADMIN_EMAIL = USERS[0][0]

# The authorized source registry lives in app/source_registry.py. It is applied on
# every application start so a running database never keeps a stale portal URL.


def seed_users(db):
    """Create the sign-in accounts.

    A deployment reading the live portals is not a demo. It gets one
    account — the administrator — whose password comes from
    ``BMS_ADMIN_PASSWORD``, and no demo accounts at all: everyone else is
    created by the administrator through the app, with passwords nobody has
    printed in a repository. Fixtures mode keeps the demo accounts so the
    whole pipeline can be walked without setup.
    """
    created = 0
    accounts = USERS if settings.fixtures else [
        (ADMIN_EMAIL, "System Admin", "admin", settings.admin_password or "")
    ]
    for email, name, role, password in accounts:
        exists = db.execute(select(User).where(User.email == email)).scalars().first()
        if exists:
            continue
        if not password:
            import logging

            logging.getLogger("bms.seed").critical(
                "Refusing to create the administrator account with a known default "
                "password. Set BMS_ADMIN_PASSWORD and start again."
            )
            continue
        db.add(User(email=email, name=name, role=role, password_hash=hash_password(password)))
        created += 1
    db.commit()
    return created


def apply_admin_password(db):
    """Rotate the administrator's password to the one in the environment.

    Called on every start. Setting ``BMS_ADMIN_PASSWORD`` on a live
    deployment is therefore the documented way to change the admin password,
    including recovering one that was lost. The rotation only happens when
    the stored hash does not already match, so a start-up costs one password
    verification, not a write.
    """
    import logging

    from app.security import verify_password

    password = (settings.admin_password or "").strip()
    if not password:
        return False
    admin = db.execute(select(User).where(User.email == ADMIN_EMAIL)).scalars().first()
    if not admin:
        return False
    if verify_password(password, admin.password_hash):
        return False
    admin.password_hash = hash_password(password)
    db.commit()
    logging.getLogger("bms.seed").info("Administrator password rotated from BMS_ADMIN_PASSWORD")
    return True


def seed_kb(db):
    company = db.execute(select(CompanyProfile)).scalars().first()
    if company:
        return False
    company = CompanyProfile(
        name="AL-Hussain Traders & Engineers PVT. LTD.",
        legal_name="AL-Hussain Traders & Engineers PVT. LTD.",
        secp="SECP-0123456 (demo)",
        ntn="7654321-8 (demo)",
        tax_status="Active",
        address="Lahore, Pakistan",
        website="https://www.ahte.com.pk",
        email="info@ahte.com.pk",
        summary="Power-sector EPC contractor executing NTDC and donor-funded transmission & substation works with own tower, stringing and testing resources.",
        blacklisted=False,
    )
    db.add(company)
    db.add(
        License(
            authority="PEC",
            number="C-A-98765 (demo)",
            category="C-A",
            fields=["Electrical", "Transmission Lines", "Grid Stations", "Civil Works"],
            approved=True,
        )
    )
    for fy, turnover, net_worth, profit in [
        ("2022-23", 4_800_000_000, 2_100_000_000, 310_000_000),
        ("2023-24", 5_600_000_000, 2_480_000_000, 360_000_000),
        ("2024-25", 6_400_000_000, 2_900_000_000, 420_000_000),
    ]:
        db.add(
            FinancialYear(
                fiscal_year=fy,
                turnover=turnover,
                net_worth=net_worth,
                profit=profit,
                currency="PKR",
                auditor="Demo & Co. Chartered Accountants",
                bonding_capacity=1_500_000_000,
                approved=True,
            )
        )
    projects = [
        ("PD-EHV-24-2021", "National Transmission & Despatch Company (NTDC)", "Design, supply and installation of 220kV double-circuit transmission line (approx. 82 km) including tower erection, stringing and testing.", "Transmission Lines", 3_650_000_000, "Punjab", "2021", "2024", "Sole", "PSDP"),
        ("PD-EHV-26-2022", "National Transmission & Despatch Company (NTDC)", "500kV grid station extension: GIS bays, transformer installation, protection and SCADA works.", "Substations", 5_200_000_000, "Punjab", "2022", "2025", "Sole", "PSDP"),
        ("TLC-14", "NTDC (donor-funded)", "132kV transmission line construction package TLC-14 under donor financing.", "Transmission Lines", 2_250_000_000, "Khyber Pakhtunkhwa", "2020", "2023", "Sole", "ADB Loan"),
        ("ADB-201", "Power utility (ADB funded)", "220kV substation and associated transmission works under ADB-financed power transmission investment programme.", "Substations", 3_100_000_000, "Sindh", "2021", "2024", "JV Partner", "ADB Loan"),
        ("NOR-125", "NTDC (Nordic-funded)", "132kV grid station upgrading and rehabilitation works under Nordic financing.", "Substations", 1_480_000_000, "Punjab", "2022", "2024", "Sole", "Nordic Fund"),
        ("WB-08A", "Distribution company (World Bank funded)", "Rehabilitation and augmentation of 11kV/132kV distribution system, WB-08A package.", "Civil Infrastructure", 980_000_000, "Punjab", "2023", "2025", "Sole", "World Bank"),
    ]
    for contract_no, client, scope, category, value, area, start, end, role, funding in projects:
        db.add(
            ProjectExperience(
                contract_no=contract_no,
                client=client,
                scope=scope,
                category=category,
                value=value,
                currency="PKR",
                country="PK",
                area=area,
                start_date=start,
                end_date=end,
                role=role,
                funding_source=funding,
                certificate_ref=f"REF-{contract_no}",
                keywords=category,
                performance_note="Completed on schedule with satisfactory performance certificates.",
                approved=True,
            )
        )
    personnel = [
        ("Eng. Ahmed Khan", "Project Manager", "ELECT-PM-1101", 18, "B.Sc. Electrical Engineering", "PD-EHV-24-2021; PD-EHV-26-2022", ["PMP"]),
        ("Eng. Sana Malik", "Resident Engineer", "ELECT-RE-2205", 12, "B.Sc. Electrical Engineering", "TLC-14; ADB-201", []),
        ("Eng. Bilal Hussain", "QA/QC Engineer", "ELECT-QC-3310", 9, "B.Sc. Electrical Engineering", "PD-EHV-26-2022; WB-08A", ["ISO 9001 Lead Auditor"]),
        ("Mr. Tariq Mehmood", "HSE Officer", "HSE-4402", 11, "B.Sc. Environmental Science", "PD-EHV-24-2021", ["NEBOSH IGC"]),
        ("Eng. Fatima Sheikh", "Design Engineer", "ELECT-DE-5108", 7, "M.Sc. Power Systems", "ADB-201", []),
        ("Mr. Usman Ali", "Surveyor", "SUR-6601", 14, "D.A.E. Civil", "TLC-14; NOR-125", []),
    ]
    for name, position, pec, years, education, key_projects, certs in personnel:
        db.add(
            Personnel(
                name=name,
                position=position,
                pec_reg_no=pec,
                years_experience=years,
                education=education,
                key_projects=key_projects,
                certifications=certs,
                availability="Available",
                approved=True,
            )
        )
    equipment = [
        ("Hydraulic Tower Erection Crane 25T", "Cranes", "25 ton hydraulic", 2, "Owned", 2021),
        ("Stringing Equipment Set (Pullers & Tensioners)", "Stringing", "60 kN pulling / 40 kN tensioning", 3, "Owned", 2022),
        ("Concrete Batching Plant", "Civil", "30 m3/hr", 1, "Owned", 2020),
        ("Transit Mixers", "Civil", "6 m3", 6, "Owned", 2021),
        ("Test Van — Transformer & Cable Testing", "Testing", "500kV class HV test set", 1, "Owned", 2023),
        ("Excavators", "Civil", "1.2 m3 bucket", 4, "Owned", 2022),
        ("Tower Assembly Cranes 10T", "Cranes", "10 ton", 3, "Owned", 2021),
        ("Drilling Rigs for Foundations", "Foundations", "Auger rig", 2, "Leased", 2024),
    ]
    for name, category, spec, qty, ownership, year in equipment:
        db.add(
            EquipmentItem(
                name=name,
                category=category,
                spec=spec,
                quantity=qty,
                ownership=ownership,
                year=year,
                condition="Good",
                location="Central depot, Lahore",
                approved=True,
            )
        )
    for name, issuer, number in [
        ("ISO 9001:2015 QMS Certificate", "Demo Certification Body", "ISO9K-2211 (demo)"),
        ("ISO 14001:2015 EMS Certificate", "Demo Certification Body", "ISO14K-2212 (demo)"),
        ("ISO 45001:2018 OH&S Certificate", "Demo Certification Body", "ISO45K-2213 (demo)"),
        ("PEC Enlistment Certificate C-A", "Pakistan Engineering Council", "PEC-CA-98765 (demo)"),
    ]:
        db.add(CompanyCertificate(name=name, issuer=issuer, number=number, valid_from="2024-01-01", approved=True))
    library = [
        ("Company Policy — Bid Security and Bank Guarantees", "policy", "bid security, bank guarantee, finance", "Internal policy governing issuance and recovery of bid securities, performance bonds and advance payment guarantees."),
        ("HSE Manual Summary", "manual", "hse, safety, environment", "Site HSE organisation, PPE standards, incident reporting and emergency response procedures for transmission works."),
        ("Quality Assurance Procedure — Transmission Works", "procedure", "quality, qa qc, transmission", "ITPs, material inspection, tower erection tolerances, stringing sag checks and commissioning test records."),
        ("Subcontracting and JV Policy", "policy", "subcontract, joint venture, pec", "Rules for JV formation per PEC requirements and subcontractor prequalification."),
    ]
    for title, doc_type, tags, content in library:
        db.add(LibraryDocument(title=title, type=doc_type, tags=tags, content_text=content, approved=True))
    db.commit()
    return True


def seed_sources(db):
    """Apply the authorized source registry to the database.

    Refreshing matters: a registry correction (a portal moved to its real
    government domain, an authority name was filled in) has to reach databases
    that were seeded before the correction, not just fresh installs.
    """
    return sync_source_registry(db)


def seed_mappings(db):
    """Keep the portal-category mappings in step with the live portals.

    The mappings are applied one at a time rather than only on an empty
    table, so a category a portal starts publishing — PPRA Punjab's own
    "Goods" and "Services", for instance — reaches a database that was seeded
    before it appeared.
    """
    wanted = [
        ("ppra_punjab", "Electrical Works", "Transmission Lines"),
        ("ppra_punjab", "Civil Works", "Civil Infrastructure"),
        ("ppra_punjab", "Supply of Goods", "Supply / Goods"),
        ("ppra_punjab", "Goods", "Supply / Goods"),
        ("ppra_punjab", "Services", "Services"),
        ("epms_federal", "Works/Electrical", "Substations"),
        ("epms_federal", "Goods", "Supply / Goods"),
        ("epads_federal", "Consultancy Services", "Services"),
    ]
    for source_code, source_category, internal in wanted:
        existing = db.execute(
            select(CategoryMapping).where(
                CategoryMapping.source_code == source_code,
                CategoryMapping.source_category == source_category,
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(CategoryMapping(source_code=source_code, source_category=source_category, internal_category=internal))
        elif existing.internal_category != internal:
            existing.internal_category = internal
    db.commit()


def run_demo_pipeline(db):
    if db.execute(select(Opportunity)).scalars().first():
        return
    from app.services import jobs

    stats = jobs.run_scan(db)
    normalized = db.execute(select(Opportunity).where(Opportunity.state == "NORMALIZED")).scalars().all()
    for opp in normalized:
        scorer.run(db, opp)
    print(f"Demo pipeline: scanned {stats}, scored {len(normalized)} opportunities")
    leads_service.import_fixture_leads(db)
    from app.connectors import email_inbox

    email_source = db.execute(select(Source).where(Source.code == "email_plan")).scalars().first()
    if email_source:
        email_inbox.import_leads(db, email_source)


def main(init=True):
    # The application already brings the schema up before it seeds, so the
    # deployed start-up does not pay for the schema check twice.
    if init:
        init_db()
    db = SessionLocal()
    try:
        print(f"Users created: {seed_users(db)}")
        kb_seeded = seed_kb(db)
        print(f"KB seeded: {kb_seeded}")
        print(f"Sources: {seed_sources(db)}")
        seed_mappings(db)
        if settings.fixtures:
            run_demo_pipeline(db)
        counts = {
            "users": db.query(User).count(),
            "sources": db.query(Source).count(),
            "opportunities": db.query(Opportunity).count(),
            "leads": db.query(Lead).count(),
        }
        print(f"Seed complete: {counts}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
