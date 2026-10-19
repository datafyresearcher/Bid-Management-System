# 00 — Executive Summary

## The problem

Infrastructure contractors in Pakistan, such as AHTE (EPC — transmission lines, substations,
civil works), lose time and revenue to a fragmented, manual bid process:

| Pain | Reality today |
|------|----------------|
| Opportunity discovery | Staff check PPRA Punjab, Federal EPADS, NTDC/WAPDA websites and newspaper classifieds manually. Tenders are missed; deadlines are lost. |
| Document analysis | A single tender package (100–300+ pages: ITT, GCC/PCC, specs, BOQ, drawings) takes hours to read, extract requirements from and convert into a compliance matrix. |
| Proposal preparation | Technical proposals are re-assembled from scratch each time, though 70–90% of content (project experience, CVs, equipment, policies) already exists inside the company. |
| Pipeline blindness | No visibility of tenders that are *coming* (procurement plans, ADB/World Bank pipelines, budget documents) — only what is already advertised. |
| Institutional memory | Win/loss reasons, pricing history and client intelligence live in individual inboxes and folders. |

Existing commercial aggregators (PakistanTender, TenderService.pk, etc.) only **list published
tenders** — they do not analyse documents, prepare proposals, or see unpublished opportunities.

## The solution

An AI-powered Bid Management System (BMS) with one shared workspace that runs the full lifecycle:

```
DISCOVER → SCORE → [HUMAN: GO/NO-GO] → ANALYSE → [HUMAN: ELIGIBILITY]
        → DRAFT → [HUMAN: REVIEW] → ASSEMBLE → [HUMAN: APPROVE]
        → READY TO SUBMIT → [HUMAN: SUBMIT ON PORTAL] → OUTCOME LEARNING
```

- **Generic by design** — inputs are `Country`, `Area`, `Category`. Pakistan is fully configured
  first (Punjab priority, then Federal); Saudi Arabia (Etimad) is the designed expansion path.
- **Unpublished Leads Radar** — surfaces pre-advertisement signals: annual procurement plans,
  ADB/World Bank/IsDB procurement plans, PSDP/ADB budget allocations, prequalification notices.
  This is the capability no local aggregator offers.
- **Company Knowledge Base** — the company's legal, financial, experience, personnel, equipment
  and certificate data, ingested once and reused for every prequalification and proposal. Every
  AI-drafted claim is traceable to a KB artifact; gaps are flagged, never filled with fiction.
- **Human-in-the-loop by construction** — five mandatory review gates; the system performs the
  next automated actions only after a human decision (approve, reject, request changes).
- **Pakistan-ready compliance** — PEC licensing rules, blacklist checks, PPRA procedures, FIDIC
  and PEC standard bidding document awareness built into the analysis.
- **Assisted submission** — MVP assembles the complete bid pack, verifies the checklist and hands
  over a portal deep link; the human signs and uploads (portals require DSC/e-token). The KSA
  phase enables true e-submission because Etimad is fully electronic with an official API.

## Why now / why this design

Research across six international systems (see `docs/01`) converges on the same recipe we adopt:
normalise many portals into one schema; keep deterministic logic for search/ranking and use LLMs
only for judgement; gate every bid decision behind a human; ground all drafts in a company
knowledge base; and monitor sources for silent breakage. One studied platform cut document
review time from 3–4 hours to ~15 minutes of verification; another reduced proposal writing from
20–40 hours to 2–4 hours of review time — those are the target economics for AHTE.

## Value case (targets, to be validated with AHTE)

| Metric | Today (est.) | Target with BMS |
|--------|--------------|-----------------|
| Discovery effort | 2–3 h/day scanning sources | 15–30 min/day reviewing a scored inbox |
| Tender package analysis | 3–8 h/tender | 30–60 min verification of AI-extracted matrix |
| Proposal assembly | Days per bid | Review-and-edit of a pre-assembled draft |
| Missed eligible tenders | Unknown, non-zero | Near zero: every configured source scanned daily |
| Unpublished pipeline visibility | Ad hoc | Continuous leads radar with expected quarters |
| Win/loss learning | Not captured | Captured per opportunity, feeds future scoring |

## Decisions requested from the Business Domain Expert

The review pack (`docs/10`) contains an **Assumptions Register** and a **25-question
questionnaire**. The highest-impact items:

1. Confirm the eligibility rule set (PEC categories, turnover multiples, experience thresholds)
   used for auto-screening AHTE against tenders.
2. Confirm the review chain and approval authorities inside AHTE (who signs off Go/No-Go, pricing,
   final bid).
3. Confirm which contract regimes dominate (PEC standard documents vs FIDIC editions vs donor
   documents) and which clause-level risks deserve automated flags.
4. Validate the source priority list (`docs/05`) and unpublished-lead sources (`docs/06`).
5. Validate the assisted-submission flow against how AHTE actually submits (DSC, challans, portal
   accounts).

## Scope of this pack and next steps

This phase delivers **documentation only** (this pack). After domain sign-off:

- **Phase 1** — Pakistan MVP build (see `docs/08`): discovery + scoring + analysis + KB + drafting
  + gates + assisted submission, developed with OpenRouter free models and deployed on the
  in-house server with an OpenAI provider switch.
- **Phase 2** — harden, add newspaper channel and more sources, capture win/loss analytics.
- **Phase 3** — KSA market entry via Etimad APIs (see `docs/09`).
