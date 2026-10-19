# 09 — KSA Expansion Roadmap (Phase 3)

Audience: management (primary). Engineering deltas summarized at the end.

**Premise:** the MVP is Pakistan-specific for speed, but the architecture is generic by
`Country / Area / Category` (`docs/02` §5). Saudi Arabia is the designated second market because
its procurement environment removes the two biggest MVP constraints: **scraping** (Etimad has an
official developer API) and **assisted-only submission** (Etimad is fully electronic, including
bid submission and award).

---

## 1. Why KSA, and why it fits this architecture

| Factor | Detail |
|--------|--------|
| Market size & pipeline | Vision 2030 programs and infrastructure spend; Etimad-scale volume (~2,000 active competitions at a time; >460k awarded tenders listed). |
| Structural advantage | Etimad unifies procurement end-to-end (review, purchase RFP, e-submission, evaluation, e-award) and offers a **Developer Portal with REST APIs** — ingestion via API is more durable than scraping and allows **true e-submission** eventually. |
| Same lead play | Government Tenders and Procurement Law requires annual procurement plans published — the Leads Radar design (`docs/06`) transfers directly; Etimad also lists "upcoming tenders". |
| AHTE fit | AHTE publicly welcomes international JV/partnerships; PMC/EPC power & infrastructure works are core to KSA programs; the KB model already stores JV partnerships and multi-country project experience. |
| Generic model proof | Country/Area/Category parameters, source registry and taxonomy mappings were designed for exactly this expansion. |

---

## 2. Requirement deltas (Pakistan → KSA)

| Area | Pakistan MVP | KSA delta |
|------|--------------|-----------|
| Source ingestion | HTML connectors + email + manual | **Etimad Developer API products** (tenders, upcoming tenders, awards) + manual upload; scraping is fallback only |
| Submission | Assisted (DSC/token, challans) | **Native e-submission path** via Etimad services/APIs where the supplier account and regulations permit; assisted mode remains default until certified |
| Language | English (+ Urdu glossary) | **Arabic-first documents** (RTL, OCR for scans), bilingual UI output; Arabic-aware chunking and citation display |
| Calendar | Gregorian, PKT | **Hijri/Gregorian dual dates**; KSA working week/holidays |
| Classification | PEC categories/fields | **Saudi Contractors Authority (SCA)** classification levels and fields (analogue of PEC); map to internal taxonomy |
| Local content | PEC/FBR/blacklist checks | Add **LCGPA local-content** requirements and preferences; CR/ZATCA status checks |
| Securities | BG/challan norms | KSA bank guarantee formats and instructions; different security norms to model as checklist rules |
| Data residency | In-house server (D-08) | **PDPL/NCA**: deploy in KSA region or client-controlled KSA infrastructure; LLM provider choice revisited for residency (possible local model or KSA-hosted endpoints) |
| Currency & pricing | PKR | SAR; multi-currency projects |
| Portal accounts | Supplier registration + DSC | Etimad supplier registration, classification, and e-services onboarding (client-side task, system tracks status) |

---

## 3. Architecture deltas

1. **Country profile module** (already planned): SA regulatory profile, calendar, currency,
   languages, submission mode = `native-electronic`.
2. **API connector**: Etimad Developer Portal client — API keys per environment, product
   subscriptions, rate-plan compliance, snapshotting responses for audit. No business logic in the
   connector (P2 holds).
3. **Arabic pipeline**: OCR (Arabic-trained), normalization (hamza/taa-marbuta variants),
   RTL-aware chunking; citations displayed with original Arabic text + EN translation; drafting
   output bilingual where the tender demands Arabic.
4. **Taxonomy mapping**: SCA classes/activities + Etimad activity codes → internal categories.
5. **Deployment option**: KSA-region containers (or client on-prem in KSA) + residency-compliant
   model access; feature flags separate PK and KSA data paths cleanly (no cross-region document
   transfer).
6. **Submission module**: new `submission_mode = api-assisted` path; still gated by Gate 4/5 with
   human confirmation until regulator/client sign-off allows automation.

---

## 4. Phased plan (K1–K4)

| Phase | Content | Exit criteria |
|-------|---------|---------------|
| **K1 — Read-only API PoC** | Developer Portal account; ingest tenders + upcoming tenders into the existing model; measure coverage vs manual browsing | 200+ KSA tenders normalised; category mapping working for AHTE-relevant classes; leads from upcoming tenders validated |
| **K2 — Arabic & compliance** | Arabic extraction/scoring/drafting quality; SCA/LCGPA checks; residency deployment design approved by legal/security | Gold-set accuracy ≥ 85% on Arabic document extraction; residency sign-off |
| **K3 — Pilot with KSA-facing entity** | AHTE JV entity or partner bids a real KSA tender; gates run; assisted submission via Etimad | One submitted bid end-to-end; time-savings measured; no residency findings |
| **K4 — Native e-submission & scale** | Etimad e-submission integration (where permitted), award tracking | Human-confirmed e-submission works; operations runbook for KSA |

---

## 5. Legal, compliance & commercial considerations

- **Data residency (PDPL/NCA)**: documents, KB extracts, and AI outputs for KSA opportunities must
  not transit PK infrastructure. Plan region-pinned storage + provider endpoints or a KSA-hosted
  model; document the data-flow map for client legal review.
- **Etimad API terms**: Developer Portal has subscription/rate-plan rules — comply exactly; keys in
  managed secrets; no redistribution of bulk data beyond internal use.
- **Supplier eligibility**: Etimad participation normally requires a registered Saudi entity /
  qualifying JV; the system can track registration/classification status as KB expiries, but the
  commercial vehicle (JV, branch, subsidiary) is AHTE's business decision.
- **Language liability**: Arabic drafts are drafts; Gate 3 review by qualified Arabic reviewers
  remains mandatory (no change to the human-gate rule).

---

## 6. Open questions (carry into KSA discovery)

1. Which SCA classification level/activities does the commercial vehicle target — drives
   eligibility gates and taxonomy seed.
2. Does AHTE intend to bid as an international contractor (JV with local partner) or via a KSA
   entity — affects KB structure and e-submission account model.
3. Residency posture: KSA cloud region vs client on-prem in KSA — decides model provider and
   infra plan.
4. Whether Etimad e-submission via developer APIs is permitted for this use case (confirm with
   NCGR/Etimad through the official channel) — determines K4 feasibility vs staying assisted.
