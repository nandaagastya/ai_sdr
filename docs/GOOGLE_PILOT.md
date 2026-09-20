# Google pilot implementation status

Provider choice: Google Workspace/Gmail and Google Calendar. Salesforce is deferred and must remain disconnected.

Completed foundation: new workflow tasks have explicit reply foreign-key associations; dashboard task context is loaded in batches. Qualification and call-outcome corrections retain before/after evidence, a reason, a manually asserted reviewer name, and revision conflict checks. Changed qualification after call preparation flags human review and preserves the historical brief. Outcome corrections change only explicitly linked follow-up tasks. No email or calendar invitation is sent.

Legacy task links are not guessed during normal page requests. `flask link-legacy-tasks` prints a read-only proposal; after reviewing source records, pass individual `--task-id` values to apply unambiguous links. Ambiguous or unmatched tasks remain visible. Never run seed.py against existing data.

Limitations: reviewer names are not authenticated identities. Corrected qualification can require manual reconciliation of a historical brief or meeting; regeneration and rebooking are not implemented. The existing development application is not ready for public deployment.

Next implementation sequence:

1. Authentication, tenant boundaries, authenticated reviewers, encrypted OAuth token storage, and versioned database migrations.
2. Gmail OAuth connection and read-only synchronization with durable cursors, provider message IDs, and thread association. Verify with a dedicated test inbox.
3. Durable jobs, retries/backoff, failure visibility, PostgreSQL concurrency checks, and recovery tests.
4. Gmail sending behind the provider interface, explicitly gated; persist attempts before sending and reconcile uncertain results before retrying. Gmail status must not be presented as proof of delivery.
5. Google Calendar event integration with stable external IDs, duplicate prevention, updates/cancellations, and a test calendar.
6. Controlled end-to-end Google pilot with synthetic prospects. Keep normal sending disabled until the controlled test is authorized.

Live verification requires a Google Cloud OAuth application and an authorized test account. Client secrets and tokens belong in configured secret storage, never in chat or source control. Automated local tests alone do not establish that Google integration works.
