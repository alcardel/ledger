# Ledger — Credit Appraisal Workbench

A working local-first MSME and enterprise credit workbench with a configurable loan catalog. Next.js/TypeScript frontend, FastAPI backend, PostgreSQL with forced row-level security, Celery/Redis jobs, Ollama, optional Gemini extraction, and a WorkOS authentication adapter.

## Start locally

Requirements: Node 22+, Python 3.12, uv, Docker, Ollama.

```sh
cp .env.example .env                 # only for a fresh checkout; preserve existing credentials
ollama pull qwen3:8b
ollama pull qwen3-vl:4b
./scripts/dev.sh
```

The startup script creates `frontend/.env.local` from `frontend/.env.example` if absent. Keep private keys in the root `.env`; only browser-visible configuration belongs in the frontend file. Both local environment files are ignored by Git.

Open http://localhost:3000. API documentation: http://localhost:8000/docs.

The script starts a local API, a single inference worker, and the web app. PostgreSQL listens on loopback port 55432; Redis on 56379. Docker volumes persist application records. Generated documents live under `data/documents`. Rerunning the seed preserves existing cases and edits.

For a production-mode frontend, stop the dev frontend before `cd frontend && npm run build && npm start`; do not run a build against a live dev server's `.next` directory.

## Model setup

Current selected design: **local Qwen decisions; Gemini extraction when configured, otherwise local Qwen vision**. Jev is optional and not required.

Set these values in the root `.env`, never in the browser or source files:

```dotenv
DECISION_PROVIDER=local
DECISION_MODEL=qwen3:8b
EXTRACTION_PROVIDER=auto
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
OLLAMA_MODEL=qwen3-vl:4b
```

`EXTRACTION_PROVIDER=auto` uses Gemini if a key exists, otherwise local extraction. Set `local` to keep extraction local or `gemini` to require Gemini. A failed Gemini request produces an explicit failure, not a hidden provider switch. Restart the API and worker after changing `.env`.

Local judgments are not calibrated probabilities. Every assessment stores the model identity, input evidence, policy version, actual response and deterministic results. Selecting `DECISION_PROVIDER=jev` requires `JEV_API_KEY`; its adapter uses the official TypeSafe endpoint. No AI decisions are preseeded.

Gemini receives the selected document's text or rendered page when configured. Original files remain in the local vault. Use synthetic evidence for the demo.

## Authentication

Default `AUTH_MODE=demo` is an explicitly labeled local synthetic environment. It permits role previews with a local demo token and **must not be deployed publicly**. The frontend and API bind to loopback by default.

For WorkOS:

1. Set `AUTH_MODE=workos`, `WORKOS_CLIENT_ID`, `WORKOS_API_KEY`, and a random `SESSION_SECRET` of at least 32 characters.
2. Register `http://localhost:8000/api/v1/auth/callback` as the local redirect URI.
3. Create organization roles with slugs `org_admin`, `relationship_manager`, `credit_analyst`, `credit_approver`, `policy_manager`, and `risk_reviewer`; assign active organization memberships.
4. Restart services and use **Audit & Administration → Sign in with WorkOS**.

WorkOS organization membership determines tenant and role. Demo headers are rejected in WorkOS mode. Staff case assignment is enforced by the API; administrators cannot cross organization boundaries. The seed belongs only to `demo-bank`; WorkOS organizations start empty and need an initial policy and applications. WorkOS end-to-end sign-in requires your account configuration; it cannot be verified without credentials.

The application database role is non-superuser and cannot bypass RLS. Owner/migration credentials are used only by the local bootstrap. PostgreSQL triggers prevent updates/deletes to audit events, overrides, assessments, approvals, facts, and published policies.

## Main workflows

- **Origination:** create an application, upload PDF/image/CSV documents, run extraction, verify source-linked facts.
- **Financials:** decimal calculations with missing/zero-denominator handling; cash-flow review with manual transaction categorization and exclusion.
- **Credit policy:** add extraction fields, calculations and nested rule conditions; ask local Qwen to draft a validation; save a draft, simulate against cases, and publish a version.
- **Appraisal:** queue a real local-model assessment and inspect its recommendation, policy gates and input snapshot. A changed evidence revision makes an assessment stale.
- **Decision:** officers cannot self-approve or bypass blocking gates. Administrators use an explicit reasoned override, including for their own cases or their own policy publication.
- **Exceptions:** resolve or explicitly accept an exception. Original failures remain in the assessment.
- **Audit:** inspect original decisions, subsequent overrides, actor, reason and timestamps. Repeated idempotency keys do not create duplicate decisions.

## Verification

```sh
.venv/bin/pytest backend/tests -q
cd frontend
npm run typecheck
npm run build
node browser-check.cjs              # with API and frontend running
```

PostgreSQL tests require the local database. Unit/API tests use isolated in-memory data. Browser screenshots and live probe results are written to ignored `artifacts/`.

## Structure

- `backend/app/engine.py`: bounded financial expressions and policy evaluation; no eval or user code execution.
- `backend/app/main.py`: versioned API, authorization and transaction boundaries.
- `backend/app/tasks.py`: durable job records and background processing.
- `backend/app/providers.py`: local, Gemini and Jev adapters.
- `backend/migrations`: database RLS and immutable-history migration.
- `frontend`: dashboard, application workbench and configurable policy editor.
- `docs`: demonstration script, architecture notes and pitch material.

## Operational limits and scaling

This is a working local demo foundation, not production-certified lending infrastructure. It has a generic versioned record store with indexed tenant/kind/parent columns. Before a high-volume pilot, split high-volume transactions into dedicated tables, add retention/backup/restore operations, tested SSO lifecycle handling, malware scanning, object storage, stronger job recovery, organization provisioning, comprehensive document-specific extraction benchmarks, and load testing.

Uploads support English/INR demo evidence up to 25 MB and 100 PDF pages. Password-protected PDFs currently require an unlocked replacement. New file connectors, full bank-specific statement parsers, multilingual/currency normalization, and unrecognized formula operators require development; these do not silently pass as supported.


## Expanded loan catalog and manual credit bureau entry

Loan Products & Pricing contains 12 illustrative products: MSME term, working capital, personal, education, two-wheeler, car, home, gold, loan against property, equipment, commercial vehicle and agriculture. Administrators can add additional product definitions without deployment and configure required evidence, base rate, spread, floor/cap, tenure and flat/monthly reducing interest. Product changes require a reason and are audited. Applications snapshot their pricing and evidence requirements; subsequent settings changes do not reprice existing applications. Specialized repayment schedules (moratoria, seasonal payments, balloon payments, floating-rate resets), fees, taxes and effective APR are not yet implemented. The calculator labels these limits explicitly.

Manual credit bureau entry is available in each application's summary. Officers record the report subject, role, date, source explanation, optional uploaded report, personal score or business rank, arrears and overdue balance. Missing scores remain missing; they do not become zero. Entries preserve history and trigger reassessment. Co-applicant/guarantor reports stay separate. Business report dates and arrears do not replace personal report fields. Manual data is **not** a live CIBIL verification.

Roopya appears in Audit & Administration as an integration option with onboarding pending. No bureau request is sent and no live connection is claimed. Its authenticated API transport remains to be implemented and verified against the supplied onboarding contract before enabling live pulls.

Run `.venv/bin/python -m app.retail_demo` once to add the retail samples and illustrative retail policy. There are 30 initial synthetic applications across 12 product types; acceptance tests may add clearly named test cases. Retail policy demonstrates FOIR and selected collateral LTV checks separately from business ratios. Product-specific underwriting thresholds, custom-product rule coverage and specialized lending workflows must be configured and validated by the institution.

Additional browser verification: `node workflow-check.cjs` and `node retail-check.cjs` from frontend with services running. These intentionally create synthetic test records and preserve their audit history.

### Module navigation and queues
Each module has a shareable route (for example `/credit-overview`, `/approval-workbench`, `/exceptions-referrals`, `/credit-policy`). Applications retain their originating module at `/<module>/applications/<application-id>/<tab>`. Browser history restores tabs and list filters; refreshing a deep link restores the same case. Policy editor tabs are recorded in the `editor` query parameter. Internal metric keys are hidden from financial tables; hover or focus the information control to inspect the formula.

Module queues use `/api/v1/approval-workbench/applications`, `/api/v1/document-review/applications`, `/api/v1/financial-spreading/applications`, `/api/v1/cash-flow/applications`, and `/api/v1/employee-assignments`. They share the existing tenant and case-visibility enforcement. Origination, exceptions, policies, products, administration and overview retain their separate resource APIs. API contracts are available at `http://localhost:8000/docs`.

Customer obligations are entered through **Review previous loans**. Reviewed schedules retain lender, active/closed status, EMI, outstanding amount, reported days past due and source-supported repayment notes. Unknown obligations remain missing until reviewed; zero requires an explicit no-loans confirmation. Proposed EMI comes from saved application pricing. Financial formulas can be edited under **Credit Policy → Financial calculations → Edit formula**, then saved, tested and published as a new policy version.

Application intake now collects borrower/facility details, displays the product’s required document checklist and asks whether evidence is ready. “No” offers an explicit Draft confirmation; “Yes” creates the application and guides uploads by document type, saving progress after each successful upload. Upload errors remain on the current step. Officers may finish later from the Documents tab. Creation and upload retries reuse idempotency keys. All select controls use the shared `InlineSelect` component; options expand in document flow and support keyboard navigation, rather than opening native system menus.

### Business-only lending scope
The active catalog now supports MSME and Enterprise borrower segments, each using business term loans or working capital. New applications persist `business_segment` (`msme` or `enterprise`). Existing original MSME business cases default to MSME in queue summaries. Other products are excluded from active queues, dashboard totals and origination, and cannot be recreated through the product API. Historical applications and immutable evidence/policies remain in storage. Policy working copies are scoped to business facilities; changing a published policy still requires testing and publication. The startup script no longer seeds retail applications.
