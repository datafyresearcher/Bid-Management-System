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
| **Authority** | "Punjab Procurement Regulatory Authority (PPRA), Government of Punjab" | The body that legally publishes the tender. Shown on the dashboard against every record from this source |
| **Tier** | `P0` / `P1` / `P2` | Priority from §1. Drives scan cadence and dashboard ordering |
| **Access** | `public` / `published-document` / `email` / `manual` | How we are entitled to read the data |
| **Portal URL** | `https://eproc.punjab.gov.pk/` | The authority's own home page. Must be the authority's real domain — never a lookalike |
| **Listing URL** | `https://eproc.punjab.gov.pk/ActiveTenders.aspx` | The page notices are actually read from. Defaults to the portal URL when a source publishes at one address |
| Entry URL + pagination pattern | as applicable | Templates only |
| Selectors / field map | title, dates, ref, attachments | Templates only; validated on Test Fetch |
| Category mapping | portal category → internal category | Editable table; defaults seeded |
| Schedule | daily 02:00 PKT | Per-source cadence |
| Rate limit / politeness | 1 req / 3 s | Defaults enforced by framework |
| Enabled | on/off | Off = retained history, no scans |
| Health | ok / degraded / broken + last scan stats | Auto-maintained; alert on transition |
| Approval | who/when approved | Audit |

**Portal URLs must be verified against the authority's own domain.** A URL that looks official but
is not — a dead host, a parked domain, or a plausible spelling of a government portal — makes
every downstream reference untraceable, which is worse than having no link at all. §9 lists the
domains confirmed live.

What non-technical admins **can** do: add Template A/B/C sources, adjust schedules, edit category
mappings, enable/disable, run Test Fetch, add email routes.
What needs engineering: new code adapters, selector work on JS-heavy portals, rate/robots changes.

### 5.1 Record-level provenance

Each opportunity carries a `source_id` pointing at its registry row, plus `source_refs` holding the
per-notice detail captured from the portal (the authority's own reference number and the URL of
the notice). The dashboard renders both: the registry row answers "which body publishes this",
the reference answers "which notice is this".

Records created outside a portal scan — manual entries, converted leads — still resolve to a
registry row (`manual`, `email_plan`, `annual_plan`) so no record is ever left unattributed.

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

---

## 9. Verified official portals

The registry only accepts URLs confirmed live on the authority's own domain. Verified against the
live portals:

| Registry code | Authority | Portal URL | Notice listing |
|---------------|-----------|------------|----------------|
| `ppra_punjab` | Punjab Procurement Regulatory Authority (PPRA), Government of Punjab | `https://eproc.punjab.gov.pk/` | `https://eproc.punjab.gov.pk/ActiveTenders.aspx` |
| `epms_federal` | Federal Public Procurement Regulatory Authority (PPRA), Government of Pakistan | `https://epms.ppra.gov.pk/` | `https://epms.ppra.gov.pk/public/tenders/active-tenders` |
| `ntdc` | National Transmission & Despatch Company Limited (NTDC) | `https://ntdc.gov.pk/` | `https://ntdc.gov.pk/tendors` |
| `wapda` | Pakistan Water and Power Development Authority (WAPDA) | `https://wapda.gov.pk/` | `https://wapda.gov.pk/wapda-tenders/` |

Also live and authoritative, for the next wave of adapters: `https://epads.gov.pk/` (Federal
EPADS), `https://ppra.punjab.gov.pk/` (PPRA Punjab notices),
`https://punjab.eprocure.gov.pk/` (EPADS Punjab e-bidding).

### 9.1 Notice links

A notice link must open a real page on the authority's site. Where a portal has no stable
per-notice URL, link to the listing page with the reference applied as a filter — EPMS accepts
`?keyword=<reference>`, which searches the live active-tenders list by title or tender number.
The captured reference number is always shown next to the link, so a reader can find the notice
whether or not the filtered URL resolves.

### 9.2 Capture mode

The registry records whether a capture came off the live portal or from a saved copy of one
(`last_scan_stats.mode`: `live` or `saved-capture`). The dashboard banner states this, so a saved
capture is never presented as a live pull.

The banner goes further than announcing the mode. It reports what the feed has actually done: how
many portals answered, when they last answered, which ones failed, and how many of the records on
screen came from a live read. Every record carries the mode of the read that captured it, so a
seeded demo record is counted separately from a live one and cannot pass for a tender.

---

## 10. Showing provenance to the user

The dashboard answers "where did this come from?" in three places:

1. **A banner** under the page title stating the capture mode and linking to the source register.
2. **A Source column / tag on every record** — the publishing source, its tier, the reference
   number captured from the portal, and a link to the notice.
3. **The "Data sources & provenance" register** — every source with its authority, tier, record
   count, official portal, notice listing, access mode, last scan and health.

The same attribution block appears on the opportunity detail page, where a reviewer confirms a
single tender before deciding to bid.

---

## 11. Reading the portals live

The connectors read the authorities' own pages. Nothing is aggregated, nothing is mirrored, and no
access control is bypassed. What follows is the operational detail of running that in anger.

### 11.1 Switching it on

```
BMS_FIXTURES=false
```

That is the whole switch. `settings.fixtures` selects between two paths in every connector: the
saved capture used in demo mode, and the live read used in production. Both paths are kept, so the
demo never depends on the portals being up and the live path never depends on a capture being
fresh.

The deployed API is switched by the release pipeline: `.github/workflows/deploy.yml` sets
`BMS_FIXTURES=false` on the Vercel API project before it deploys, and the smoke test fails the
build if the running API still reports that it is reading saved captures. Change that one line in
the workflow to go back to the demo feed.

The live settings live in `services/api/app/config.py` and can be overridden by environment
variable:

| Setting | Default | Meaning |
|---------|---------|---------|
| `BMS_LIVE_REQUEST_TIMEOUT` | 60 | Seconds allowed for one portal request. These are slow government sites. |
| `BMS_LIVE_MIN_INTERVAL` | 3.0 | Minimum seconds between two requests to the same portal. |
| `BMS_LIVE_RETRIES` | 2 | Retries after a failed request, with exponential backoff. |
| `BMS_LIVE_MAX_PAGES` | 3 | Listing pages walked per source in one scan. |
| `BMS_LIVE_MAX_DETAILS` | 2 | Detail pages read per source in one scan. |
| `BMS_LIVE_SCAN_DEADLINE` | 32 | Seconds a source's read may spend on the network. |
| `BMS_LIVE_LOOKBACK_DAYS` | 60 | How far back to read a portal that publishes its whole history at once. |
| `BMS_LIVE_BROWSER_UA` | true | Whether a live read presents a browser User-Agent (see 11.3). |

A read that would run past `BMS_LIVE_SCAN_DEADLINE` stops first, and returns the pages it managed to
read. That matters on a serverless function, where a read that is cut off halfway through loses
everything it had gathered.

### 11.2 What each connector reads

| Source | What is read | How |
|--------|--------------|-----|
| `ppra_punjab` | `eproc.punjab.gov.pk/ActiveTenders.aspx` | ASP.NET WebForms grid. Pages are reached by **postback**, carrying `__VIEWSTATE` and `__EVENTVALIDATION` back to the server; the postback target for each page is read from the pager's own links rather than guessed. |
| `epms_federal` | `epms.ppra.gov.pk/public/tenders/active-tenders` | Server-rendered table; the organisation card under each tender row carries the buyer. |
| `epads_federal` | `epads.gov.pk` | Server-rendered table; the full title and agency are read from the tooltip attributes, because the visible cell is truncated. |
| `ntdc` | `ntdc.gov.pk/ntdc/api/tenders` | Public JSON feed, no key and no session. The page itself is an Angular shell with no markup to read. |
| `wapda` | `wapda.gov.pk/wapda-tenders/` | WordPress posts, with the pager behind a query variable. |

Only public pages are read. The supplier registration, captcha and bid-submission pages of these
portals are never touched, and no credential is ever stored or sent — the system never signs in to
a portal, and submission stays a human act (D-06).

**PPRA Punjab answers only from inside Pakistan.** Its e-Procurement host (`eproc.punjab.gov.pk`)
does not accept a connection from outside the country: a read from the deployed API times out on
the connection, while the same read from a host in Pakistan returns the grid. The other four
portals answer from anywhere. So the Punjab connector works, and the deployed dashboard reports
that one portal could not be read rather than quietly showing nothing for it; running the API on a
host with a route into Pakistan brings Punjab in as well.

### 11.3 Reading as a browser, and why

Some of these portals drop a client that does not look like a browser. NTDC answers **403** to a
bot User-Agent and **200** to a browser one. PPRA Punjab's `.aspx` pages complete the handshake and
then drop the connection unless the client's TLS signature matches a browser's.

The live client therefore reproduces Chrome's TLS fingerprint (`curl_cffi`), and presents a browser
User-Agent. This is a read of a page any member of the public can open by typing its address; it
is not an attempt to get at anything a visitor would not see. The rate stays low, and the
User-Agent can be replaced with the system's own identity by setting `BMS_LIVE_BROWSER_UA=false` on
any portal that accepts it.

**Credentials found in a portal's own JavaScript bundle are not used.** NTDC ships an SDXP API key
in its public bundle; that key was left alone. Reading the public feed that the site's own
JavaScript calls needs no credential at all.

### 11.4 What is recorded, and what is not

A notice is only recorded with what the portal actually published:

- A closing date that a portal does not publish stays empty. EPADS publishes a countdown ("closing
  in 19 hours") and renders its dates in JavaScript; NTDC's feed has no closing date; WAPDA's
  listing does not carry one. In all three the deadline is left empty and picked up later from the
  notice document at Gate 2, rather than estimated.
- A reference is recorded only when the portal prints one. Where the listing has no reference field
  the notice is identified by the document the authority published it under, and the reference shown
  against the record is the one the authority printed.
- The portal's own type is used rather than a guess from the wording of the title. PPRA Punjab
  prints "Goods", "Services" or "Work"; that decides the tender type.

### 11.5 Corrigenda

A corrigendum is the tender it corrects, published a second time. PPRA Punjab and EPMS both list
the correction as a notice of its own, so the same tender appears twice in the listing. The
connectors tie the two together where the pairing is unambiguous, and the record keeps the
**later** closing date and is marked `Corrigendum`, because a corrected closing date is the thing
a bid manager must not miss.

### 11.6 Running it

A scan is per source: `POST /api/sources/{id}/scan`, or the **Scan** button in the dashboard's
source register (bid managers and admins). One source per request keeps the read inside the
function budget of a serverless deployment.

Where the API runs as a long-lived service, the scheduler loop runs the same code on an interval
(`BMS_SCHEDULER_ENABLED=true`, `BMS_SCAN_INTERVAL_SECONDS`).

A scan that returns no notices marks the source **degraded** rather than healthy — a portal that
answers but yields nothing has changed shape under us, and that is a drift signal.

### 11.7 Drift detection

`python capture_golden.py` saves the current listing page of each portal into
`services/api/tests/golden/`. The parser tests run against those captures on every build, so a
change in how a portal lays out its page fails the build instead of quietly emptying the
dashboard. Re-run the capture when a portal changes and the tests tell you what moved.

### 11.8 Runbook

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| Source health `degraded`, 0 notices | Portal layout changed, or the listing moved | Re-run `capture_golden.py`, read the diff, update the parser |
| Source health `error`, "could not connect" | The portal does not accept connections from this host | PPRA Punjab's e-Procurement portal answers only from inside Pakistan. Run the API on a host with a route into Pakistan |
| Source health `error` | Portal unreachable, or the TLS fingerprint was rejected | Check the portal by hand; confirm `curl_cffi` is installed (`pip install -r requirements.txt`) |
| Records appear but with no closing date | The portal does not publish one | Expected for EPADS, NTDC and WAPDA; the deadline arrives with the notice document at Gate 2 |
| Records appear with a document link instead of a page | The portal has no per-notice page | Expected for PPRA Punjab; the link opens the authority's own notice document |
| A tender appears twice | Two genuinely different notices share a name | Check the references: two different references are two different tenders |
| Scan times out | The portal is slow today | Lower `BMS_LIVE_MAX_PAGES`; the scan is per source and can be repeated |
