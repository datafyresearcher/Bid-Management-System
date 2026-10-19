# 07 — FIDIC, PEC & Compliance Mapping

Audience: Business Domain Expert (primary reviewer), engineering (implementer of the checks).

FIDIC is a governing framework for infrastructure works contracts. This document maps (a) which
contract regime is in play for a given Pakistani tender, (b) what the system extracts and checks,
and (c) which risks it flags for the bid team — before Gate 1/2 decisions.

---

## 1. FIDIC suite overview and where it appears in Pakistan

| Book | Full name | Design responsibility | Typical use | In Pakistan |
|------|-----------|----------------------|-------------|-------------|
| **Red Book** | Conditions of Contract for Construction | Employer designs | Building/engineering works | PEC standard bidding documents are built on FIDIC General Conditions (with PEC-mandated Particular Conditions) |
| **Yellow Book** | Conditions of Contract for Plant & Design-Build | Contractor designs | E&M plant, design-and-build | PEC design-build SBD (two-stage two-envelope) references FIDIC P&DB |
| **Silver Book** | Conditions of Contract for EPC/Turnkey | Contractor designs, fixed price/time certainty | Process/power/infrastructure with high certainty demands | Common on IPP/private power and some donor/industrial projects |
| **Emerald Book** | Underground Works | Shared | Tunnels | Rare in PK; flag-only |
| **Green Book** | Short Form | Either | Small works | Below PEC SBD thresholds in some entities |
| **MDB Harmonised (Pink)** | Red Book, MDB edition | Employer | World Bank/ADB-style banks | Used on MDB-financed works when harmonised edition adopted |
| **White Book** | Client/Consultant Services Agreement | Consultant | Consultancy | Not core to construction bids |

**Pakistan practice (verified):**
- For PSDP/local-investment works, **PEC standard bidding documents are obligatory**; they
  incorporate FIDIC-based General Conditions Part-I with PEC-varied conditions in Part-II.
- For donor-funded projects, **funding agencies' bidding documents (FIDIC-based SBDs)** are used.
- Where no PEC document applies, FIDIC or other recognized forms may be used with competent
  authority approval (e.g., WAPDA manual guidance).

---

## 2. Regime detection (automatic, from documents)

The analyzer determines the contract regime by evidence, not assumption:

| Signal | Detected as |
|--------|-------------|
| "General Conditions of Contract, Part-I" + PEC references + tender data section | PEC Standard (FIDIC-based GCC + PCC) |
| "Conditions of Contract for Construction" / "Red Book" / 1999/2017 edition references | FIDIC CONS (Red) |
| "Plant and Design-Build" / "Yellow Book" | FIDIC P&DB (Yellow) |
| "EPC/Turnkey" / "Silver Book" | FIDIC EPCT (Silver) |
| "Procurement of Works" ADB/WB SBD format + loan number (e.g., ADB-PTSP-05-2024 patterns) | Donor SBD (MDB-harmonised or agency SBD) |
| Two-envelope/design-build Pakistan formats (TSTE) | PEC TSTE (FIDIC P&DB-based) |

Detection output: `procurement_regime`, `contract_family`, `edition_if_stated`, `confidence`,
and page/clause anchors as evidence. **Misfit handling:** if edition/conditions cannot be
determined, Gate 2 marks it "regime unconfirmed — expert review required" (never guessed).

---

## 3. Compliance checks catalogue (extracted per tender)

| Check | What the system extracts | Why it matters |
|-------|--------------------------|----------------|
| Instructions to Bidders completeness | ITT clauses, addenda issued, submission method/address, envelope rules | Non-responsive bids die here first |
| Bid security | Amount, currency, validity period, acceptable forms (BG/deposit), beneficiary wording | Wrong form/validity = rejection |
| Tender fee / document purchase | Amount, challan instructions, deadline | PPRA Punjab: fee deposited before upload |
| Submission deadline & timezone | Exact date/time, opening time | Missed time = disqualified |
| Clarification/query window | Query deadline and channel | Late queries unanswered |
| Qualification criteria | Turnover multiples, similar-work value/count, personnel, equipment, JV rules, domestic preference | PEC PQ scoring (Financial 30 / Experience 35 / Personnel 15 / Equipment 20 where PQ applied) |
| Evaluation method | Single-stage one/two-envelope; pre- vs post-qualification; lowest evaluated bid | Strategy: price vs technical emphasis |
| Price adjustment & currency | Formula availability, base month, currencies | Commercial risk basis |
| Contract conditions deltas | Particular Conditions changes vs standard GCC | Risk flags (§4) |
| Completion time & milestones | Time for Completion, interim milestones, LDs | Cash-flow and penalty exposure |
| Performance security | Amount, form, release conditions | Post-award exposure |
| Insurance requirements | CAR/EAR, third-party limits, employer's requirements | Cost input + compliance |
| Law/forum | Governing law, DAB/arbitration seat | Dispute exposure |
| Donor-specific rules | E.g., ADB NCB: ≥28-day bidding period, no negotiation, no domestic preference, public opening | Procedures that override local habits |

Each check becomes rows in the **Compliance Matrix** with status, evidence anchor, and owner
(`docs/03` Gate 2).

---

## 4. Risk flags for contractors (pre-Gate 1/2 memo)

| Category | Example flags | Typical severity |
|----------|---------------|------------------|
| Condition amendments | PCC deleting/reducing contractor protections; shortened notice periods; uncapped or high liability | High |
| Time & cost | Aggressive LD caps, no price adjustment in high-inflation PKR environment, milestone-heavy payment terms | High |
| Design risk | Silver/Yellow: full design responsibility with limited site data; geotechnical exculpation clauses | High |
| Payment | Advance payment without guarantee, delayed certification, retention terms | Medium-High |
| Securities | Bid/performance security above market norms; long validity; on-demand call risk | Medium |
| Dispute | No DAB, arbitration abroad with high cost, short notice of claims windows | Medium |
| Scope ambiguity | BOQ vs scope narrative mismatch; "or equivalent" specifications; undefined interfaces (e.g., with NTDC grid ops) | Medium |
| Eligibility | Foreign JV-only restrictions, PEC category edge (value near category ceiling), missing similar-work exactness | Depends |

Output: a **Risk Memo** per opportunity (draft at analysis, reviewed at Gate 2) with severity,
evidence anchor, and suggested mitigation/question for the bid team or clarification request.

---

## 5. PEC-specific eligibility checks (deterministic hard gates)

| Check | Rule source | Gate behaviour |
|-------|-------------|----------------|
| PEC licence covers specialization | SBD eligibility clauses | Hard fail if scope outside licence fields |
| PEC category fits estimated value | PEC bye-laws (C-A = no limit; lower categories have ceilings) | AHTE C-A passes value ceilings; other entities/JVs checked when bidding in new fields |
| Active taxpayer status | FBR/provincial lists | Hard gate (status from KB, expiry-tracked) |
| Blacklist/debarment | PEC + federal/provincial PPRA lists (+ foreign/international where stated) | Hard gate; manual confirmation link shown |
| JV rules for foreign constructors | PEC + SBD clauses | Flag: JV with local registered constructor required; provisional licence path |
| Prequalification status | When PQ used, only prequalified bidders may bid | If not prequalified → screen out or re-route to PQ opportunity |

---

## 6. Donor-procedure deltas (e.g., ADB NCB — verified)

Applied by the analyzer when a donor SBD is detected; surfaced as explicit checklist notes:

- Minimum bidding period **28 days** from advertisement.
- Bids opened publicly; evaluation strictly per declared criteria; **no negotiation**; award to
  lowest evaluated (technically responsive) bidder.
- No domestic preference for domestic bidders/goods under NCB (per published clarifications).
- Government-owned enterprises only eligible under commercial-autonomy conditions.
- Rejection of all bids / rebidding requires donor concurrence.

---

## 7. Outputs of the analysis (artifacts)

1. **Compliance Matrix draft** — one row per requirement/check; statuses Covered/GAP/TBD/N-A.
2. **Risk Memo draft** — flags with severity + evidence + suggested action.
3. **Clarification questions draft** — candidate queries for the tender query window (human
   decides what to submit).
4. **Regime summary** — family, edition confidence, and any unconfirmed items for expert eyes.

All four display at Gate 2 with page/clause anchors; edits and confirmations are audited.

---

## 8. Domain assumptions to validate (see A-register in `docs/10`)

- A-07: FIDIC edition/format mix faced by AHTE (which clients use 1999 vs 2017; donor SBD
  prevalence; private EPC prevalence of Silver Book).
- A-09: PEC category ceilings and specializations mapping used for hard gates.
- A-15: Risk-flag severity defaults and which flags must always escalate to management.
- A-16: Preference for clarifications to be system-drafted vs authored entirely by humans.
