# AI SDR Platform — Prototype

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

`GET /` — pipeline stage counts, an SVG map of the agent stack, an SVG
data-flow diagram of one lead's path (including the no-reply follow-up
loop and the learning-loop feedback path), a top-accounts-by-fit table,
and a recent-agent-runs table with a button to trigger a live prospecting
run.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then add your real APOLLO_API_KEY

python seed.py                     # populate with realistic demo data
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
sender_name (up to 100 characters), and offer (up to 600 characters).
Success returns HTTP 201, the saved activity and run IDs, and three messages.
Invalid input returns HTTP 400. Generation errors return HTTP 500 and close
the execution audit as an error.

Nothing is sent or scheduled; no tasks are created or pipeline stages changed.
Existing SQLite databases work without reseeding or schema changes.
This is the preview portion of Phase 1, not a complete sending agent. Provider
integration, opt-outs, cadence execution, send idempotency, and live-send
eligibility are still pending. Do not expose the unauthenticated prototype publicly.
