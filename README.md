# AI-Powered Bid Management System (BMS)

[![Deploy to Vercel](https://github.com/datafyresearcher/Bid-Management-System/actions/workflows/deploy.yml/badge.svg)](https://github.com/datafyresearcher/Bid-Management-System/actions/workflows/deploy.yml)

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

### Live portal reading

The connectors can also read the authorities' own pages, so the dashboard shows what was published
today rather than what was saved earlier. Set `BMS_FIXTURES=false` and the connectors fetch
PPRA Punjab's Active Procurement grid, the federal EPMS and EPADS lists, NTDC's public tender feed
and WAPDA's tender notices. Only public pages are read, at one request every three seconds, and
nothing ever signs in to a portal. **[docs/05 §11](docs/05-pakistan-sources-and-connectors.md)
has the full setup, the runbook, and the two things to know: PPRA Punjab's portal answers only
from inside Pakistan, and the deployed review environment keeps each instance's records on that
instance, so the source register's **Scan** button reads a portal on demand.**


### Option A — Docker Compose (everything)

```bash
docker compose up --build
```

- Web app: http://localhost:3000
- API + Swagger docs: http://localhost:8000/docs

The `api` container seeds the database on first start (demo users, sources, knowledge base) and
runs the scheduled scan every hour (`BMS_SCAN_INTERVAL_SECONDS`).

### Option B — Local development

**Port configuration first.** The API reads its settings from `.env` at the
repository root *and* from `services/api/.env` (the local file wins). The web
app reads `NEXT_PUBLIC_API_URL` from `apps/web/.env.local`. Both are already
configured on this machine:

| Service | URL | Where it is set |
|---|---|---|
| Web app | http://localhost:3001 | `apps/web/.env.local` → `NEXT_PUBLIC_API_URL` |
| API + Swagger | http://localhost:8001/docs | `.env` → `BMS_CORS_ORIGINS` |

Port 3001/8001 rather than 3000/8000 because another project on this machine
already holds those two ports. If you move to a clean machine, change
`NEXT_PUBLIC_API_URL` in `apps/web/.env.local` to `http://localhost:8000` and
`BMS_CORS_ORIGINS` in `.env` to `http://localhost:3000`.

Backend (Python 3.11+):

```bash
cd services/api
python -m venv .venv
.venv\Scripts\activate            # Windows (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
python seed.py                    # demo users, sources, KB, initial scan + scoring
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8001
```

> If you move the project folder, recreate the virtualenv — a Windows venv
> records absolute paths in its console scripts, so `.venv\Scripts\uvicorn.exe`
> keeps pointing at the old location. `.venv\Scripts\python.exe -m uvicorn`
> still works, because the venv resolves its base interpreter from the system
> Python.

Frontend (Node 20+):

```bash
cd apps/web
npm install
npm run dev -- --port 3001        # proxies API at the URL in .env.local
```

### Demo credentials (fixtures mode only)

These accounts are seeded when `BMS_FIXTURES=true` — the demo pipeline. A
deployment reading the live portals seeds only the administrator, whose
password comes from `BMS_ADMIN_PASSWORD`, and everyone else is created in the
app. The sign-in screen no longer prefills any credentials; demo one-click
accounts appear only when the web app is built with
`NEXT_PUBLIC_DEMO_MODE=true`.

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

`BMS_LLM_PROVIDER` selects the backend:

| Provider | What it does |
|---|---|
| `mock` (default) | A **deterministic engine** that performs the same four tasks the LLM performs — scoring rationale, requirement extraction, risk flagging, proposal drafting — with no API key and no network. It is a reproducible baseline you can diff a real model against, and every call it serves is recorded with `simulated=True` so simulated output is never confused with measured model behaviour. |
| `openrouter` | Any OpenRouter model, via the OpenAI-compatible API. |
| `openai` | Any OpenAI model. |

Set the matching API key in `.env` and restart the API to switch:

```bash
BMS_LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-...
BMS_LLM_MODEL=openrouter/auto
```

Prompt contracts and JSON-schema validation live in `services/api/app/llm/`.
The provider layer adds bounded retries with backoff, a response cache, strict
schema validation of every structured response, prompt-injection fencing on
all third-party document text, and parallel section drafting.

**Safety property:** a missing-evidence marker found by the deterministic
writer (`[[GAP: …]]`) is re-inserted if the model drops it. The model can
rewrite a section; it cannot erase a known gap in your evidence.

### Measuring accuracy

The system ships with a labelled **gold set** — tender documents with
human-confirmed field values — and an evaluation harness that runs the real
pipeline over them and reports per-field precision, recall and F1.

```bash
cd services/api
python evaluate.py                 # table
python evaluate.py --json          # machine-readable
python evaluate.py --min-case-accuracy 0.95   # CI gate
```

Or from the Admin screen: **Admin → Extraction accuracy (gold set) → Run
evaluation**. The same run is available at `GET /api/admin/evaluation`.

The current gold set is 7 cases covering a clean PPRA ITT, a table-formatted
EPMS schedule, an NTDC notice with an ordinal date, a space-aligned WAPDA
schedule, a bilingual Urdu/English notice, a consultancy tender with no bid
security at all (the negative case that catches hallucinations), and a notice
where the submission deadline and the bid opening date differ.

**Be clear about what that number means.** The gold set is small and was
written by the same team that wrote the extractor, so it is a *regression
baseline* that protects against silent breakage — not a production accuracy
claim. A real accuracy claim needs a gold set built from AHTE's own
historical tender packages (assumption **A-01** in `docs/10`). The harness is
built and waiting for that data.

### Tests

```bash
cd services/api
.venv\Scripts\python.exe -m pytest tests -q
```

Covers the scorer, normalizer, document pipeline, leads API, the **proposal
drafting path**, one **full end-to-end pipeline** test that drives a tender
from discovery through every gate to a Won outcome over the HTTP API, and the
**gold-set accuracy regression test**.

There is also a **live smoke test** that exercises the running system over
HTTP — login, dashboard, all five gates, submission, outcome, AI quality and
the gold set:

```bash
cd services/api
.venv\Scripts\python.exe smoke_test.py      # needs the API running
# BMS_BASE_URL=http://localhost:8017 .venv\Scripts\python.exe smoke_test.py
```

## CI/CD — automatic deployment to Vercel

Every push to `main` runs `.github/workflows/deploy.yml`, which gates on quality
and then deploys both halves of the system to Vercel.

```
push to main
   └─ verify      pytest suite + gold-set evaluation (must reach 90% case accuracy) + next build
        ├─ deploy-api   services/api  → Vercel project "bms-ahte-api"
        └─ deploy-web   apps/web      → Vercel project "bms-ahte"
             └─ smoke  poll the live API /api/health and the web app
```

The deploy jobs are **serialised** by a `vercel-production` concurrency group, so
two pushes can never race to claim the production alias.

| Live target | URL |
|---|---|
| Web app (Next.js) | https://bms-ahte.vercel.app |
| API (FastAPI) | https://bms-ahte-api.vercel.app |

**Repository secrets and variables**

| Name | Kind | Value |
|---|---|---|
| `VERCEL_TOKEN` | secret | Vercel access token used by the CLI in CI |
| `VERCEL_ORG_ID` | secret | `team_xCaLHoqSXx04VvpNyOtyUS9m` |
| `VERCEL_WEB_PROJECT_ID` | secret | `prj_qYDGQK2yHvlBQes5SggeyA4OFBCP` |
| `VERCEL_API_PROJECT_ID` | secret | `prj_t8DosVYqdTm8yyxS44rDqtNC1u4q` |
| `VERCEL_WEB_URL` | variable | `https://bms-ahte.vercel.app` (smoke test target) |
| `VERCEL_API_URL` | variable | `https://bms-ahte-api.vercel.app` (smoke test target) |

Runtime configuration for each Vercel project (database URL, CORS origins,
`NEXT_PUBLIC_API_URL`, LLM provider, …) lives in the **Vercel project settings**,
not in Git, so it is never exposed in the repository.

> **Rotating the token.** Vercel access tokens are short-lived. When the pipeline
> starts failing with an authentication error, create a fresh token in
> *Vercel → Settings → Tokens* and update the `VERCEL_TOKEN` repository secret:
> `gh secret set VERCEL_TOKEN --body "<new token>"`. The pipeline needs no other
> change.

To run a deployment without pushing:

```bash
gh workflow run deploy.yml
```

## Production operations

The deployed system reads the live portals and holds real tender data. The
defaults below are what make that safe to run unattended.

### Sign-in and accounts

* **The demo passwords only exist in fixtures mode.** A deployment with
  `BMS_FIXTURES=false` seeds no accounts at all rather than creating one with
  a password printed in this repository. Create real users in *Admin → Users*.
* **Sessions are refused until the signing key is set.** Sign-in answers 503
  while `BMS_SECRET_KEY` is left at its default on a live deployment, because
  that default is in the repository and sessions signed with it are forgeable.
* **Rotate or recover the admin password with `BMS_ADMIN_PASSWORD`.** Set it,
  redeploy, sign in with the new password. On every start the API checks the
  stored hash and rotates only when it differs.
* **Failed sign-ins are rate-limited** (default 10 failures per client+account
  per 5 minutes → HTTP 429). The limit makes password guessing slow; it is
  tuned with `BMS_LOGIN_MAX_ATTEMPTS` / `BMS_LOGIN_WINDOW_SECONDS`.
* **The health endpoint hides its internals.** Anonymous callers get
  `{"status", "fixtures"}` — what the platform check and the CI smoke test
  need. Database contents and LLM configuration are reported only to a signed-in
  administrator.

### Scheduled work (daily scan + digest)

A serverless deployment has no process that wakes up on its own, so the daily
routine runs as one scheduled request, `GET /api/cron/tick` (07:00 PKT, from
`services/api/vercel.json`): read every enabled portal, run the SLA
watchdogs, score what is waiting, then send the digest.

* **It is guarded and fails closed.** The request must carry
  `Authorization: Bearer <CRON_SECRET>`; a deployment without a `CRON_SECRET`
  configured refuses cron work (HTTP 503) rather than running it for whoever
  finds the URL.
* **Enable it** by adding the secret to the repository and redeploying:
  `gh secret set CRON_SECRET --body "$(openssl rand -hex 24)"`. The pipeline
  pushes it to the API project automatically. On the Vercel dashboard it can
  also be set directly as `CRON_SECRET`.
* Docker deployments don't need the cron route: run with
  `BMS_SCHEDULER_ENABLED=true` and the in-process scheduler does the same
  work every `BMS_SCAN_INTERVAL_SECONDS`.

### Email delivery (the executive digest)

The digest is the ranked brief: the top tenders by fit score, the ones
closing within 72 hours, and the gate/queue counts — the few decisions worth
attention, not an alert list. A same-day alert also goes out when new tenders
clear screening.

* **Without SMTP settings** nothing is lost: the brief is recorded in the
  dashboard notification inbox and the send is marked `sent=false`.
* **With SMTP settings** (`BMS_SMTP_HOST`, `BMS_SMTP_PORT`, `BMS_SMTP_USER`,
  `BMS_SMTP_PASSWORD`, `BMS_SMTP_FROM`) it is emailed to `BMS_DIGEST_RECIPIENTS`,
  or to the active admin/bid-manager/management accounts when that is empty.
* **Check the configuration before relying on it:** *Admin → Digest → Preview*
  (`GET /api/admin/digest/preview`) returns the brief as it would be sent;
  `POST /api/admin/digest/send` delivers it now.

### Portal reads

Live reads verify TLS certificates by default (`BMS_LIVE_VERIFY_TLS=true`).
The one `verify=False` fallback has been removed; turning verification off is
now an explicit, logged configuration choice for a portal whose certificate
chain an inspection appliance breaks.

### Container hardening

The API image runs as a non-root user with a `HEALTHCHECK` on
`/api/health`, and its `.dockerignore` keeps local `bms.db` files and test
code out of the image.

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
│   │   ├── routers/           ← auth, dashboard, opportunities, gates, leads, kb, sources, admin, proposals, cron
│   │   ├── services/          ← workflow (state machine + gates), scorer, extractor, risk,
│   │   │                        documents, drafter, submission, leads, normalizer, jobs, audit,
│   │   │                        digest + emailer (the executive brief), risk_rules, evaluation, ai_quality…
│   │   ├── connectors/        ← source adapters (PPRA Punjab, EPMS Federal, fixture JSON, email inbox)
│   │   └── llm/               ← provider abstraction + prompts + schemas + deterministic engine
│   ├── goldset/               ← labelled tender documents + cases.json (accuracy ground truth)
│   ├── evaluate.py            ← gold-set evaluation CLI
│   ├── seed.py                ← idempotent demo seed (users, sources, KB, first scan)
│   └── tests/                 ← pytest suite incl. end-to-end pipeline + gold-set regression
└── apps/web/                  ← Next.js 15 App Router frontend
    ├── app/                   ← login, dashboard, inbox, pipeline, bid room, review queue, leads, KB, admin
    ├── components/            ← Shell (auth guard + nav)
    └── lib/api.js             ← API client + formatting helpers
```

All diagrams are Mermaid and render on GitHub / VS Code / most Markdown viewers.
