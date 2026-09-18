# Prototype import review

Imported from ai-sdr-prototype.zip supplied by Nanda on September 18, 2026.
The archive's original local git metadata remains in the supplied ZIP; this
import adds its source snapshot to the existing GitHub history.

## Verified

- Five shared models, six read APIs, prospecting POST endpoint, and dashboard exist.
- Five offline regression tests pass: read routes/dashboard, scoring, missing-key
  audit, repeated upsert preserving booked state, and provider failure audit.
- Seed creates ten demo accounts and six simulated runs; seeded dashboard and
  all six read endpoints respond successfully.
- No actual credentials or database files found in the imported source.
- No live Apollo call was made and no outreach was sent.

## Import fixes

- Re-prospecting preserves existing downstream stages.
- Generated demo domains/emails use .example, LinkedIn URLs are omitted,
  account source is demo, and all seed run descriptions identify simulated data.
- Local development server defaults to loopback with debug disabled.
- README documents destructive reseeding and distinguishes seven API routes.

## Before outreach

The current prospecting agent produces accounts only. It does not find contacts
or enrich domains. Seeded contacts must not be mistaken for discovered people.
Add an explicit contact acquisition/import path before live outreach.

The current new/qualified/outreach/replied/booked/closed stages differ from the
guide. In particular qualified currently means ICP fit, not reply qualification.
Migrate existing stages and define contact-level state before sequencing agents;
do not simply rename qualified on old data without preserving its meaning.

Add migrations before extending existing databases: create_all does not migrate
tables. Add request validation, malformed provider response handling, and
transaction rollback/error completion. Current scoring treats unknown country
as a pass and broad consulting as a vertical match; revisit those explicit rules.

Build outreach in preview/sandbox mode first with versioned templates,
provider abstraction, duplicate prevention, and stop conditions. A preview
must not claim that an email was actually delivered or advance a live send stage.

Authentication, tenant isolation, durable job execution, usage tracking, CRM
sync, and open-source licensing remain future work. Learning-loop is an extension
in the rebuilt prototype; it must keep scoring changes inspectable and versioned.

## Validation limits

Tests use Python 3.12, SQLite, and mocked Apollo responses. PostgreSQL, live
provider compatibility, and visual browser rendering were not verified. Existing
datetime.utcnow and Query.get deprecation warnings remain for later cleanup.
