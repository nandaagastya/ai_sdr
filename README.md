# AI SDR Platform — Prototype

**Moving to another laptop?** Follow [the laptop setup guide](docs/LAPTOP_SETUP.md).
Restore the database and `.env` through a private transfer, not GitHub.
**Do not run `seed.py` on an existing installation: it deletes existing data.**
Email sending remains simulated; Gmail, Google Calendar, and Salesforce are not connected.

A working prototype of an AI SDR (Sales Development Representative) platform:
software that automates the full sales-development pipeline — prospecting,
outreach, reply handling, call prep, booking, and post-call logging —
leaving only the live phone call to a human rep.

This is not a personal productivity tool; it's the backend for a product
meant to be sold into a specific vertical first (Salesforce consulting
firms) before expanding.

## Architecture

**Target shape:** an orchestrator plus seven sub-agents, all sharing one
Postgres/SQLite data layer, with eventual Salesforce/HubSpot sync through
this same Flask backend.

```
                    Orchestrator
   ┌──────┬──────────┬──────────┬─────────┬──────────┬────────────┐
Prospecting Outreach Reply/Qual Call-Prep Booking Post-Call-Log Learning-Loop
   (LIVE)   (stub)    (stub)    (stub)    (stub)    (stub)        (stub)
```

Only **Prospecting** is fully wired up in this prototype — it makes a real
call to the Apollo.io organization search API, scores results with a
transparent rules-based ICP-fit scorer, and upserts them into the shared
schema. Outreach now supports saved template-based previews at /outreach, without delivery. The remaining planned agents are represented as `AgentRun` audit records
so the data model and dashboard already reflect the target shape; wiring
each one up is the next milestone (see "On the horizon" below).

**Why rules-based scoring, not ML:** debuggability and client trust. A
rep — or a client evaluating the product — can see exactly why an account
scored the way it did.

**Why the human stays on the phone:** deliberate positioning, not a
missing feature. It's the one part of the funnel a client won't want fully
automated, and it's a smaller build.

## Data model

Five shared models (`app/models.py`):

| Model      | Purpose                                              |
|------------|-------------------------------------------------------|
| `Account`  | A company / ICP target, with its fit score and stage |
| `Contact`  | A person at an Account                                |
| `Activity` | A logged interaction (email, reply, call, note)       |
| `Task`     | A follow-up action, agent- or human-owned             |
| `AgentRun` | Audit record of one execution of one agent            |

## API (6 read endpoints + 1 prospecting trigger)

| Method | Path                    | Purpose                                   |
|--------|-------------------------|---------------------------------------------|
| GET    | `/api/accounts`         | List accounts (optional `?stage=`)         |
| GET    | `/api/accounts/<id>`    | One account with contacts/activities/tasks |
| GET    | `/api/contacts`         | List contacts (optional `?account_id=`)    |
| GET    | `/api/tasks`            | List follow-up tasks (optional `?status=`) |
| GET    | `/api/agent-runs`       | Audit trail of every agent execution       |
| GET    | `/api/pipeline`         | Aggregate stage counts + avg ICP score     |
| POST   | `/api/prospect/run`     | Trigger a live Apollo prospecting run      |

## Dashboard

`GET /` shows open tasks (earliest due first), outreach drafts needing review,
and main prospects with a contact and an outreach shortcut. Tasks can be marked
done. The overview shows up to five tasks; `/tasks` lists all open tasks. Main
prospects show up to eight non-closed companies, ordered by fit score and then
newest first. Newly imported companies are marked as not yet assessed.
Architecture diagrams and execution logs are absent from the user dashboard.
Apollo search remains available through **Find companies** at `/leads/discover`;
execution audit records remain available through `/api/agent-runs`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then add your real APOLLO_API_KEY

# Optional, ONLY for a disposable database: python seed.py (deletes existing data)
python run.py                      # http://localhost:5000
```

Without an Apollo key, everything works except the "Run prospecting
agent" button — the dashboard and API are fully browsable off the seeded
data.

## Apollo integration notes (`app/agents/prospecting.py`)

- Auth must be confirmed before trusting a "no results" response — a
  bad/missing key fails silently rather than raising an error.
- Organization *search* (this prototype) is the right call before
  scoring; per-domain *enrichment* (a separate, credit-costed call) is
  meant to run downstream, only on orgs that already clear the ICP bar.
- Working search parameters:
  ```json
  {
    "q_organization_keyword_tags": ["Salesforce consulting"],
    "organization_num_employees_ranges": ["51,200", "201,500"],
    "organization_locations": ["United States"],
    "per_page": 10
  }
  ```

## On the horizon

1. Outreach agent (sequenced email/LinkedIn touches)
2. Reply / qualification agent
3. Call-prep agent (brief generation ahead of the human call)
4. Booking agent
5. Post-call logging agent
6. Learning-loop: feed real outcomes (booked vs. ghosted, objection type,
   deal risk) back into ICP/signal scoring
7. Web-scraping lead source alongside Apollo (company sites, directories, LinkedIn)
8. Salesforce / HubSpot sync


## Verified baseline and limitations

See [build roadmap](docs/ROADMAP.md) and [import review](docs/IMPORT_REVIEW.md).
Run offline tests with: python -m unittest discover -s tests -v
Tests use an isolated database and mocked Apollo responses.

Running seed.py **deletes all existing tables and data in DATABASE_URL**.
Use it only with a disposable demo database. Demo contacts use reserved
.example domains; all seeded execution records are simulated.
The development server binds to localhost with debugging disabled.
Authentication, client isolation, migrations, and production serving remain
unimplemented. Live Apollo compatibility has not been verified in this import.
Repository visibility remains private; open-source licensing is pending.


## Outreach previews

Open http://127.0.0.1:5000/outreach or choose **Create outreach preview**
on the dashboard. Pick a contact, enter your name and a factual offer, and
generate three draft emails (suggested days 0, 4, and 9). Contacts are ordered
by company ICP score, then decision-maker status. Existing contacts at any
pipeline stage can be previewed; this is not live-send eligibility logic.

Drafts use versioned templates in app/prompts/outreach and require no AI or
email API key. Each intentional generation saves an outreach_preview Activity
and an outreach AgentRun. Refreshing the result does not regenerate it.
Recent previews are linked from the dashboard.

The API is POST /api/outreach/preview with JSON fields contact_id (integer),
sender_name (up to 100 characters), offer (up to 600 characters), and optional personalization (template or ai).
Success returns HTTP 201, the saved activity and run IDs, and three messages.
Invalid input returns HTTP 400. Generation errors return HTTP 500 and close
the execution audit as an error.

Nothing is sent or scheduled; no tasks are created or pipeline stages changed.
Existing SQLite databases work without reseeding or schema changes.
This is the preview portion of Phase 1, not a complete sending agent. Provider
integration, opt-outs, cadence execution, send idempotency, and live-send
eligibility are still pending. Do not expose the unauthenticated prototype publicly.


### Optional AI personalization

Templates remain the default. To enable the **AI-written opening** option, set
`OPENAI_API_KEY` and `OPENAI_MODEL` in your local `.env`, then restart Flask.
Choose a Responses API model supporting Structured Outputs. No new dependency
or database migration is required. Existing saved previews now display their
activity number, including previews created before this fix.

Select AI-written opening in the form, or add `"personalization": "ai"` to the
preview API payload. This generates only the first email's opening paragraph;
the supplied offer, template subjects, follow-ups, and suggested days stay intact.
Company name, industry, contact title, and the offer are sent to OpenAI; recipient
email and sender name are excluded. AI calls can incur provider charges.
The integration uses `store: false` and the
[Responses Structured Outputs format](https://developers.openai.com/api/docs/guides/structured-outputs).
The prompt restricts claims to supplied facts, but generated text still requires
human review. It does not research prospects or verify claims.

Saved AI previews include the model, prompt version, and returned token usage;
usage is also recorded in AgentRun. Missing configuration returns HTTP 400 before
any provider call. Provider errors, refusals, incomplete or invalid output return
HTTP 500 and an error audit, without a partial preview or silent template fallback.
There is a 5-second connection / 45-second read timeout and no automatic retry.
Refreshing a saved preview never calls the provider again. Tests use mocked
provider responses; live AI generation has not been verified.

### Draft editing and approval

Open a saved preview and expand **Edit these drafts** to change all three
subjects and bodies. Save edits before choosing **Approve saved draft**.
Approval marks only the saved revision; it never sends or schedules email.
Changed content clears approval. **Return to draft** revokes approval without
changing the text. Revision history preserves previous content and status.
Existing previews start at revision 1 in draft status without a migration.
Edits and reviews make no provider calls and incur no AI token usage.

`POST /api/outreach/previews/<id>/review` accepts `action` (`save`, `approve`,
`reopen`) and the current integer `revision`. For `save`, supply `messages`
as three objects containing only `subject` (1–200 characters) and `body`
(1–5000 characters). The server preserves recipients and suggested days.
Stale revisions return 409; invalid input returns 400; missing previews return
404. Unchanged saves and repeated current-state approvals are no-ops.
Browser review forms use session CSRF tokens. The prototype still has no user
accounts, so approvals are not attributed to authenticated reviewers.

### Review queue

Open `/outreach/queue` or choose **Review all previews** on the dashboard.
Filter by **Needs review** or **Approved**, or search company, recipient,
first subject, or preview number. Counts reflect the current search. Results
show newest previews first, 20 per page, with links to edit and approve each
saved sequence. Reopening or editing approved content returns it to Needs review.
The queue is read-only and uses no AI tokens. Existing previews default to draft
status. This prototype parses saved JSON summaries in Python; a large production
queue should move searchable review fields into indexed database columns.


## Lead-file import

Open **Import leads** (`/leads/import`). Upload, match columns, inspect the row
preview, then explicitly confirm. Company and Email are required; optional
fields are first/last name, title, website, industry, employees, and location.
The downloadable CSV template gives the expected structure.

Supported: UTF-8 CSV/TSV (comma, tab, semicolon, or pipe delimiters), XLSX first
worksheet, DOCX first table (or delimited paragraph rows), and selectable-text
PDF tables (up to 20 pages). Files must have a unique header row and one lead
per row. Maximum 5 MB, 1,000 leads, and 50 columns. Scanned PDFs, images, old
XLS/DOC formats, and arbitrary prose are not supported. PDF column extraction
is best-effort and must be checked in the preview. No OCR or AI service is used.

Duplicate emails are skipped case-insensitively, including repeats in the file.
Existing company domains are matched first, then unambiguous company names.
Existing company/contact fields and pipeline stages are not overwritten.
New companies enter `new` with fit not yet assessed. Invalid rows are skipped
and reported; duplicate status is rechecked at confirmation. Import writes
are atomic and repeated confirmation of the same batch does not add duplicates.
The prototype does not yet guarantee deduplication across simultaneous imports
from different browser sessions; serialize imports until database-level contact
uniqueness and normalized company keys are introduced.

A new `lead_imports` staging table is created by the app factory without
replacing existing tables. Original files are not saved. Extracted staging rows
are session-owned, expire after 24 hours, and are cleaned on the next upload;
confirmed imports discard staged data and retain a count receipt plus an audit
record. Restart the app after installing requirements. Never reseed existing data.


### Web-first and optional Apollo discovery

Open `/leads/discover`. Scan up to five supplied company URLs, or extract company links from one public directory and select up to five to scan. The scanner reads the supplied page plus up to two contact/about/team pages, extracts published same-domain email addresses, and shows source links before you save selected results. Existing leads are deduplicated; web saves preserve existing company fields. Company names are suggestions to review, and published inboxes are not verified decision-maker contacts. This version does not perform keyword search across the internet or render JavaScript-only sites.

Apollo remains an explicit separate button using the official organization-search API. Enter specific domains for targeted lookup, or leave them blank for the existing Salesforce consulting filters. Successful identical searches are cached for 24 hours, with a manual refresh option and request count shown in the UI. Web scans never fall back to Apollo or AI. Apollo may charge credits for fresh calls; request counts are not a credit-balance estimate. Concurrent fresh searches are not coalesced in this prototype.

Web reads honor robots rules, rate-limit requests, cap page sizes, skip blocked sites, and validate/pin public destination IPs while retaining TLS verification. No login-required pages or access-control bypasses are supported. Successful web results also cache for 24 hours. Review batches and source records use additive database tables; do not rerun `seed.py`. Email sending remains disabled.

Validation: 40 unittest tests pass. Browser verification uses isolated synthetic provider responses; a separate real read of example.com verified the public transport without Apollo or AI calls. Endpoint reference: https://docs.apollo.io/reference/organization-search


### Status milestone

Company `fit_status` is separate from contact `pipeline_stage` and outreach `review_status`. Apollo scoring updates fit only. The existing account `stage` remains company history for compatibility; it must not drive future contact automation. `/api/pipeline` returns separate company-fit and contact-progress counts alongside legacy company-stage counts.

Startup applies version `001_separate_fit_and_progress` once. Existing file-backed SQLite databases receive a consistent `.before-status-*.bak` backup before columns are added. Original account stages are retained in `legacy_stage`; old ICP-derived `qualified` becomes `new`, while booked/other progressed company history remains unchanged. Contacts on those progressed companies become `needs_review`, because company history cannot identify which individual was contacted. Fresh contacts default to `not_contacted`.

The internal transition function requires expected current state and a source event reference, writes an activity in the caller's transaction, and rejects invalid/stale transitions. It is not exposed as a public endpoint. Future agents must validate provider evidence before invoking it. Manual reconciliation of legacy `needs_review` contacts remains future work. PostgreSQL execution and concurrent startup migrations have not been validated; this migration is for the current single-process prototype.

Validation: 42 tests pass, including repeat migration, preserved legacy history, approval independence, and rejected duplicate transitions. No live sending is enabled.


### Lead quality milestone

New Apollo assessments and newly created web/import companies share `app/services/lead_quality.py` rules `icp-v2`. Missing data earns zero points. Salesforce-services points require an explicit Salesforce plus consulting/implementation/services/integration industry description; company names and generic consulting alone do not qualify. Strong fit requires target employee size, explicit Salesforce-services evidence and an explicitly supplied US location. The score measures supplied evidence, not probability or independent verification. Location strings not matching the supported country labels receive no US points.

Dashboard “Why this fit?” exposes each rule and version. Domain presence does not verify email delivery; common role inboxes are labeled likely shared and all emails remain unverified. Partial Apollo responses preserve existing non-empty facts and booked company history. Older saved assessments are labeled as previous assessments; this milestone does not silently rescore the existing database. Web/import matches preserve existing account facts and assessments. Broad keyword web discovery, verified contact enrichment, and bulk reassessment remain separate work.

46 tests pass, including contrasting ICP cases, invalid inputs, source-independent scoring and partial Apollo preservation. Browser demonstrations use synthetic data. No live provider calls or sends were needed.


### Recipient-aware outreach previews

New previews use outreach-v2 templates and personalization-v2 instructions. Named contacts use their supplied first name and usable title. Likely shared inboxes and unnamed contacts receive team wording; placeholder titles such as Public website contact are omitted from template and AI context. Shared inbox detection is a conservative common-address heuristic, not verified ownership. The preview stores its recipient category and supplied personalization facts for review. Existing saved text and approvals are not regenerated.

48 tests pass, including shared/named/unnamed wording and a simulated failed AI attempt that preserves an existing approved preview byte-for-byte with no automatic retry. AI output still requires human factual review; instructions are not a factual verification system. Sending remains off.


### First-touch delivery simulation

Approved previews expose an explicit local simulation action. It freezes the approved recipient/message/revision in a DeliverySimulation receipt, records a fake provider ID and audit run, and leaves contact progress unchanged. A unique preview/revision/touch constraint and transactional draft comparison protect against duplicate receipts and stale approvals. Repeating a successful simulation reuses its receipt. The fake provider has no network or credential access.

50 tests pass, including draft/stale-revision rejection, duplicate reuse, unchanged contact progress, CSRF and provider-failure rollback. Browser verification clicked twice and retained one identical simulated receipt. This does not establish real-provider exactly-once delivery: real transport, uncertain-outcome reconciliation, sending eligibility/suppression, schedules, delivery webhooks and inbox verification remain unimplemented. Real sending remains disabled. New tables are additive; do not run seed.py.


### Outreach eligibility and stop controls

Before a new simulated receipt, the app rechecks recipient identity, email syntax, contact progress, company history and email-level suppression. First-touch simulation requires not_contacted and no progressed company history. The UI shows the blocking reason. Manual pause/lift controls use CSRF and audit activities; lifting a pause cannot clear unsubscribe/bounce suppression. Internal unsubscribe/bounce rules exist, but live inbound/provider events are not connected. Suppression applies across duplicate contacts with the same normalized email. A retry of an existing simulation may return its historical receipt without a new provider action.

54 tests pass. This is a single-process SQLite simulation gate, not real sending authorization. Live-send locking, provider event ingestion, schedules and follow-up cancellation still need implementation. No emails sent. Browser demonstration verified the booked-company block and a manual pause.


### Reply review preview

`/replies/review` analyzes pasted text locally with reply-rules-v1, suggests interested/not interested/out-of-office/referral/unsubscribe or needs review, and shows matched phrases. Recognized quote/history markers are excluded. Mixed/unclear intent requires review; potential mixed opt-outs recommend holding outreach. All suggestions require a human: this is a small English phrase classifier, not reliable unrestricted email understanding. Qualification fields remain unknown.

57 tests pass. Browser-verified interested and mixed-intent examples. Pasted content is not persisted or sent to a provider. Inbox OAuth, sender/thread matching, durable events, opt-out persistence and automated qualification are still pending; this screen does not update contacts or suppression.


### Reviewed reply recording

The reply screen now supports explicit recording after a human selects an outcome and supplies a sender email. Exactly one saved contact must match; absent or ambiguous matches are rejected without writes. Analysis alone remains read-only. Recorded replies include original text, suggested classification and manually chosen outcome in an inbound Activity. Identical normalized sender/body pairs reuse one receipt; conflicting repeated outcomes are rejected. Identical legitimate replies cannot currently be distinguished without external message IDs.

All recorded replies stop outreach: confirmed unsubscribe uses email-level unsubscribe suppression; other outcomes pause and create a human task. Non-ambiguous non-OOO replies advance only not_contacted/outreach contacts to replied, preserving later stages and company history. No automatic qualification. The sender is manually asserted, not authenticated; inbox/thread/provider-event verification remains pending. This remains a local single-user prototype, not a production inbox integration.

61 tests pass, including duplicate safety, partial failure rollback, sender ambiguity, CSRF and opt-out suppression. Browser demonstration recorded a synthetic unsubscribe as activity #5 and verified the outreach screen showed “Outreach stopped: unsubscribe.” No email was sent.


### Saved reply history

`/replies` provides outcome-filtered, paginated history (20 per page). `/replies/<activity_id>` shows the original manually recorded sender/text, human outcome, original classifier suggestion, current email-level stop, contact progress and company tasks. Company tasks are explicitly labeled as company-wide. These pages are read-only; they neither regenerate classification nor alter records. 63 tests pass, covering filtering, pagination, missing records, escaping and unchanged database counts. Browser demonstration verified the detail of a synthetic interested reply with its paused outreach and human task.


### Manual qualification evidence

Saved replies now support budget/authority/need/timing evidence notes. Saving partial evidence does not advance progress. Explicit qualification requires four nonempty notes, an interested recorded outcome, replied contact progress, and no active unsubscribe/bounce for the current contact email. The app checks completeness, not truth: evidence and sources are entered by the reviewer. Qualification preserves its evidence and audit revision and does not lift outreach stops. Corrections to a finalized assessment and automatic evidence extraction are not implemented. Single-process local prototype; no authenticated reviewer attribution yet.

65 tests pass, covering incomplete evidence, stale revisions, explicit qualification, preserved suppression, opt-out rejection and CSRF. Browser verification used clearly synthetic notes and showed qualified contact progress with outreach still paused.


### Call preparation

A qualified reply exposes Prepare or open call brief. It saves a template-based snapshot of company/contact, original reply, qualification revision/evidence and fit explanation, plus three general suggested questions. The view bounds long excerpts and links to full source notes. No LLM calls. Creation advances qualified to call_prepped and adds a human review task in one transaction; repeats reuse the brief. Outreach stops remain unchanged. Snapshots are not automatically refreshed; check current contact/restrictions before acting. Booking and live calls remain separate milestones.

67 tests pass, including qualification gating, repeat safety, snapshot persistence, unchanged suppression, CSRF and rollback. Browser demonstration verified a brief generated from explicitly synthetic qualification notes.


### Manual meeting confirmation

A call brief accepts an externally agreed future timestamp with explicit UTC offset and a confirmation source note. Confirmation stores UTC, creates a human call task, and transitions call_prepped to booked atomically. Identical repeats reuse the record; changes are rejected pending a dedicated rescheduling workflow. This records a manual assertion, not calendar availability or an invitation. No provider integration, rescheduling, cancellation or reminder automation yet. Outreach stops remain in place.

68 tests pass, including invalid/past/offset-free input, repeat safety, task timing and CSRF. Browser demo converted 2026-10-20 14:00 -04:00 to 18:00 UTC and showed the local call task. No invitation or email was sent.


### Manual meeting changes

Rescheduling updates the existing call task and stores prior/new time and confirmation note in revision history. Cancellation marks that task skipped, moves the booked contact to needs_review, and creates a human next-step task without lifting outreach stops. Unique change revisions reject stale changes. Only open tasks for booked contacts can change. Canceled meetings cannot yet be rebooked. These are local records; calendar events are untouched.

69 tests pass. Browser demonstration rescheduled the synthetic meeting by one day, then canceled it and verified two history entries and the canceled state. No emails or calendar requests occurred.


### Post-call outcomes

After a recorded meeting starts, the human can confirm the call took place and log follow-up/won/lost with notes. Follow-up requires a future timezone-aware date and next-step description. Logging closes the call task and transitions booked → called → logged in one transaction; follow-up creates a human task. Identical repeats reuse the saved outcome; conflicting changes and canceled/future meetings are rejected. Won/lost is recorded for the call, not applied globally to the account. Stops are preserved. Generic call-task completion routes to the brief instead of bypassing logging. No CRM, email or calendar write occurs; outcome corrections remain pending.

71 tests pass. Browser verification saved a synthetic completed call and a future proposal-review task. No real call was made by the app.


### Workflow next actions

The overview and `/workflow` derive one next action from the latest saved reply per contact: qualification, call preparation, meeting confirmation, upcoming-call review, outcome logging, or follow-up. Active unsubscribe/bounce restrictions take precedence. This is read-only guidance, not a scheduled orchestrator. It does not send messages or transition records on page views.

Exact system-generated qualification/brief task descriptions are recognized against saved source records. Superseded steps are separated from active work without deleting or changing task history. Unrecognized/manual tasks remain active. Meeting tasks link directly to the brief. Booked count now uses contact progress rather than legacy company history. Current implementation uses per-record lookups and description matching for older tasks; structured task associations and scale optimization remain future work.

73 tests pass, including the full manual sequence, terminal outcomes, follow-up completion, latest-reply selection, restriction precedence and read-only page checks. Browser demonstrated the Log call outcome next action and filtered completed steps. Background retries, live integrations and CRM sync are still pending.
