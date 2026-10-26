# Architecture and design decisions

## Layout

```
backend/              FastAPI service and Celery worker
  app/api/            HTTP routes (thin: validate, authorize, delegate)
  app/core/           Settings, signing and encryption, HTTP hardening, log redaction
  app/db/             Engines and sessions (owner and restricted), row-level security setup
  app/services/       Domain and integration logic
    gmail/            REST client, parser, sync, Gmail label mirroring, push notifications
    classification/   Rule signals, AI classifier, processing pipeline
    recruitment/      Extraction, grounding checks, record matching, decisions
    labels.py         Context-label naming and dedupe
    sheets/           Sheets client, column mapping, two-way sync and conflicts
    drafting/         Reply scenarios, generation, quality checks, Gmail drafts
    workflows/        Step catalogue, executors, engine, default workflow
    privacy.py        Retention, export, account deletion
    llm.py            AI providers (Ollama, Anthropic) behind one interface
  app/models/         SQLAlchemy models; every user-owned row carries user_id
  app/schemas/        Pydantic request/response contracts and validated preferences
  app/worker.py       Celery app and beat schedule
  app/tasks.py        Thin background tasks
  alembic/            Versioned migrations
  sql/                Row-level security policies (applied by app/db/rls.py)
frontend/             React + TypeScript + Vite + Tailwind
  src/api/            Typed API contracts and TanStack Query hooks, one module per resource
  src/components/     UI primitives (ui/), email views (email/), settings sections (settings/)
  src/pages/          Route-level views
docs/                 Setup, architecture, roadmap
```

## Email pipeline

```
Gmail ──poll / push / manual──▶ sync_mailbox ──new email ids──▶ process_email (one task per email)
  (history API, lease)       │                               │
                             ▼                               ├─ rules decide the folder
                       email_messages                        ├─ Claude: folder, label, flags
                       (unique per message)                  ├─ threshold → labeled or review
                                                             ├─ recruitment email: extract →
                                                             │    company, contact, opportunity
                                                             └─ mirror labels in Gmail
```

Every step is idempotent. Sync takes a lease per mailbox and keeps its history cursor in
`gmail_sync_states`, so it resumes after a restart. A processing task claims its email with an
atomic `pending → processing` update, so duplicate tasks are harmless. The poller re-queues claims
abandoned by a dead worker and work queued for too long.

## Decisions

| Decision | Rationale |
| --- | --- |
| **Four fixed folders, AI-named labels** (user decision) | The folders drive navigation and later workflows (recruitment records, reminders), so they stay fixed. Gmail labels have no predefined list: the AI names one from context and reuses existing labels. |
| Label dedupe: normalized-name match, then a similarity ≥ 0.88 whose numbers agree | Stops sprawl ("Job Offer" vs "Job Offers") without merging distinct items ("CS301" vs "CS302"). Disabled labels are never revived by the AI, and new AI labels are capped at 300. |
| Uncertain emails get a *suggested* label, not a created one | Labels come only from confident results or the user's confirmation, so the label set stays clean. |
| Rules and configured university senders decide; provider domains, keywords and headers are hints | Matches the spec: a certification provider's newsletter is not a certification email. The AI weighs hints against the content. |
| Suspicious only on concrete signs, decided by the AI | Regex heuristics misfire (bank notices say "never share your OTP"). Low confidence alone never marks an email suspicious. |
| **AI provider behind one interface; Ollama by default** (user decision, for privacy) | `llm.py` takes prompt blocks and returns a validated Pydantic object. Ollama is constrained to the JSON schema (refs inlined), and Claude uses `messages.parse`. Both map failures to *retry later* or *unusable*. |
| Extraction values must be grounded in the email | Salary numbers must appear in the text, deadline wording must be quoted from it, and websites must appear in the text or links. Anything else is dropped, never guessed. |
| Exact identifiers match, weaker evidence asks the user | Same thread or job reference updates an opportunity, and same domain or normalized name reuses a company. Similar names, or the same company and title, create a `DuplicateCandidate`, and nothing merges without the user. |
| Only the primary Recruitment folder creates records | University and certification emails (including internships posted by a university) never create recruitment records automatically, as the spec requires. |
| Decision and status on the opportunity, history in `user_decisions` | One place for the current state, with a full audit of choices. The spec's separate `applications` table would duplicate these fields. Phase 4 derives the Applications sheet from them. |
| Consequential changes need confirmation (HTTP 409, then repeated with `confirm`) | Declining, accepting or declining an offer, and withdrawing are never one click. |
| Claude via `messages.parse` with a Pydantic schema, no tools | The model can only return a classification. Output is validated, group values come from an enum, and label references are mapped back server-side. |
| Prompt-injection safeguards | Email content is delimited, any `<email>` tag inside it is neutralized, the system prompt says never to obey it, and Specify's own signals sit outside the email block. |
| Model `claude-opus-5-5` at `effort: low`, server-side fallback on refusals | Low effort suits classification. `fallbacks: "default"` re-runs a declined request on another model. The model can be changed with `AI_MODEL`. |
| Prompt caching on the instructions and the per-user label list | Bursts such as an initial sync reuse the cached prefix. The label list is ordered by creation so it stays stable between calls. |
| Transient AI or Gmail failures retry with backoff; the final attempt falls back to rules | Classification never stalls. Unusable AI output (refusal, invalid) goes straight to review. |
| Only Specify-managed labels are ever added or removed in Gmail | Labels you created are never touched. An existing Gmail label with the same name is reused, never renamed. |
| `gmail.modify` as the only Gmail scope | It is the narrowest scope that can apply labels, and it covers reading and drafts. Draft Only is enforced in code. |
| Message parsing keeps text only, at most 20,000 characters, and sends at most 6,000 to the AI, saying so in the prompt | Data minimization. HTML is reduced to text and never rendered. Attachments are recorded as metadata and never downloaded. |
| `UTCDateTime` column type | Every timestamp is stored in UTC and returned timezone-aware on PostgreSQL and SQLite alike. |
| Group membership in `email_message_groups` | An email can sit in several folders (a university internship is also Recruitment), and folder queries stay portable SQL. |
| Session in an httpOnly, SameSite=Lax cookie holding a signed JWT | JavaScript cannot read it, so XSS cannot steal it. Google tokens never reach the browser. |
| OAuth with PKCE and a signed state cookie; separate login, Gmail and Sheets purposes | Least privilege: each scope is requested only when its feature is connected. An integration must belong to the signed-in Google account. |
| OAuth tokens encrypted with Fernet | A database dump alone does not reveal tokens. Disconnecting revokes access at Google first. |
| Typed preferences (`UserPreferences`) with deep-merge updates | Every setting is validated (timezones, thresholds, lists). Partial updates cannot wipe other sections. |
| Synchronous SQLAlchemy; background work in Celery | Simple code. Long work never runs in a request, and the API only enqueues it. |
| Tests run tasks eagerly against fakes | `CELERY_TASK_ALWAYS_EAGER` and in-memory Gmail and AI fakes exercise the full pipeline without Redis or network. |
| Optional row-level security through a second, restricted database role | Isolation no longer depends only on every query remembering its user filter. Workers and sign-in keep the owner role because they act for the system. The policy script is idempotent and re-applied on every start, and a test fails when a new table has no policy. |
| CSRF: `SameSite=Lax` plus an `Origin` allow-list for writes | Lax already stops cross-site form posts. The Origin check also covers same-site subdomains and old browsers. No token plumbing is needed in the frontend. |
| Retention removes email text, not the email record | Folders, labels and opportunities keep working, the full email stays in Gmail, and the most sensitive content (the body) does not pile up. |
| Push notifications only start a sync | A webhook never carries data Specify trusts. It names a mailbox, and the normal history sync does the rest, so polling and push share one code path. |
| UI primitives written in the shadcn/ui style | Same ownership model without CLI scaffolding. Radix primitives will be added when dialogs and menus are needed. |

## Supabase

The schema is plain PostgreSQL, so `DATABASE_URL` can point at Supabase (use the direct
connection string as the owner). The row-level security script works there unchanged. Set
`REQUEST_DATABASE_URL` for the `specify_app` role ([SECURITY.md](SECURITY.md#row-level-security)).
