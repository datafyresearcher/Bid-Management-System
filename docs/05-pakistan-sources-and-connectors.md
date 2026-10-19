# 05 — Pakistan Sources & Connectors

Audience: engineering (primary), domain expert (source validation, A-05/A-06).

This document is the **source matrix** that precedes code (GroupBWT lesson, `docs/01` §1.2), the
connector design that keeps portals replaceable, and the admin model for managing sources (D-04).

---

## 1. Source priority (per D-05)

| Tier | Source | Why this tier |
|------|--------|----------------|
| **P0** | Punjab PPRA + Punjab e-Procurement | Stated priority; high volume; legally relevant publication channel |
| **P1** | Federal EPMS + EPADS + NTDC/WAPDA/DISCO buyer sites | AHTE's power-sector bread and butter; donor-funded pipelines |
| **P2** | Newspapers (via email inbox, then OCR channel) | Tenders that never hit portals; also legally meaningful publication |
| **P3** | ADB / World Bank / IsDB plans & notices | Pipeline + donor tenders (AHTE has ADB record) |
| **Leads** | Annual procurement plans, PSDP/ADP, PC-I signals | See `docs/06` — cross-cutting, not a "scanned portal" |

---

## 2. Source matrix

Columns: access = how we fetch; auth = does fetching need login. *Feasibility* notes are
engineering assessments to be reconfirmed at build time (portals change).

### P0 — Punjab

| Source | URL | Content | Access | Cadence | Auth | Notes / risks |
|--------|-----|---------|--------|---------|------|----------------|
| PPRA Punjab — Tender Notices | `ppra.punjab.gov.pk` | Tender notices, PQs, EOIs, RFPs (+ archive) | HTML list + detail pages; attachments PDF | Daily (≥1×) | No | Large archive (100k+ notices historically); pagination + stable keys needed; watch for layout changes |
| Punjab e-Procurement (EPADS Punjab) | `punjab.eprocure.gov.pk` | Live e-tenders, corrigenda, results | HTML list + detail; some documents behind login | Daily | Partial | Document sale may require registered supplier account — fetch metadata + public docs only; **submission remains human** (D-06) |
| Punjab departments (LCMG etc.) | departmental sites | Occasional direct adverts | HTML | Weekly sweep | No | Cover via PPRA Punjab primarily; add only high-value departments if gaps observed |

### P1 — Federal & buyer sites

| Source | URL | Content | Access | Cadence | Auth | Notes / risks |
|--------|-----|---------|--------|---------|------|----------------|
| PPRA EPMS — Active Tenders | `epms.ppra.gov.pk` | Active tenders + recently closed (10 days) | HTML table + detail | Daily | No | Clean tabular structure; includes org, category, published/closing dates |
| Federal EPADS | `portal.eprocure.gov.pk`, `epads.gov.pk` | Tenders, PQ, EOI, awards, **annual plans** | HTML/JSON where exposed; PDFs | Daily (+ weekly for plans) | No | Some views are JS-rendered → browser automation (Playwright) |
| NTDC | `ntdc.gov.pk` | IFBs, PQs, corrigenda, awards (often donor-funded) | HTML + PDF | Daily | No | AHTE core buyer; cross-check against ADB notices |
| WAPDA | `wapda.gov.pk` (+ project sites e.g., `gmfp.wapda.gov.pk`) | Tenders, PQ, procurement manuals | HTML + PDF | Daily | No | Project-level sites vary; start with main site + known project pages |
| DISCOs (HESCO, GEPCO, LESCO, MEPCO, FESCO…) | each DISCO site | Distribution works tenders | HTML | Weekly sweep | No | Many small tenders; aggregate into same pipeline |
| Other energy infra (SNGPL, SSGC, PSO, OGDCL) | buyer sites | Adjacent-category works/goods | Weekly sweep | No | Optional expansion; useful for AHTE's trading arm |

### P2 — Newspapers (channel design in §6)

| Source | Content observed | Access | Notes |
|--------|------------------|--------|-------|
| Jang, Dawn, Express, Nawaiwaqt, The News, Dunya, Mashriq… | Classified tender notices (~thousands/month across dailies) | **Channel 1 (MVP): email inbox** — subscriptions/forwarded scans | Aggregators prove volume (≈9.8k tender ads / 30 days on one site) |
| Print/scan archives | Same | **Channel 2 (Phase 1.5): licensed OCR pipeline** | Copyright: use licensed feed or partnership; do not scrape publisher sites without review |

### P3 — Donors

| Source | URL | Content | Access | Cadence | Auth | Notes |
|--------|-----|---------|--------|---------|------|-------|
| ADB Projects & Tenders | `adb.org` project pages | IFBs, procurement plans (18-month lookahead), contract awards | HTML + PDF plans | Weekly | No | Procurement plans are also **leads** (`docs/06`); ADB mandates early market engagement for internationally advertised contracts from Jan 2026 |
| World Bank | `projects.worldbank.org` | Project pipelines, procurement notices | HTML/API-ish | Weekly | No | — |
| IsDB | `isdb.org` | Project procurement notices | HTML | Weekly | No | — |

---

## 3. Connector framework

One interface, many adapters. Connectors do **no** business logic (P2): they fetch, paginate,
download, and hand raw payloads to the normalizer.

```
Connector interface (conceptual)
  listing_page(cursor)      -> [ {source_native_id, url, title_snippet, dates_shown} ]
  detail(native_id)         -> { raw_html_or_json, fields_as_shown, attachment_links[] }
  documents(attachment)     -> file_stream (stored as RawSnapshot + Document)
  health_probe()            -> {ok|degraded, samples_expected_vs_found}
```

| Concern | Design |
|---------|--------|
| Pagination & cursors | Per-adapter; idempotent re-fetch (dedup by native_id + hash) |
| Raw persistence | Every payload stored immutably (hash, fetched_at, parser_version) before parsing — fixes can re-parse history |
| Parsing isolation | One parser module per source; a parser crash or layout change cannot affect other sources |
| Rendering needs | Static HTML: `httpx`; JS-heavy views: Playwright with a shared browser pool |
| Anti-bot reality | Keep request rates low; prefer list pages + detail pages as a human would; never bypass access controls |
| Change detection | Per-source **golden fixtures** (saved payloads) + parser tests run on every schedule tick against a canary page |
| Drift detection | Volume anomaly (source yields < 40% of trailing-average listings), field-presence checks (e.g., closing date missing rate > 10%), HTTP error rates → dashboard health alert (P8) |

---

## 4. Adapter templates vs code adapters (D-04)

| Type | Used when | Admin can create? |
|------|-----------|-------------------|
| **Template A — List+Detail HTML** | Portal has a paginated list table + detail pages with predictable fields; attachments are direct links | ✅ Yes — admin supplies URL patterns + CSS/XPath selectors via guided form; **must pass Test Fetch before activation** |
| **Template B — RSS/JSON feed** | Source exposes a feed/API | ✅ Yes — endpoint + field map |
| **Template C — Email forwarder** | Newspaper/third-party alerts | ✅ Yes — just a routing rule |
| **Code adapter** | Login-gated, multi-step JS flows, anti-bot-sensitive (e.g., e-procurement portals, DISCO sites) | ❌ Engineering only |

An admin-created source is inactive until: (1) Test Fetch returns ≥1 valid listing + 1 detail +
1 document link, (2) the domain owner marks the source approved, (3) it passes one scheduled scan
compared against the test result.

---

## 5. Source Registry schema (admin screen, D-04)

| Field | Example | Notes |
|-------|---------|-------|
| Name / Short code | "PPRA Punjab Notices" / `ppra_punjab` | Unique |
| Country / Area | PK / Punjab | Drives filters and taxonomy |
| Type | Portal / Buyer / Donor / Newspaper / Email | — |
| Adapter | Template A/B/C or code adapter id | — |
| Entry URL + pagination pattern | as applicable | Templates only |
| Selectors / field map | title, dates, ref, attachments | Templates only; validated on Test Fetch |
| Category mapping | portal category → internal category | Editable table; defaults seeded |
| Schedule | daily 02:00 PKT | Per-source cadence |
| Rate limit / politeness | 1 req / 3 s | Defaults enforced by framework |
| Enabled | on/off | Off = retained history, no scans |
| Health | ok / degraded / broken + last scan stats | Auto-maintained; alert on transition |
| Approval | who/when approved | Audit |

What non-technical admins **can** do: add Template A/B/C sources, adjust schedules, edit category
mappings, enable/disable, run Test Fetch, add email routes.
What needs engineering: new code adapters, selector work on JS-heavy portals, rate/robots changes.

---

## 6. Non-portal channels

### 6.1 Manual upload (MVP requirement)

Spec in `docs/03` §8. Engineering points: virus scan → sandbox parse; `source=manual`; if dedup
match found, offer "attach to existing opportunity"; extraction identical to portal tenders so all
downstream scores/matrices are comparable.

### 6.2 Email alert inbox

- Dedicated address, e.g., `tenders@<company-domain>`; IMAP polling every 15 min.
- Accepts: forwarded aggregator alerts, newspaper e-paper snippets, buyer emails, colleague finds.
- Parser: extract subject/body links → fetch → normalise; attachments (PDF/JPG) → OCR path.
- Rules: sender allowlist; per-sender tagging (e.g., `paperpk`); spam/quarantine view; manual
  approval queue for ambiguous items (never auto-create opportunities from unknown senders without
  review — the item lands as a Lead instead).

### 6.3 Newspaper OCR channel (Phase 1.5)

Options ranked: (1) **license a feed / partner** with an existing aggregator; (2) publisher e-paper
API if available commercially; (3) in-house OCR of scans *already lawfully obtained* (email inbox,
purchased copies). Decision gate: legal review of copyright before any pipeline that scrapes
publisher pages (A-08).

---

## 7. Submission mechanics support (per D-06)

Per-source submission cheat-sheets the system generates at Gate 5 (human executes):

| Portal | Mechanics the pack reflects |
|--------|------------------------------|
| Punjab e-Procurement | Supplier account login; DSC/e-token signing; tender fee challan (deposited before upload per PPRA Punjab practice); document naming per portal fields; upload limits |
| Federal EPADS | Supplier registration; DSC; fee instruments; two-envelope uploads where applicable |
| Buyer-portal (NTDC/WAPDA) | Physical/prescribed submission addresses when required; sealed-envelope instructions captured as checklist items with address + courier notes |
| Donor (ADB) | e-submission where offered (e.g., ADB CMS/portal); otherwise prescribed addresses; strict closing-time rules (timezone shown in pack) |

The system never stores portal credentials or DSC material (D-06; revisit only if the client
later requests credential custody with explicit security sign-off).

---

## 8. Source health monitoring (dashboard, P8)

| Signal | Threshold (default) | Action |
|--------|---------------------|--------|
| New listings volume | < 40% of trailing 7-day average | Degraded alert; canary fixture re-test |
| Required-field presence | closing-date missing > 10% of rows | Parser alert |
| HTTP/parse errors | > 5% of requests or any 3 consecutive | Broken alert; pause source; retry with backoff |
| Fixture test failure | Any golden fixture fails | Blocked scan; engineering ticket auto-created in audit log |
| Login walls appearing | Detail fetch redirects to login | Mark `partial`, notify admin |

All health alerts appear in the Admin Console and as a home-dashboard banner; no email (D-03).
