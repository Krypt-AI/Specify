# Security and privacy

Specify holds access to someone's mailbox, so the design assumes every layer can fail and puts
another behind it. This page lists the controls, how to switch on the optional ones, and what
they do not cover.

## Controls

| Area | Control |
| --- | --- |
| Sign-in | Google OAuth with PKCE and a signed, short-lived state cookie. Each integration (Gmail, Sheets) asks for its own scopes when connected, and must be the same Google account. |
| Session | A signed JWT in an `httpOnly`, `SameSite=Lax` cookie (`Secure` when `APP_ENV=production`). JavaScript cannot read it. |
| Cross-site requests | `SameSite=Lax`, plus an `Origin` check: a state-changing request whose `Origin` is not `FRONTEND_URL` or `BACKEND_URL` is refused with 403. |
| Every endpoint needs a session | Enforced by a test that walks the API's route table (`tests/test_security.py`). The only exceptions are health, sign-in, logout and the Google-signed Gmail webhook. |
| Google tokens | Encrypted with Fernet (`TOKEN_ENCRYPTION_KEY`), refreshed on the server, revoked at Google on disconnect and account deletion. Never sent to the browser, never in exports, redacted from logs. |
| Least privilege | `gmail.modify` (read, label, draft) and `spreadsheets`. **Draft Only:** Specify has no code that sends, archives or deletes email (a test checks the Gmail client has no such method). |
| User isolation | Every query filters by the signed-in user. Optional PostgreSQL row-level security enforces it again in the database ([below](#row-level-security)). |
| Untrusted email | Email text is delimited and neutralized before the AI sees it, and the AI can only return validated structured data. It has no tools and cannot act. Extracted values (salary, deadlines, dates, websites) are kept only when they appear in the email. HTML is never rendered. |
| HTTP | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, a `default-src 'none'` CSP on API responses, `Cache-Control: no-store` on `/api`, HSTS in production. Interactive API docs are off in production. |
| Errors | Unexpected errors return a generic message and a request id (`X-Request-ID`), never internals. The same id is on every log line for that request. |
| Logs | Bearer tokens, Google access and refresh tokens, Anthropic keys, OAuth codes and token fields are redacted from every log line and traceback, in the API and the worker. |
| Webhooks | Gmail push requests must carry an OIDC token signed by Google for the configured audience and service account. |
| Privacy | Email text is removed after a retention period (default 365 days, Settings → Privacy & security). Users can export all their data as JSON and delete their account, which revokes Google access and deletes every row. With Ollama, email text never leaves the server. |

## Row-level security

With `REQUEST_DATABASE_URL` set, signed-in requests connect as the restricted role
`specify_app`. Each transaction sets `app.current_user_id` to the signed-in user, and the
policies in [`backend/sql/row_level_security.sql`](../backend/sql/row_level_security.sql) only
show that user's rows: tables with a `user_id` column directly, and child tables (email folder
memberships, sync state, sheet row state and conflicts, workflow steps) through their parent. A
query that forgets its user filter returns nothing from other users, and writing a row for
another user fails.

The owner role (`DATABASE_URL`) is not subject to the policies. Sign-in (there is no user yet),
the Gmail webhook (it finds the user from the notification), background workers (they act for
every user) and migrations use it.

**Turn it on** (PostgreSQL only, including Supabase):

1. Choose a long random password and set
   `REQUEST_DATABASE_URL=postgresql+psycopg://specify_app:<password>@<host>:5432/<database>`.
2. Restart the backend. On every start it runs the migrations, then `python -m app.db.rls`, which
   creates the role with that password, grants it table access and (re)creates the policies.

**Check it:** `docker compose logs backend` shows "Row-level security applied". The tests prove
it against a real database:

```bash
# a throwaway database the tests may drop and recreate
docker compose exec db psql -U mailup -c "CREATE DATABASE specify_rls_test"
cd backend
TEST_POSTGRES_URL=postgresql+psycopg://mailup:mailup@localhost:5432/specify_rls_test \
  python -m pytest tests/test_row_level_security.py
# the whole suite through the restricted role (run the line above first: it creates the role)
TEST_DATABASE_URL=postgresql+psycopg://mailup:mailup@localhost:5432/specify_rls_test \
TEST_REQUEST_DATABASE_URL=postgresql+psycopg://specify_app:rls-test-password@localhost:5432/specify_rls_test \
  python -m pytest
```

**Adding a table:** add it to one of the two lists in the SQL file. `test_policy_script_covers_every_table`
fails until you do.

## Secrets and rotation

- `SESSION_SECRET`: rotating it signs everyone out. Nothing else is affected.
- `TOKEN_ENCRYPTION_KEY`: stored Google tokens can only be read with the key that encrypted them.
  If you rotate it, every user must reconnect Gmail and Sheets. Back it up with your database
  backups ([DEPLOYMENT.md](DEPLOYMENT.md#backup-and-recovery)), but store it separately.
- `GOOGLE_CLIENT_SECRET`: rotate it in the Google Cloud Console (add a new secret, deploy, then
  delete the old one). Existing refresh tokens keep working.
- Never commit `.env`. It is in `.gitignore` and `.dockerignore`.

## Known limits

- Google's `gmail.modify` scope technically allows sending, archiving and deleting. Specify's
  restriction to labels and drafts is enforced in its code, not by Google.
- Workflow run history keeps step inputs and outputs, such as extracted fields, until the account
  is deleted. Retention removes email text, not these summaries.
- Labels, drafts and the spreadsheet that Specify created stay in the user's Google account after
  account deletion, because they belong to the user.
- Specify is built for one person or a small trusted group per deployment. Opening it to the
  public requires Google's app verification and, for restricted scopes, a security assessment.
