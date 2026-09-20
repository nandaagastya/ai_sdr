# AI SDR build roadmap

Based on the AI SDR Platform — Step-by-Step Build Guide dated September 17, 2026.

## Current status

The guide describes an existing Flask/SQLite prototype with Apollo prospecting, five shared models, six endpoints, and a dashboard. The rebuilt prototype is now imported with ten passing offline regression tests and a seeded dashboard/API smoke check. Live Apollo access remains unverified. See IMPORT_REVIEW.md for gaps before outreach.

## Outreach preview milestone

Implemented: saved three-touch template previews, dashboard form and history links, input validation, and execution audit. Saved preview IDs display on reload. Optional AI-written first-email openings use a separate OpenAI provider with versioned instructions and token usage auditing; templates remain the default. No email delivery or scheduling. Existing databases need no migration for this milestone. Draft editing, revision history, approval/reopening, and stale-revision protection are implemented without provider calls. Approval is local review status only. A searchable, paginated review queue provides all/draft/approved filters and links to saved sequences. Phase 1 sending remains incomplete.

## Product scope

Initial vertical: Salesforce consulting firms with 51–500 employees. Automate prospecting, outreach, reply qualification, call preparation, scheduling, and post-call logging. A human conducts the live call and closes the deal.

## Architecture contract

- Keep Account, Contact, Activity, Task, and AgentRun as the shared data layer; extend existing models rather than replacing them.
- Keep each agent independently testable; place sequencing and retry ownership in the orchestrator.
- Use transparent, versioned rules for ICP scoring and qualification.
- Keep generation templates versioned and external providers behind interfaces.
- Track execution status, timestamps, references, and provider usage per AgentRun.
- Route ambiguous results and exhausted retries to a visible human review queue.

## Milestones

| Phase | Work | Exit criterion |
| --- | --- | --- |
| 0 | Import and verify the existing prototype | Documented setup runs; existing endpoints, models, prospecting, and dashboard inspected |
| 1 | Outreach with replaceable email provider | Test records produce personalized messages; sandbox delivery and activity logging work |
| 2 | PostgreSQL migration | Versioned migrations run; no SQLite-only assumptions remain |
| 3 | Reply and qualification | Replies match threads, classify intent, and qualify common cases with review for ambiguity |
| 4 | Call preparation | Qualified contacts produce a short, evidence-grounded call brief |
| 5 | Booking | Scheduling confirmation creates a human task; no-response and cancellation paths work |
| 6 | Post-call logging | Structured human input records outcome, closes the task, and routes next steps |
| 7 | Orchestrator | Agents sequence automatically with complete audit logs, retries, and review routing |
| 8 | Salesforce sync | One-way account/contact/activity synchronization works with retry and deduplication |
| 9 | Launch validation | Full pipeline demonstrated end to end with the human handling the call |

Integrate each agent with the execution wrapper as it becomes testable; phase 7 completes end-to-end orchestration. Migrate before concurrent inbox and booking workers go live. HubSpot and bidirectional CRM synchronization are later scope.

## First implementation session

1. Import source after checking for credentials, local databases, and real lead data.
2. Read repository instructions and document the actual project structure.
3. Run the app and existing tests; capture a reproducible baseline.
4. Inventory the six existing endpoints and five models before changing them.
5. Add versioned pipeline stages and required fields through migrations.
6. Implement outreach against a fake/sandbox provider with meaningful tests before live integration.

## Decisions to resolve against the prototype

- Choose the authoritative pipeline state per contact and define account-level aggregation.
- Keep review status separate from pipeline progress so recovery can resume correctly.
- Give one execution wrapper ownership of AgentRun creation and completion.
- Define idempotency for retries, inbound events, sends, and CRM writes; handle uncertain provider outcomes without blind resending.
- Stop or reschedule follow-ups on replies, opt-outs, bookings, and out-of-office messages.
- Separate booking-link delivery from confirmed booking.
- Define authentication, tenant isolation, webhook verification, and secret handling before client deployment.
- Select sending and calendar providers after checking their current capabilities and permitted usage.

## Open-source release

- Publish source with an explicit open-source license.
- Supply setup instructions, an environment-variable example, synthetic demo data, and contribution guidance.
- Exclude secrets, live lead data, local databases, and client exports.
- Make repository visibility public when the release contents are ready. Repository visibility cannot be changed through the currently available GitHub connector tools.


## User dashboard and lead imports

The overview now focuses on actionable tasks, draft reviews, and main prospects. CSV/TSV, XLSX, DOCX tables, and selectable-text PDF lead tables support column mapping, row preview, validation, duplicate skipping, and explicit import confirmation. Original files are not stored. Sending remains off.
