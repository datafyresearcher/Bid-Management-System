# 01 — Research & Lessons Learned

This document records the research foundation for the system design: international platforms
studied, the Pakistan and Saudi procurement environments, AHTE's profile, and the design
implications drawn from all of it.

---

## 1. International platforms studied and lessons learned

### 1.1 Polytender — AI agent for tender discovery (EU/UK/US focus)

Reads 300+ official procurement portals daily, respects per-portal rate limits and access rules,
normalises every notice into one consistent schema (dates, values, currencies, CPV codes, regions,
lots), merges duplicates across portals into one record, links corrigenda to originals, and serves
it to AI agents through a clean tool interface.

**Lessons adopted:**
- Connector abstraction: portals own *zero* business logic; hundreds of sources become a handful
  of clean internal tools. When a portal changes, we fix one connector — not the whole system.
- "A person signs off: the agent recommends, a person decides" — every bid/no-bid and every
  submitted document has a human gate.
- "No invented evidence" — the model cannot know real references or certificates; instruct it to
  **mark gaps instead of filling them**, and feed it only approved material.
- Tender documents are **untrusted third-party input**; the model must treat document text as
  content, never as instructions (prompt-injection defence).

### 1.2 GroupBWT — tender data aggregation playbook

Published a 6-step playbook from building large tender aggregation systems (e.g., a UK system over
100+ heterogeneous sources).

**Lessons adopted:**
- **Build the source matrix before writing code** — every portal, its format (HTML/XML/JSON), update
  frequency, notice types and jurisdiction documented first. Our `docs/05` is that matrix.
- **Normalise to a single standard** — they adopt **OCDS (Open Contracting Data Standard)** as the
  baseline and extend it rather than replacing it. Our canonical opportunity model is
  OCDS-inspired (`docs/04`).
- **Strict 4-layer split**: Collection (fetch raw payloads only) / Normalization (per-source parsers)
  / Storage (dedup, versioning, raw snapshots) / Delivery (API). A crashed scraper, schema change
  or storage migration must never take down the other layers.
- **Tag at ingestion, not later**: jurisdiction, procurement regime, buyer type, thresholds are
  cheap to capture at fetch time and impossible to reconstruct afterwards.
- **Monitor schema drift, not just HTTP errors** — the silent failure is a renamed field or a
  shifted column; alert on *distribution anomalies* (e.g., a source that suddenly yields 10% of
  its usual volume).
- **Build the delivery API before the dashboard** — dashboards are downstream consumers.

### 1.3 TenderMania — autonomous tender agent (hackathon-grade reference)

Multi-agent pipeline: scraper agents → normalizer → scorer agents (capability, eligibility win
probability) → aggregator (pursue vs archive) → drafter agent (EOI). Hard-gate filters plus
multi-dimensional scoring; RAG over company data with BM25; **human approval gate on the final
action**; audit trail recording the reasoning behind each decision.

**Lessons adopted:**
- Deterministic **hard gates** (PEC category, blacklist, deadline feasibility) run *before* any
  LLM scoring — a tender that fails a hard gate never reaches AI judgement.
- Every AI recommendation must **explain itself with evidence** from the company profile and the
  tender; "this is a good fit" is not acceptable output.
- Audit trail of reasoning per decision (feeds the AI-quality analytics module).

### 1.4 Zuci — agentic AI bid management for a global services firm

Case study of converting high-stakes RFP response into a multi-agent decision system.

**Lessons adopted:**
- **Design the decision system before the agents**: define, on paper, who owns every decision,
  escalation rules, approval thresholds, guardrails, shared context, reliability metrics, and the
  human checkpoints. Our `docs/03` is that decision architecture.
- Enterprise safeguards are structural, not add-ons: audit trails for every decision, explainable
  reasoning paths, confidence scoring with escalation triggers, approval workflows for sensitive
  actions.

### 1.5 Purple → Bidwell (UK) — tender system turned product

Automated ingestion from UK portals into a daily email; a **knowledge base** of past responses,
case studies, credentials and policies; when a blank tender arrives, questions are extracted and
matched against the KB, drafting complete responses in the company's voice, exportable to
Word/Excel. Design target: turn a 20–40 hour writing job into 2–4 hours of review.

**Lessons adopted:**
- The KB is the engine, not a feature. One-time ingestion of company material pays off across every
  future bid.
- Extract the tender's *questions/requirements* first, then match to KB passages — never generate
  free-form text without a matched source.
- Export formats matter: proposals must leave the system as editable Word/Excel-compatible
  documents for final human polish.

### 1.6 WorkspaceAlberta (MCP bid workspace) — engineering reference architecture

An open architecture for a bid workspace combining public tender feeds (CanadaBuys, Alberta APC)
with LLM judgement.

**Lessons adopted:**
- **Deterministic before generative**: search, filtering, deadline ranking, profile matching and
  daily briefs are plain code — reproducible, zero per-request cost. The LLM is invoked *only for
  judgement* (tender fit review, document analysis).
- **Normalize early**: heterogeneous sources (bilingual CSV, camelCase JSON) are converted into one
  shared opportunity shape so every downstream tool works on one schema.
- **Untrusted files never touch the service**: attachments downloaded, unzipped and parsed inside a
  short-lived sandbox with hard limits (file count, size, prompt length, command timeouts); only a
  validated JSON artifact comes back.
- **Model routing with failover**: primary API key → fallback key → alternate provider — status
  inspectable without a model call.

### 1.7 Tender-automation platform case (epsilonmetrics, RU)

Six-module platform (AI search, document analysis, funnel, win-probability forecast, notifications,
AI-quality analytics) for 500-tender workloads.

**Lessons adopted:**
- **Start with the auto-search module first** — fastest visible effect, and it generates the data
  stream every later module depends on. (This matches our MVP milestone ordering, `docs/08`.)
- Win-probability forecasting requires accumulated own-history — it is a *later* phase, not an MVP
  feature.
- Notification design is a module of its own (deadlines, documentation changes, duplicates,
  stage-SLA breaches). We implement it as dashboard-only per decision D-03.
- Keep an **AI-quality analytics** view: share of correct auto-decisions, where the classifier errs,
  how often humans override — this is how the system earns trust.

---

## 2. Cross-cutting design implications (lesson → our decision)

| Lesson | Our design response (doc) |
|--------|---------------------------|
| Connectors own zero logic; fix one connector at a time | Adapter interface + per-source connectors, isolated parsing (`docs/02`, `docs/05`) |
| Deterministic before generative | Hard gates, scoring math, deadlines, dedup, matching in plain code; LLM only for extraction, judgement, drafting (`docs/02`) |
| Normalise early to a standard (OCDS-inspired) | Canonical Opportunity model + source taxonomy mappings (`docs/04`) |
| Tag jurisdiction/regime/thresholds at ingestion | Ingestion-time metadata fields (`docs/04`, `docs/05`) |
| Schema-drift monitoring beats HTTP monitoring | Golden fixtures + volume/distribution anomaly alerts per source (`docs/05`) |
| Human signs off every bid decision | 5 mandatory gates with SLA, audit and next-action triggers (`docs/03`) |
| No invented evidence; mark gaps | KB-grounded drafting with citations; "GAP" status in compliance matrix (`docs/03`, `docs/04`) |
| Tender files are untrusted input | Sandboxed parsing workers, size/type limits, injection fencing (`docs/02`) |
| Design the decision system first | `docs/03` precedes any code; A-register in `docs/10` |
| KB is the engine | One-time KB ingestion, evidence linking, certificate expiry tracking (`docs/04`) |
| Start with search module | M1 milestone is discovery+scoring before anything else (`docs/08`) |
| Model routing with failover; provider abstraction | OpenRouter (dev) → OpenAI (prod) via provider layer (`docs/02`) |
| AI-quality analytics | Correction-rate dashboard; feeds scoring calibration (`docs/03`) |

---

## 3. Pakistan market study

### 3.1 Regulatory environment

| Instrument | Scope | Relevance |
|-----------|-------|-----------|
| PPRA Ordinance 2002 + Public Procurement Rules 2004 | Federal public procurement | Governs NTDC, WAPDA, DISCOs, all federal entities |
| Punjab PPRA Rules 2014 | Punjab provincial procurement | Priority market (D-05); PPRA Punjab operates tender notices, EPADS, e-tender management and search |
| PEC bye-laws + standard documents | All engineering works procurement | Licensing categories, prequalification scoring, standard bidding documents incorporating FIDIC General Conditions |
| Donor rules (ADB, World Bank, IsDB) | Donor-funded projects | FIDIC-based bidding documents, NCB/ICB procedures, 28-day minimum bid period, no negotiations for lowest-evaluated bid |

Notes verified from primary sources:
- PPRA Punjab publishes tender notices, prequalification notices, EOIs and RFPs (>129,000 tender
  notices on file) at `ppra.punjab.gov.pk`; e-tendering runs at `punjab.eprocure.gov.pk`.
- Federal EPADS (`portal.eprocure.gov.pk`, `epads.gov.pk`) hosts tenders, PQ, EOI, awards **and
  Annual Procurement Plans of procuring agencies**; `epms.ppra.gov.pk` exposes active tenders
  (tenders open or closed within the last 10 days) with tender no, organisation, status, advertised
  and closing dates.
- Under Punjab PPRA Rules 2014, response time is computed from publication in a newspaper **or**
  on the website, whichever is later — meaning newspaper publication is legally meaningful, not
  just informational.

### 3.2 PEC (Pakistan Engineering Council) mechanics

- Constructors are licensed by **category and field of specialization**; AHTE holds **C-A
  (No Limit)** — eligible for works of any value in its fields.
- Prequalification (where used) is scored on **Financial Soundness 30 / Experience 35 / Personnel
  15 / Equipment 20**, with pass/fail minimums per heading; JV experience counts, sub-contractor
  experience does not; enlistment with government organizations scores points.
- Eligibility screens seen in standard bidding documents: PEC license relevant to value and
  specialization; **Active Taxpayer** on FBR/provincial lists; **not blacklisted/debarred** by PEC,
  federal/provincial PPRAs, foreign countries or international organizations; foreign constructors
  must JV with a locally registered constructor.
- PEC standard bidding documents (civil works >Rs 25 M; E&M; design-build TSTE; smaller contracts)
  incorporate FIDIC General Conditions with PEC-mandated Particular Conditions.

### 3.3 Source landscape (verified)

| Source class | Examples verified | Notes |
|--------------|-------------------|-------|
| Provincial portals | `ppra.punjab.gov.pk`, `punjab.eprocure.gov.pk` | Priority (D-05). Tender notices + e-tendering |
| Federal portals | `ppra.gov.pk`, `portal.eprocure.gov.pk`, `epads.gov.pk`, `epms.ppra.gov.pk` | EPADS + EPMS active tender lists; awards; annual plans |
| Buyer websites | NTDC, WAPDA, DISCOs (HESCO, GEPCO, LESCO…), SNGPL/SSGC (energy infra) | Direct adverts; AHTE's core buyers |
| Newspaper classifieds | Jang, Dawn, Express, Nawaiwaqt, The News, Dunya… | Many tenders appear in print (and legally count from print publication); ~9,800 tender ads/30 days observed on one aggregator |
| Donor portals | ADB (projects & tenders), World Bank, IsDB | Procurement plans with 18-month lookahead incl. planned advertisement dates |
| Budget documents | PSDP (federal), ADP (Punjab), PC-I/PC-II approvals | Pre-tender signals |
| Commercial aggregators | PakistanTender, TenderService.pk (PaperPK, since 2007, Rs 3,000/mo), biddetail.com | **Market validation**: paid demand exists for merely *listing* published tenders; none offer analysis, drafting, KB, or leads-to-advert pipeline depth |

### 3.4 Submission mechanics (why MVP is "assisted submission")

- Punjab e-procurement and EPADS require **registered supplier accounts**; final bid submission
  requires **digital signature (DSC / e-token)** and, for many tenders, **bank challans** for
  tender fees deposited *before* upload (PPRA Punjab rule guidance).
- Bid security (typically a bank guarantee / deposit at 2–5% of estimate) is a physical/instrument
  process outside any portal.
- Therefore: the system prepares everything (pack, checklist, forms, drafts) and verifies it, but
  a human executes the signed upload. Full e-submission becomes possible only in KSA (Etimad).

### 3.5 Unpublished-lead sources (available today, under-exploited)

1. **Annual Procurement Plans** — required of procuring agencies; published on EPADS and PPRA
   Punjab (planned procurements with dates/quarters).
2. **ADB procurement plans** — per-project 18-month lookahead with advertisement dates, updated
   versions (e.g., Power Transmission Strengthening Project 4383-PAK plans); from Jan 2026, ADB
   also mandates early market engagement for internationally advertised contracts.
3. **World Bank / IsDB** project pipelines and procurement notices.
4. **PSDP/ADP + PC-I approvals** — budget lines and approved schemes precede tenders by months.
5. **Prequalification notices** — earlier than main IFB; also a qualification-building opportunity.
6. Buyer websites' news/notices sections (NTDC/WAPDA project announcements).
7. Private-sector procurement (K-Electric, IPPs, CPEC-linked works) — direct invitations.

---

## 4. Saudi Arabia (KSA) market study — expansion path

- **Etimad** (launched 2018, Ministry of Finance / NCGR) unifies government procurement end-to-end:
  review tenders, purchase RFPs, submit bids, examine bids, technical evaluation, electronic award,
  plus "upcoming tenders" listings. Observed scale: ~2,000 active competitions at a time and
  >460,000 awarded tenders on the public listings; >SAR 1 trillion payment orders processed.
- **Official Developer Portal** (`apiportal.etimad.sa`) provides REST APIs with key-based access
  and product subscriptions — meaning **API-based ingestion replaces scraping** for KSA, and
  **true e-submission** is achievable in the expansion phase.
- **Government Tenders and Procurement Law, Art. 12**: entities must publish annual procurement
  plans — the same unpublished-leads capability applies.
- Domain deltas to plan for: **Arabic document processing** (RTL, OCR), **Hijri/dual calendars**,
  **Saudi Contractors Authority (SCA) classification** (analogue of PEC), **local content
  (LCGPA)** requirements, **data residency (PDPL/NCA)** — see `docs/09`.

---

## 5. AHTE profile and system fit

From public company information (ahte.com.pk):

- **AL-Hussain Traders & Engineers (Pvt.) Ltd** — incorporated under SECP; **PEC C-A (No Limit)**.
- Self-described **Power System EPC Company**: transmission lines, substations, civil
  infrastructures; expanding into renewable energy, transportation and trading/JV/consultancy.
- Representative project record: NTDC substations (PD-EHV-24, PD-EHV-26, NOR-125, WB-08A), NTDC
  transmission lines (TLC-14 lots), **ADB-financed lines (ADB-201 Lot-I sections)** — i.e., AHTE
  already bids and delivers donor-funded work, which is exactly where FIDIC-based documents,
  28-day windows and prequalification scoring (PEC/ADB) apply.
- Public posture welcomes **international JV/consortium partnerships** for domestic and global
  projects.

**Fit statement:** AHTE's buyer universe (NTDC, WAPDA, DISCOs, donor agencies, Punjab
infrastructure departments) maps directly onto the P0–P3 source plan in `docs/05`, and its
ADB track record makes the unpublished-leads pipeline (`docs/06`) immediately valuable.

---

## 6. What the research tells us NOT to build

- No fully autonomous bidder. Every credible system gates human judgement; public procurement law
  and practice demand accountability.
- No invented content. Grounded drafting with gap flagging only.
- No scraping-only strategy. Official APIs (Etimad) and inbox ingestion (email alerts) are more
  durable; scraping is a means, not the architecture.
- No win-probability ML in MVP. It needs accumulated own-history first.
- No notification sprawl. Dashboard-only for MVP (D-03); email/WhatsApp can come later if the
  domain expert argues for it.
