# 10 — Business Domain Expert Review Pack

**Audience: the Business Domain Expert (tendering / procurement / contracts / FIDIC).**
This document is the handover point between the design team and domain knowledge. Nothing in this
pack is treated as settled until the items below are validated.

**How to use this pack (≈ 3–4 hours):**

1. Read `docs/00` (summary) and `docs/03` (workflow) — 30 min.
2. Walk the **worked example** below against your real experience — 45 min.
3. Complete the **Assumptions Register** verdicts — 45 min.
4. Answer the **25-question questionnaire** — 60 min.
5. Review the **sample artifacts** and mark anything factually wrong about Pakistani procurement
   practice — 30 min.
6. Sign the checklist at the end (or list required changes).

Feedback format: for each item use `Accept / Reject / Modify + comment`. Changes are tracked in the
decision log (`README.md`) and the affected documents are revised before build starts.

---

## 1. Assumptions Register (A-register)

Every assumption the design currently rests on. **Impact if wrong** = what breaks in the system if
the assumption is incorrect and we build anyway.

| ID | Assumption | Why it matters | Impact if wrong | Validate? |
|----|-----------|----------------|-----------------|-----------|
| A-01 | AHTE will act as pilot user/design partner and provide KB data (financials, projects, certificates) and sample tender history for the gold set | MVP accuracy targets and KB grounding depend on real data | Extraction/scoring quality unverifiable; pilots slip | Confirm pilot commitment and data owner |
| A-02 | AHTE's primary buyers are NTDC, WAPDA, DISCOs, Punjab infrastructure departments, and donor agencies (work found via PPRA Punjab, EPADS, buyer sites, newspapers) | Drives source priority P0–P3 | Wrong sources → empty inbox → trust collapse in week 1 | Does this match where AHTE actually finds work? What is missing? |
| A-03 | Gate owners: Bid Manager = Gate 1/5; Proposal Engineer (+Technical Expert) = Gate 2/3; Management = Gate 4. Approval authority scales with tender value (bands TBD) | Workflow routing and SLAs | Wrong owners → bottlenecks, unapproved bids or stalled queues | Who signs Go/No-Go? Who approves final bid/price? At what value bands? |
| A-04 | Tender mix is dominated by works (transmission lines, substations, civil), with some goods/supply; mostly PEC-format SBDs, some donor SBDs, occasional private EPC | Determines parser and template priorities | Build effort spent on wrong tender types | Typical monthly tender count and type split? |
| A-05 | Source priority: Punjab P0 (ppra.punjab.gov.pk, punjab.eprocure.gov.pk); Federal P1 (EPMS, EPADS, NTDC/WAPDA/DISCOs); newspapers P2; donors P3 | Build order and expectations | Missed opportunities or wasted connector effort | Accept or reorder? Any Punjab-specific source missing (e.g., specific C&W, PHED portals)? |
| A-06 | The portal coverage in `docs/05` §2 is complete enough that > 90% of relevant AHTE tenders appear in at least one configured source | Coverage goal is the core promise | Silent missed tenders destroy trust | Where do tenders you actually win appear? What's not on our list? |
| A-07 | Contract regimes: PEC SBDs (FIDIC-based GCC/PCC) dominate; donor projects use FIDIC-based agency SBDs; Silver Book appears mainly in private/EPC contexts | Risk-flag and regime-detection rules | Flags misfire; wrong checklists | Which FIDIC editions/formats are most common in your last 20 tenders? |
| A-08 | Newspaper OCR pipeline must wait for legal review/licensing; email inbox + manual upload suffice for MVP | Legal exposure | Copyright claim or delayed channel | Which papers/aggregators matter most; is a licensed feed acceptable budget-wise? |
| A-09 | Hard eligibility gates: PEC category/field coverage, active taxpayer, blacklist checks (PEC + PPRAs), deadline feasibility, JV-only rules for foreign constructors | Gate 1 integrity | System approves tenders AHTE cannot win or rejects ones it can | Are these the right hard gates? What else is truly a knockout in practice? |
| A-10 | Awards in public works go to lowest evaluated (technically responsive) bid; negotiations are rare/restricted | Pricing strategy assumptions in drafting/checklists | Misleading strategy guidance | Confirm evaluation reality on AHTE's typical tenders (works + donor) |
| A-11 | Scoring: hard gates then weighted soft score (scope 30 / buyer 15 / value 15 / geography 10 / qualification margin 15 / strategy 15); auto-archive below 40; Gate 1 queue above threshold | Inbox quality = product quality | Noise (junk queue) or missed good tenders | Accept weights? What threshold would you trust to auto-archive? |
| A-12 | Pricing/BOQ remains human-entered in MVP; the system provides BOQ extraction and a pricing skeleton but no cost intelligence | Honest scope boundary | Expectation mismatch with management | Where does cost/rate data live today? Is structured extraction useful there? |
| A-13 | Bid security 2–5% (bank guarantee/deposit), tender fee via bank challan; both tracked as checklist items with deadlines | Gate 5 pack correctness | Rejected/blocked submissions | Confirm typical security %/forms and fee practices in Punjab vs Federal |
| A-14 | Gate SLAs: Gate 1 = 1 wd (4h if deadline < 7d); Gate 2 = 2 wd; Gate 3 = 3 wd; Gate 4 = 1 wd; Gate 5 = by T-1 | Escalation behaviour | Bids start late → rushed quality | Are these realistic for AHTE staffing? Override per tender type? |
| A-15 | Risk-flag severity defaults (e.g., uncapped liability = High; missing price adjustment = High in PKR inflation) and which flags always escalate to management | Risk memo usefulness | Flags ignored or alarm fatigue | Which risks have burned you most? What must always reach management? |
| A-16 | Clarification questions may be system-drafted with citations for human approval before sending | Uses query windows better | If culturally unacceptable, wastes feature | Should the system draft clarifications or only list anomalies? |
| A-17 | JV/consortium is a realistic route (AHTE welcomes international JVs) and JV partners/agreements belong in the KB | JV gates, PQ scoring, KSA path | Foreign-JV rules unmodeled | Current JV partners? How do you evaluate JV vs sole bids? |
| A-18 | KB data exists in usable form: 3–5 yrs audited financials, completion certificates, CVs, equipment lists, licence scans | KB is the engine of drafting | Drafting produces GAPs only; low value | Who owns each KB section? Is anything unavailable/restricted? |
| A-19 | Internal working language is English; a bilingual (EN-UR) glossary suffices for non-technical users | UI/drafts language | Adoption friction | Is Urdu UI needed for any role? |
| A-20 | AHTE will capture win/loss reasons and (optionally) competitor/award intelligence | Feeds analytics + future win-probability | No learning loop | Who records outcomes today (if anyone)? Any policy limits on competitor data? |
| A-21 | CV/personal data: access-controlled; departure handling per HR policy | Privacy/governance | Compliance gap | What is the current HR policy reference? |
| A-22 | Audit expectations: every AI action and gate decision retrievable with who/when/why; no deletion of decision records | Governance promise | Trust/dispute risk | Any internal/external audit frameworks we must align to? |

---

## 2. Worked example — full thread (critique this)

> **Scenario (pattern from real tenders):** NTDC issues a prequalification/tender for a **220 kV
> substation extension**, ADB-financed (PTSP-style project, IFB like `ADB-PTSP-…`), published on
> NTDC site + EPMS + a national daily. Deadline 28 days. Contract: donor SBD (FIDIC-based), works,
> single-stage (post-qualification), bid security via bank guarantee, sealed submission.

### 2.1 Lead (T + 90 days before advertisement)

Leads Radar shows an L2 row extracted from the ADB project procurement plan: *"220 kV substation
works (Nowshera/Jamrud-type scope) — planned advertisement Q1"* — confidence High, evidence link
to plan page. Prep prompts: verify bank guarantee line, update 220 kV project keywords in profile.

### 2.2 Discovery & scoring (T + 0)

| Field | Value |
|-------|-------|
| Opportunity | OPP-2026-0311 — NTDC: 220 kV Substation Extension (ADB PTSP) |
| Sources | NTDC site (primary), EPMS (dup linked), newspaper (dup linked) |
| Hard gates | PEC C-A covers works ✓ · No blacklist hits ✓ · Deadline feasible (28 days; docs public) ✓ · No foreign-JV-only clause ✗ (not needed) |
| Soft score | **78/100** — Scope 27/30 (similar to PD-EHV-24/26) · Buyer 15/15 (NTDC, 4 projects) · Value 12/15 (security line check) · Geography 10/10 · Qualification margin 10/15 (similar-work count = 2 of 2 required, thin margin) · Strategy 4/5 |
| AI rationale | "Strong fit: AHTE has executed two comparable 220 kV substation packages for NTDC; qualification margin on similar-work count is thin — verify Form-A project certificates before committing." |
| Gate 1 | Task created, owner Bid Manager, due 1 wd → **GO** |

### 2.3 Analysis (after GO)

**Compliance matrix (excerpt)**

| # | Requirement (anchor) | Evidence (KB / tender) | Status |
|---|----------------------|------------------------|--------|
| 1 | PEC C-A licence, works specialization (ITT 3.1, p.12) | KB: PEC C-A, valid to 2027-06 | Covered |
| 2 | Average turnover ≥ Rs 2.5 bn, 3 yrs (ITT 4.2) | KB: FY23–FY25 audited | Covered |
| 3 | Similar works: ≥ 2 × 220 kV substations in last 7 yrs (ITT 4.3a) | KB: PE #214, #231 (+certificates) | Covered |
| 4 | ISO 9001 (ITT 3.4) | KB: cert valid to 2026-11 | Covered (expiry watch) |
| 5 | Bid security PKR 5.0 M, BG, 28-day validity beyond close (ITT 14, p.33) | — | **TBD** (arrange BG) |
| 6 | Form-A experience certificates on template (Forms §) | KB: certificates exist, need Form-A re-signing | **GAP** (owner: Proposal Eng, due T-10) |
| 7 | JV agreement (if JV) | — | N/A (sole bid) |

**Risk memo (excerpt)**

| Severity | Flag (anchor) | Meaning | Suggested action |
|----------|---------------|---------|------------------|
| High | PCC M-4: delay damages wording exceeds PEC standard variation (PCC p.9) | Uncapped exposure risk | Clarification question; management awareness at Gate 4 |
| Medium | Query window = 10 days from publication (ITT 10) | Short window | Submit clarifications by T-2 |
| Medium | No steel price-adjustment clause (PCC 13.8) | Volatility exposure on rebar/structure | Clarification + price buffer in estimate |

**Clarification draft (human-approved before sending):** "PCC M-4 — please confirm the LD cap and
its basis per PEC standard provisions." / "PCC 13.8 — is price adjustment for steel permitted under
the contract data?"

### 2.4 Gates 2–5

- **Gate 2:** Proposal Engineer confirms matrix; two GAPs assigned (Form-A re-signing; BG
  arrangement) with due dates; CONFIRMED at T-12.
- **Gate 3:** Technical approach, two project references and key CVs drafted from KB with
  citations; edits logged; approved at T-5.
- **Gate 4:** management approves pack + price at T-3.
- **Submission pack:** checklist (envelope rules, address/e-submission mode, BG originals, power of
  attorney, forms list, page limits), named files, courier/submission steps, DSC reminder.
- **Gate 5:** Bid Manager submits; receipt uploaded; status SUBMITTED at T-2.
- **Outcome:** award notice ingested via EPMS; recorded LOST (reason: margin on price; competitor
  data optional). Feeds AI quality + future scoring calibration.

---

## 3. Sample artifacts (mark corrections directly)

### 3.1 Scoring card (as shown at Gate 1)

```
OPP-2026-0311  NTDC — 220kV Substation Extension (ADB PTSP)         Score 78/100
Hard gates: PEC C-A ✓  Blacklist ✓  Deadline feasible ✓ (28 days)
Sub-scores: scope 27/30 · buyer 15/15 · value 12/15 · geography 10/10 · margin 10/15 · strategy 4/5
Rationale: Strong fit — two comparable NTDC 220kV substation packages in KB.
Caveat: similar-work requirement = 2, AHTE qualifies with exactly 2 → verify certificates.
Deadline: <date>  ·  Bid security: PKR 5.0 M BG  ·  Regime: Donor SBD (FIDIC-based)
```

### 3.2 Submission pack checklist (excerpt)

```
[ ] Bid security: bank guarantee, format per ITT 14 — bank instruction raised (ref #)
[ ] Tender fee challan deposited — receipt no. ____ (attach scan)
[ ] Forms: Form-A certificates (re-signed), Form 4 power of attorney, bid form (signed)
[ ] Technical volume: pages ≤ limit (ITT 12.3); index matches Section 5 requirements
[ ] Financial volume: BOQ priced in provided Excel; overwritten cells validated
[ ] Envelope marking / submission mode: <per ITB>; address: ____
[ ] Portal/DSC: portal account active; DSC token tested 48h before close
[ ] One-envelope or two-envelope per ITT 18 — confirm before packing
```

### 3.3 Draft section (excerpt with citations)

> *"AHTE has executed 220 kV substation works for NTDC under contracts PD-EHV-24-2021 and
> PD-EHV-26-2022, encompassing complete substation extensions with associated civil, structural,
> and E&M works delivered under FIDIC-based conditions."*
> **Citations:** ProjectExperience #214, #231 (+ completion certificates KB-Art-88, KB-Art-91).
>
> *"Key substation construction equipment, including ___ crane capacity and tower erection
> tooling, is company-owned and available from Q2 2027."*
> **Status: GAP — equipment availability dates require operations confirmation before submission.**

---

## 4. Questionnaire (25 questions — please answer each)

| # | Group | Question |
|---|-------|----------|
| 1 | Sources | What percentage of tenders you pursue today are found via (a) PPRA Punjab, (b) EPADS/EPMS, (c) buyer sites, (d) newspapers, (e) other? |
| 2 | Sources | Which sources are missing from `docs/05` §2 that you check manually every week? |
| 3 | Sources | How do you handle prequalification notices today (bid them, ignore, track)? |
| 4 | Sources | Would a daily scanned inbox replace your current morning routine, or supplement it? |
| 5 | Leads | Which of L1–L8 (docs/06) would you actually act on? What prep would you want flagged? |
| 6 | Eligibility | Which knockout criteria do you check first today (PEC category, blacklist, PQ status, turnover, similar work)? |
| 7 | Eligibility | Are there tender types where you never bid (e.g., certain PEC categories, foreign JV-only, below threshold)? |
| 8 | Eligibility | How do you currently verify blacklist/debarment status (PEC/PPRA sites, past experience)? |
| 9 | Eligibility | What are the practical differences between Punjab PPRA Rules 2014 and federal PPRA Rules 2004 procedures in your experience? |
| 10 | Regimes | Which FIDIC editions/SBDs appear in your last 20 tenders (PEC civil, PEC E&M, PEC TSTE, donor SBD, other)? |
| 11 | Risk | Which contract clauses have caused the most real damage on past projects (delay damages, price adjustment, payment delays, design responsibility, dispute forum)? |
| 12 | Risk | Which risk flags should always escalate to management before Gate 4? |
| 13 | Analysis | Is the compliance matrix format (requirement ↔ evidence ↔ status ↔ owner) the right artifact for your review, or do you use another format? |
| 14 | Analysis | What does your current checklist for a typical works bid include that is missing in §3.2? |
| 15 | Analysis | When a tender is genuinely ambiguous, do you prefer system-drafted clarification questions or a list of anomalies to research yourself? |
| 16 | Workflow | Who at AHTE would realistically own Gate 1 (Go/No-Go)? Within what time? |
| 17 | Workflow | Who owns technical and commercial approval of the final bid (Gate 4)? Does the value band change the approver? |
| 18 | Workflow | Are the SLA defaults (A-14) realistic for your staffing? Which gate will bottleneck first? |
| 19 | Workflow | Should auto-archive below score 40 exist at all, or should everything reach human eyes? |
| 20 | Drafting | Which proposal sections are safe to AI-draft from the KB (project references, CVs, HSE, QA/QC) and which must never be auto-drafted? |
| 21 | Pricing | Where does pricing/cost data live today (Excel files, estimator's head, past BOQs)? What would a BOQ extraction feature need to link to? |
| 22 | Submissions | Walk through your last portal submission: what steps must our Gate 5 pack cover that a generic checklist would miss? |
| 23 | Submissions | For NTDC/WAPDA sealed submissions: courier rules, time stamps, receipt proofs — what must the pack generate? |
| 24 | Outcomes | Do you record win/loss reasons or award prices today? Who would maintain this in the system? |
| 25 | Adoption | What must be true in week 1 for you to trust this system (e.g., it never misses an NIT from PPRA Punjab)? |

---

## 5. Glossary (EN — Urdu usage)

Pakistan procurement offices commonly use English terms; this glossary maps them for non-technical
users and for Urdu-language onboarding.

| Term (EN) | Urdu (common usage) | Meaning |
|-----------|---------------------|---------|
| Tender / Bid | ٹینڈر / بولی | The offer; also the solicitation |
| NIT (Notice Inviting Tender) | ٹینڈر کا اشتہار / دعوت | The advertisement of a tender |
| IFB (Invitation for Bids) | دعوت برائے بولیاں | Donor-style advertisement |
| EOI | اظہارِ دلچسپی | Expression of Interest |
| RFP | درخواست برائے تجاویز | Request for Proposals |
| Pre-qualification (PQ) | پیشگی اہلیت | Screening stage before bidding |
| Corrigendum | ترمیمی نوٹس | Amendment to a notice/document |
| Bid security / Earnest money | ضمانتی رقم | Deposit/BG securing a bid |
| Challan | چالان | Bank deposit slip for fees |
| BOQ | بل آف کوانٹٹیز | Bill of Quantities (price schedule) |
| GCC / PCC | عمومی / خصوصی شرائطِ معاہدہ | General / Particular Conditions of Contract |
| LD (Liquidated damages) | تاخیری جرمانہ | Delay penalty |
| EOT (Extension of Time) | توسیعِ مدت | Time extension |
| JV (Joint Venture) | مشترکہ منصوبہ / جے وی | Consortium of firms |
| DSC / e-token | ڈیجیٹل دستخطی سرٹیفکیٹ | Digital signature certificate for e-submission |
| PEC | پاکستان انجینئرنگ کونسل | Pakistan Engineering Council (regulator/licenser) |
| PSDP | پبلک سیکٹر ڈویلپمنٹ پروگرام | Federal development budget |
| ADP | سالانہ ترقیاتی پروگرام | Provincial development budget |
| DAB | ڈسپیوٹ ایڈجوڈیکیشن بورڈ | Dispute Adjudication Board (FIDIC) |
| NCB / ICB | قومی / بین الاقوامی مسابقتی بولی | National / International Competitive Bidding |

---

## 6. Sign-off checklist

| # | Item | Verdict (Accept / Reject / Modify) | Comments |
|---|------|-------------------------------------|----------|
| 1 | A-register A-01 … A-22 reviewed | | |
| 2 | Worked example realistic (corrections listed) | | |
| 3 | Sample artifacts factually correct for PK practice | | |
| 4 | Questionnaire answered (or live session booked) | | |
| 5 | Source priority (D-05) confirmed or amended | | |
| 6 | Gate owners/SLAs confirmed (A-03/A-14) | | |
| 7 | FIDIC/PEC mapping acceptable (`docs/07`) | | |
| 8 | Leads sources acceptable (`docs/06`) | | |
| 9 | Assisted submission flow acceptable (D-06) | | |
| 10 | Overall: proceed to build? | | |

Signed: ______________________  Role: ______________________  Date: ____________
