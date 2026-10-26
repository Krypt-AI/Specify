# Roadmap

Each phase ships working, tested functionality end to end.

## Phase 1: Foundation ✅

- Monorepo structure, Docker Compose
- Google sign-in (OAuth 2.0 + PKCE, signed state, httpOnly session cookie)
- Gmail and Sheets connection and disconnection with incremental scopes, encrypted token storage, revocation
- App shell, settings framework, setup wizard

## Phase 2: Gmail integration ✅

- Token refresh, revoked-grant and missing-scope detection (the integration shows *Reconnect*)
- Celery worker and scheduler: initial sync, incremental history sync, polling, manual sync,
  expired-cursor recovery, per-mailbox lease, recovery of work lost in a restart
- Safe message parsing (HTML reduced to text, attachments as metadata only, size limits)
- Classification: user rules and university senders decide the folder; Claude classifies
  everything else with validated structured output; confidence threshold and review queue;
  suspicious-email flagging; prompt-injection safeguards
- **Context labels:** no predefined labels. The AI names a label from each email's context, reuses
  existing labels and merges near-duplicates; labels are mirrored in Gmail under `Specify/`
- Four fixed folders (Recruitment, University, Certifications, Other) with multi-folder membership
- Corrections recorded as feedback; rule suggestions that the user accepts explicitly
- UI: Inbox, folder views, email detail with review and correction, dashboard metrics from real
  data, settings for sync, labeling, labels, rules, university and certification providers
- Tests: parser, credentials, sync, classification, API, user isolation, spec scenarios B, C, D and F

### Deferred from Phase 2

- **Gmail push notifications (Pub/Sub).** Polling every few minutes covers it until then. Push
  needs a public HTTPS endpoint, so it lands with the production deployment work.
- **Linking a Specify label to an existing Gmail label you created**, and merging two labels.
- **Applying labels to emails already processed** after Gmail labeling is switched back on.

## Phase 3: Recruitment management ✅

- AI provider is configurable: **Ollama (local, private)**, Claude, or none
- Extraction for emails whose primary folder is Recruitment: company (employer or agency),
  recruiter contact, opportunity details; salary, deadline and website kept only when grounded
  in the email text
- Matching: same thread or job reference updates the existing opportunity and moves its status
  forward; same domain or name reuses the company; similar names and same company plus title
  become duplicate candidates that the user merges or keeps separate
- Decision Queue with the spec's eleven decisions, advisory suggestion, missing information and
  preference flags; declining and status changes such as accepting an offer need confirmation;
  save for later and request more time return the opportunity after 7 and 3 days
- Companies and Opportunities pages with editing, status changes and decision history;
  opportunities can be created from any recruitment email; recruitment preferences in Settings
- Tests: extraction grounding, matching and duplicates, decisions, privacy, scenario A up to the
  decision, scenarios B and C (no recruitment records from university or certification email)

## Phase 4: Google Sheets ✅

- Connect an existing spreadsheet (link or ID) or create one with the spec's worksheets:
  Companies, Opportunities, Applications, Activity Log and the optional Email Tracker
- Rows keyed by stable record IDs; only mapped cells are written, so the user's own columns survive;
  missing worksheets and mapped columns are created; column mapping is validated
- Per worksheet: export or two-way, and which side wins when both changed. Manual edits are
  never silently overwritten: they are imported (two-way, editable columns) or raised as conflicts
  the user resolves; deleted rows are flagged and can be restored; rows of deleted records are removed
- Sync jobs with history, automatic sync after changes and every 15 minutes, retries with
  backoff, a visible failure state and a manual retry (scenario E)

## Phase 5: AI drafting ✅

- Drafts for every decision that needs a reply, plus "Draft a reply" for any email (university and
  certification replies included); editable guidance and wording per scenario; tone, length,
  language and approved personal details in Settings
- Works with Ollama, Claude or no AI (template wording); falls back to the template when the AI is
  unavailable; quality checks flag attachment claims, commitments, unknown numbers, identity
  numbers and placeholders to fill
- Gmail drafts in the original thread (In-Reply-To/References), one per decision (idempotent),
  updated on edit and regeneration, removed on discard, never recreated after the user sent or
  deleted them in Gmail
- **Draft Only:** Specify has no way to send email; sending is always done by the user in Gmail

## Phase 6: Workflow automation ✅

- Workflow engine that now runs every incoming email: definitions as graphs, one run per workflow
  per event (idempotency key), saved state, node-by-node history with inputs and outputs
- The spec's step types: Gmail and scheduled triggers, filter, classification, extraction,
  company and opportunity lookup, condition, user approval, decision input, record update,
  Sheets sync, Gmail labels, Gmail draft, reminder, notification, wait, error handler, retry, end
- The default workflow follows the spec's section 11.1 and pauses for the user's decision, then
  resumes from the saved step to draft the reply and sync
- Reliability: per-step retries with exponential backoff, error paths, failed runs kept for
  manual retry (dead letter), step time limits, pause, resume and cancel, recovery of runs
  interrupted by a restart; a failed step never lets dependent steps run
- Visual builder (React Flow): drag-and-drop steps, Yes/No/On-error connections, generated settings
  forms, validation (one trigger, no loops, all steps reachable, email steps only on email
  triggers), dry-run test runs, enable/disable, duplicate, save as template, run history
- Activity page: workflow runs with step inspection and actions, and the event log
- Automation settings: global pause (kill switch) and switches for records, drafts, approval
  before drafting and notifications

## Phase 7: Dashboard and reminders ✅

- Key dates (deadlines, exams, interviews, renewals, payments, events) read from each email,
  kept only when their wording appears in it; partial, relative or day/month-swappable dates are
  flagged "check this date" and never guessed
- Reminder rules in Settings decide which reminders exist and how early; decisions add revisits
  (save for later, more time) and recruiter follow-ups that close when the recruiter replies;
  optional "reply needed" reminders
- Follow-ups page: due, overdue, snooze, complete, reopen, manual reminders
- In-app notifications (bell): due reminders, new opportunities, unclear dates, workflow
  failures, integrations needing reconnection, failed Sheets syncs
- Dashboard: the spec's metrics from real data, including drafts awaiting review, follow-ups due
  and failed workflow runs
- Analytics: emails by folder, opportunities by status, weekly recruitment activity, decisions by
  outcome, follow-up and workflow success figures; validated colour palette, table view for
  every chart
- No calendar events and no email notifications (Specify never sends email)

## Phase 8: Security and testing ✅

- Permission audit: a test walks every API route and requires a session, with a short, explained
  list of public endpoints (it found and closed one unauthenticated endpoint)
- PostgreSQL row-level security through an optional restricted role for user requests; policies
  re-applied on every start; the whole test suite also runs through that role on PostgreSQL
- HTTP hardening: security headers, `Origin` check for writes, request ids, generic error
  responses; secrets redacted from API and worker logs
- Privacy: email text retention (default 365 days), full data export as JSON, account deletion
  that revokes Google access; Settings → Privacy & security
- Gmail push notifications through Pub/Sub (optional), with verification of Google-signed
  requests and automatic watch renewal; polling remains the fallback (deferred from Phase 2)
- End-to-end tests for the specification's scenarios A–F
- Running the suite on PostgreSQL found a column too short for draft tones, which SQLite had
  hidden; fixed in migration 0007
- Docs: [SECURITY.md](SECURITY.md), [DEPLOYMENT.md](DEPLOYMENT.md) (production, backup and
  recovery, troubleshooting), Pub/Sub setup in [GOOGLE_SETUP.md](GOOGLE_SETUP.md)

## Not yet built

- Gmail actions beyond labels and drafts (archive, star, mark read, trash). The `gmail.modify`
  scope already allows them; each would need its own switch and audit trail.
- Linking a Specify label to an existing Gmail label, and merging two labels.
- Applying labels to emails already processed after Gmail labeling is switched back on.
- Calendar events and email notifications (excluded by the specification's Draft Only rule).
