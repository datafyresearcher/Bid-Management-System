# 08 — Pakistan MVP Scope, Milestones & Acceptance

Audience: management + engineering. This bounds what gets **built first**, what is deliberately
deferred, and how "done" is verified at each step.

---

## 1. MVP goal statement

> For AHTE, deliver a single-workspace system that (Punjab-first, Federal-second) **discovers
> tenders, scores them against AHTE's profile, runs five human gates, grounds proposal drafts in
> the company knowledge base, assembles the bid pack, and supports assisted submission** — with
> an unpublished-leads radar. Built with OpenRouter free models in dev/test; production on the
> in-house server with OpenAI API (D-07/D-08).

The MVP is successful when a real AHTE bid passes through all five gates end-to-end with the
system doing discovery → analysis → drafting, and humans doing decisions → review → submission.

---

## 2. In scope (modules)

| # | Module | Content | Doc ref |
|---|--------|---------|---------|
| M1 | Discovery & ingestion | PPRA Punjab + Punjab e-Procure + EPMS Federal connectors; email inbox; manual upload; normalisation, dedup, corrigendum linking | `docs/05` |
| M2 | Scoring & Gate 1 | Hard gates + weighted score + LLM rationale; Inbox; Go/No-Go task flow | `docs/02` §8, `docs/03` |
| M3 | Document analysis | Sandbox parsing; requirement extraction; compliance matrix draft; risk memo; Gate 2 | `docs/02` §7, `docs/07` |
| M4 | Knowledge Base | Full KB per `docs/04` §4 including evidence linking, approvals, expiry watch | `docs/04` |
| M5 | Drafting & assembly | KB-grounded drafting with citations; Gate 3; pack assembly + exports (DOCX/XLSX/PDF) | `docs/03` G3/G4 |
| M6 | Submission pack & Gate 5 | Checklist, named files, fee/security/challan checklist, portal deep link; submission record | `docs/03` G5, `docs/05` §7 |
| M7 | Leads Radar | L1–L5 sources (annual plans, ADB, WB/IsDB, PSDP/ADP, PQ-as-lead), lifecycle, conversion | `docs/06` |
| M8 | Admin & governance | Source registry (D-04), roles, audit log, dashboard notification center, AI quality view | `docs/02` §10, `docs/03` §6 |

---

## 3. Out of scope (explicit)

| Deferred item | Why | Phase |
|---------------|-----|-------|
| Automatic portal submission | Portals require DSC/e-token + fee instruments (D-06) | Never in PK; KSA via Etimad API |
| Newspaper OCR pipeline | Copyright/legal gate (A-08); MVP uses email inbox + manual upload | Phase 2 |
| Win-probability / price intelligence | Needs accumulated own-history (research lesson) | Phase 2/3 |
| KSA / Arabic / Etimad | Separate market phase | Phase 3 (`docs/09`) |
| Email/SMS/WhatsApp notifications | Dashboard-only per D-03 | Revisit post-MVP |
| Mobile app, multi-tenant SaaS | Single shared workspace for MVP (D-02) | Post-MVP |
| Full e-submission on buyer-specific portals (NTDC/WAPDA) | Mostly physical/sealed-envelope processes | Human-executed with checklist |

---

## 4. Source priority recap (D-05)

| Build order | Sources |
|-------------|---------|
| Sprint 1 | PPRA Punjab notices; Punjab e-Procure metadata; manual upload |
| Sprint 2 | EPMS Federal; EPADS annual plans; email inbox |
| Sprint 3 | NTDC; WAPDA; DISCO sweep; ADB/WB/IsDB plans |
| Later | Newspaper OCR; remaining buyer sites |

---

## 5. Milestones & exit criteria

### M1 — Discovery pilot (first value, matches research lesson "start with search")
**Scope:** PPRA Punjab + manual upload + normalisation + scoring + Inbox + Gate 1.
**Exit criteria (all):**
- ≥ 95% of published notices on PPRA Punjab captured within 24 h of publication, measured over 14 consecutive days against manual spot checks.
- Dedup: no duplicates in Inbox for notices seen on two sources (seeded test set).
- Each scored opportunity shows hard-gate result + rationale with ≥ 1 evidence link.
- Gate 1 decisions logged with full audit record.
**Review:** domain expert validates scoring sanity on 20 random opportunities.

### M2 — Analysis & KB
**Scope:** document download/parse, extraction, compliance matrix, risk memo, Gate 2, KB upload/approve/expiry.
**Exit criteria:**
- On 10 real historical AHTE tender packages: extracted submission deadline, bid security, qualification thresholds and evaluation method each ≥ 90% accurate vs manual gold set.
- Compliance matrix rows carry page/clause anchors; GAP items clearly flagged.
- KB round-trip: a qualification claim cites an approved artifact and shows it in the UI.

### M3 — Drafting, assembly, approval
**Scope:** KB-grounded drafting, Gate 3, pack assembly/exports, Gate 4.
**Exit criteria:**
- Draft sections contain citations only; zero uncited claims pass Gate 3 (audit check).
- Export opens cleanly in Word/Excel with expected structure for 3 tender types (works single-stage, two-envelope, donor SBD).
- A full mock bid (from M1–M3) completes gates 1→4 within 10 working days of synthetic start.

### M4 — Leads & submission support
**Scope:** Leads Radar (L1–L5), conversion linking, Gate 5 pack, outcome capture.
**Exit criteria:**
- Leads extracted from one EPADS annual plan set + one ADB procurement plan verified row-by-row against source (precision ≥ 90%, recall ≥ 80% on target categories).
- Lead→opportunity auto-link demonstrated on at least one real published tender.
- Gate 5 pack generated for 2 real tenders including portal-specific checklists.

### M5 — Pilot run with AHTE
**Scope:** run the system on live opportunities for 4–6 weeks alongside existing practice.
**Exit criteria:**
- ≥ 3 real bids processed through gates (at least 1 donor-funded).
- Time-savings measurements captured (discovery, analysis, drafting) vs baseline estimate.
- Domain owner sign-off on continued use; defect log triaged.

---

## 6. Acceptance criteria (system-level)

| Area | Criterion |
|------|-----------|
| Correctness | Hard-gate decisions reproducible (deterministic); no opportunity advances a state without required human decision |
| Evidence | 100% of compliance items and draft claims traceable (citation or GAP) |
| Audit | Every gate decision and automation action retrievable with who/when/what/why |
| Resilience | One source can be broken without degrading other sources (isolation test) |
| Politeness | Rate limits honored; no access-control bypass; robots respected |
| Cost | Token budget per opportunity enforced; degradation mode works with LLM disabled |
| Security | Sandbox escapes none; secrets not in logs; RBAC verified by test matrix |
| Usability | A Bid Manager completes Gate 1 triage of 20 opportunities in < 30 minutes |

---

## 7. Success metrics (post-pilot, feeding management dashboard)

| Metric | Baseline (est.) | Target |
|--------|-----------------|--------|
| Sources scanned daily | Manual, inconsistent | 100% of enabled sources, daily |
| Opportunities triaged per week | Ad hoc | Full coverage of matched tenders |
| Analysis time per tender | 3–8 h | ≤ 1 h human verification |
| Drafting time per bid | Days | Review-only edits (research target: 2–4 h) |
| Bids per month (capacity) | Limited by staff time | +50% without new hires |
| Missed deadlines | Occasionally | Zero for in-system opportunities |
| Leads converted (tracked → published) | Not tracked | Measured; target ≥ 60% on Tier High |

---

## 8. Team, effort, environment

| Role | Responsibility | Effort (indicative) |
|------|----------------|---------------------|
| Full-stack engineer (2) | Web app, API, workflow engine | 12–16 weeks to M4 |
| Data/connector engineer (1) | Connectors, parsing, sandbox | 10–14 weeks to M4 |
| AI engineer (1, can overlap) | Extraction/scoring/drafting pipelines, provider abstraction | 10–14 weeks |
| Domain owner (AHTE) | KB data, gate decisions, validation | Part-time continuous, esp. M2/M5 |
| Domain expert (reviewer) | A-register + questionnaire (`docs/10`) | ~2–3 days one-off + checkpoints |

**Dev environment:** Docker Compose (web, api, workers, Postgres+pgvector, Redis, MinIO);
OpenRouter free tier with failover; seeded fixtures = sample PPRA Punjab notices + one complete
tender package + synthetic AHTE KB (real data added at M2/M5).

---

## 9. Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Portal layout changes break connectors | High | Medium | Golden fixtures + drift alerts (P8); adapter isolation; admin registry |
| OpenRouter free-tier limits during dev | Medium | Low-Medium | Queue + backoff; deterministic-first; small eval models |
| Extraction accuracy on messy scans (BOQ tables) | Medium | Medium | Human confirmation at Gate 2 is the safety net; gold-set tuning loop |
| AHTE staff adoption | Medium | High | Start with search+score (least threatening); gate UX in their language; training at M1 |
| Copyright/legal on newspaper scraping | Medium | High if ignored | Email inbox + manual upload first; legal review before OCR pipeline (A-08) |
| KB quality (stale certificates, missing financials) | Medium | High | Approvals + expiry watch; M2 gate requires KB readiness for qualification claims |
| Scope creep (KSA, pricing, submissions) | High | Medium | This document is the boundary; changes via decision log |
