# AI-Powered Bid Management System (BMS)

**Design & Architecture Documentation Pack — Pakistan MVP, KSA expansion path**

| | |
|---|---|
| Status | MVP built — design docs + running system (FastAPI API + Next.js web app) |
| Date | October 2026 |
| Pilot user / client context | AHTE — Al-Hussain Traders & Engineers (Pvt.) Ltd., EPC contractor (power transmission lines, substations, civil infrastructure), PEC C-A (No Limit) |
| Primary market | Pakistan (Punjab priority, then Federal) |
| Expansion market | Kingdom of Saudi Arabia (Etimad platform) |
| Author | Engineering & Solution Design team |
| Reviewer | Business Domain Expert (procurement / tendering / FIDIC) — see `docs/10` |

---

## What this repository contains

This pack is the complete design for an AI-powered Bid Management System that automates the
opportunity-to-submission lifecycle for infrastructure contractors: **search procurement sources,
download and analyse tenders, run human review gates, prepare proposals grounded in the company
knowledge base, track unpublished leads, and support compliant submission.**

It is written to be handed to a **Business Domain Expert** (tendering/procurement professional)
for validation before any production code is written. Every domain assumption is collected in
`docs/10` with an explicit "validate?" question.

## Document index

| # | Document | Purpose | Primary reader |
|---|----------|---------|----------------|
| 00 | [Executive Summary](docs/00-executive-summary.md) | One-page problem, solution, value case, decisions needed | Management, client |
| 01 | [Research & Lessons Learned](docs/01-research-lessons-learned.md) | International platform research, Pakistan & KSA market study, AHTE profile | All |
| 02 | [Solution Architecture](docs/02-solution-architecture.md) | Layered architecture, components, LLM abstraction, security, deployment | Engineering, technical reviewer |
| 03 | [Workflow & Human Gates](docs/03-workflow-human-gates.md) | End-to-end state machine, 5 human review gates, automation matrix, dashboards | Domain expert, engineering |
| 04 | [Data Model & Knowledge Base](docs/04-data-model-and-knowledge-base.md) | Canonical opportunity model, company knowledge base, evidence linking | Engineering, domain expert |
| 05 | [Pakistan Sources & Connectors](docs/05-pakistan-sources-and-connectors.md) | Source matrix (PPRA Punjab, EPADS, NTDC/WAPDA, newspapers), connector design, admin registry | Engineering, domain expert |
| 06 | [Unpublished Leads Pipeline](docs/06-unpublished-leads-pipeline.md) | Pre-publication lead sources (annual plans, ADB pipelines, PSDP/ADP), lead lifecycle | Domain expert, management |
| 07 | [FIDIC & Compliance Mapping](docs/07-fidic-contract-and-compliance-mapping.md) | FIDIC suite mapping, PEC/FIDIC compliance checks, risk flags | Domain expert |
| 08 | [Pakistan MVP Scope](docs/08-pakistan-mvp-scope.md) | In/out scope, milestones, acceptance criteria, risks | Management, engineering |
| 09 | [KSA Expansion Roadmap](docs/09-ksa-expansion-roadmap.md) | Etimad API, Arabic NLP, SCA, data residency, phase plan | Management |
| 10 | [Domain Expert Review Pack](docs/10-domain-expert-review-pack.md) | Assumptions register, worked AHTE example, 25-question review questionnaire, EN-UR glossary | Business Domain Expert |

## How to review (recommended reading order)

1. **Domain expert**: `00` → `03` → `10` (do the questionnaire) → then `05`, `06`, `07` for detail.
2. **Management**: `00` → `08` → `09`.
3. **Engineering**: `02` → `04` → `05` → `03`.

Feedback is captured against the **Assumptions Register (A-register)** and **Questionnaire** in
`docs/10`. No production code starts until the A-register has owner sign-off.

## Locked decisions (decision log)

| ID | Decision | Made by | Date |
|----|----------|---------|------|
| D-01 | Deliverable this phase: documentation pack only; code after domain review | Project sponsor | Oct 2026 |
| D-02 | Single shared workspace (single-tenant) for MVP; multi-tenant deferred | Project sponsor | Oct 2026 |
| D-03 | Notifications: dashboard-only (no email in MVP) | Project sponsor | Oct 2026 |
| D-04 | Admin tooling: DB-driven source registry + admin screen with adapter templates and "Test Fetch"; complex sources remain code adapters | Architecture team (delegated) | Oct 2026 |
| D-05 | Priority source: Punjab PPRA (Provincial), then Federal EPADS/EPMS + NTDC/WAPDA | Project sponsor | Oct 2026 |
| D-06 | Submission: assisted submission in MVP (portal requires DSC/token); KSA phase enables true e-submission via Etimad | Project sponsor | Oct 2026 |
| D-07 | LLM hosting: OpenRouter (free tier) for build/testing; OpenAI API for production; provider abstraction required | Project sponsor | Oct 2026 |
| D-08 | Deployment: development local (Docker Compose); production on in-house server; KSA later in-region | Project sponsor | Oct 2026 |
| D-09 | Pakistan-first MVP; architecture stays generic (Country / Area / Category inputs) for KSA expansion | Project sponsor | Oct 2026 |
| D-10 | MVP implementation authorized (fixtures-demo mode, mock LLM by default); domain review runs in parallel and feeds the A-register | Project sponsor | Oct 2026 |

## Running the MVP

The system ships in **fixtures mode** out of the box: a curated set of tender listings + tender
documents (modeled on PPRA Punjab, EPMS Federal, NTDC/WAPDA) is loaded from `fixtures/`, so the
full pipeline — discovery → analysis → 5 human gates → proposal drafting → submission pack — runs
end-to-end without any external portal access or LLM key.

### Option A — Docker Compose (everything)

```bash
docker compose up --build
```

- Web app: http://localhost:3000
- API + Swagger docs: http://localhost:8000/docs

The `api` container seeds the database on first start (demo users, sources, knowledge base) and
runs the scheduled scan every hour (`BMS_SCAN_INTERVAL_SECONDS`).

### Option B — Local development

Backend (Python 3.11+):

```bash
cd services/api
python -m venv .venv
.venv\Scripts\activate            # Windows (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
python seed.py                    # demo users, sources, KB, initial scan + scoring
uvicorn app.main:app --reload --port 8000
```

Frontend (Node 20+):

```bash
cd apps/web
npm install
npm run dev                       # http://localhost:3000 (proxies API at localhost:8000)
```

### Demo credentials

| Email | Password | Role |
|---|---|---|
| `admin@ahte.local` | `admin123` | Admin |
| `bm@ahte.local` | `bid123` | Bid Manager |
| `engineer@ahte.local` | `prop123` | Proposal Engineer |
| `finance@ahte.local` | `fin123` | Finance |
| `mgmt@ahte.local` | `mgmt123` | Management |
| `viewer@ahte.local` | `view123` | Viewer |

### Suggested demo walkthrough

1. Log in as **bm@ahte.local** → Dashboard shows new opportunities + pending gates.
2. Open **Inbox** → the seeded PPRA Punjab listings; open the GSS substation tender (score ≈ 68).
3. **Bid room → Analysis** → factor scores, risk flags, recommendation; optionally re-run analysis.
4. **Review queue** → approve **Gate 1 (Go/No-Go)**.
5. Continue as **engineer@ahte.local**: confirm scope (G2), approve technical (G3) after KB-grounded
   proposal sections are generated.
6. As **mgmt@ahte.local**: approve commercial (G4) → Gate 5 submission checklist is opened.
7. As **bm@ahte.local**: mark the bid **Submitted**, then record the outcome (Won/Lost) — feedback
   flows into the AI-quality metrics and KB gap report.
8. Check **Leads** (pre-publication signals), **Knowledge Base** (profile/projects/certificates/…),
   and **Admin** (users, category mappings, AI quality, audit log CSV export).

### LLM configuration

Default `BMS_LLM_PROVIDER=mock` — deterministic extraction/summaries, no external calls; AI-quality
metrics show "0 calls". To enable real LLM drafting set `BMS_LLM_PROVIDER=openrouter` (free tier)
or `openai` plus the matching API key in `.env`, then restart the API. Prompt contracts and
JSON-schema validation live in `services/api/app/llm/`.

### Tests

```bash
cd services/api
.venv\Scripts\python.exe -m pytest tests -q
```

Covers the scorer, normalizer, document pipeline, leads API, and one **full end-to-end pipeline**
test that drives a tender from discovery through every gate to a Won outcome over the HTTP API.

## Key terminology

See the EN-UR glossary in `docs/10-domain-expert-review-pack.md#glossary`.
Core terms used throughout: **Opportunity** (a published tender tracked by the system),
**Lead** (a pre-publication signal), **Gate** (a mandatory human review checkpoint),
**KB** (Company Knowledge Base), **Connector** (software adapter for one procurement source).

## Repository layout

```
BID Management System/
├── README.md                  ← this file (index + decision log + run guide)
├── docker-compose.yml         ← api + web services
├── .env.example               ← all configuration knobs
├── docs/                      ← design documentation pack (00–10)
├── fixtures/                  ← curated demo data (listings + tender documents + leads)
├── services/api/              ← FastAPI backend
│   ├── app/
│   │   ├── main.py            ← app factory, CORS, scheduler hook
│   │   ├── config.py  db.py  models.py  security.py  serializers.py
│   │   ├── routers/           ← auth, dashboard, opportunities, gates, leads, kb, sources, admin, proposals
│   │   ├── services/          ← workflow (state machine + gates), scorer, extractor, risk,
│   │   │                        documents, drafter, submission, leads, normalizer, jobs, audit…
│   │   ├── connectors/        ← source adapters (PPRA Punjab, EPMS Federal, fixture JSON, email inbox)
│   │   └── llm/               ← provider abstraction + prompts (mock / OpenRouter / OpenAI)
│   ├── seed.py                ← idempotent demo seed (users, sources, KB, first scan)
│   └── tests/                 ← pytest suite incl. end-to-end pipeline test
└── apps/web/                  ← Next.js 15 App Router frontend
    ├── app/                   ← login, dashboard, inbox, pipeline, bid room, review queue, leads, KB, admin
    ├── components/            ← Shell (auth guard + nav)
    └── lib/api.js             ← API client + formatting helpers
```

All diagrams are Mermaid and render on GitHub / VS Code / most Markdown viewers.
