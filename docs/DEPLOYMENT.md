# Deployment, backup and troubleshooting

## Production deployment

The Docker Compose setup is for development: it runs the Vite dev server and uses default
database passwords. A production deployment keeps the same services (PostgreSQL, Redis, API,
worker, scheduler) and changes the following.

### 1. One HTTPS origin

Serve the frontend and the API from the same site, for example `https://specify.example.com`
for the app and `https://specify.example.com/api` for the backend. The session cookie is
`SameSite=Lax`, so the browser only sends it to the API when both are on the same site. One
origin also avoids CORS entirely. A minimal [Caddy](https://caddyserver.com/) configuration,
which also obtains the TLS certificate:

```
specify.example.com {
    handle /api/* {
        reverse_proxy backend:8000
    }
    handle {
        root * /srv/specify
        try_files {path} /index.html
        file_server
    }
}
```

Build the frontend with the API on the same origin and copy `frontend/dist` to `/srv/specify`:

```bash
cd frontend
VITE_API_URL=https://specify.example.com npm ci && npm run build
```

### 2. Environment

```
APP_ENV=production                    # Secure cookies, HSTS, no interactive API docs
FRONTEND_URL=https://specify.example.com
BACKEND_URL=https://specify.example.com
DATABASE_URL=postgresql+psycopg://<owner>:<strong password>@<db host>:5432/<db>
REQUEST_DATABASE_URL=postgresql+psycopg://specify_app:<another strong password>@<db host>:5432/<db>
REDIS_URL=redis://<redis host>:6379/0
SESSION_SECRET=<generated>
TOKEN_ENCRYPTION_KEY=<generated>
```

Generate the secrets with the commands in `.env.example`, and keep them in your platform's secret
store rather than in a file on the server where possible. Give PostgreSQL and Redis real passwords
and do not publish their ports. Remove the `ports:` lines for `db` and `redis` from the Compose file.
`REQUEST_DATABASE_URL` turns on row-level security ([SECURITY.md](SECURITY.md#row-level-security)).

### 3. Google

- Add `https://specify.example.com/api/auth/google/callback` as an authorized redirect URI on
  the OAuth client.
- In Testing mode only listed test users can sign in, and Gmail must be reconnected weekly
  ([GOOGLE_SETUP.md](GOOGLE_SETUP.md#testing-mode-limits)).
- Optional: Gmail push notifications ([GOOGLE_SETUP.md](GOOGLE_SETUP.md#gmail-push-notifications-optional)),
  which need this public HTTPS URL.

### 4. Processes

| Process | Command | Replicas |
| --- | --- | --- |
| API | `alembic upgrade head && python -m app.db.rls && uvicorn app.main:app --host 0.0.0.0 --port 8000` (the image's default) | 1 or more |
| Worker | `celery -A app.worker worker --loglevel=info` | 1 or more |
| Scheduler | `celery -A app.worker beat --loglevel=info` | **exactly 1** (two schedulers poll twice; the work stays idempotent but doubles) |

The API answers `GET /health` for load balancer checks. Logs go to standard output. Each request
line carries its request id.

### 5. AI provider

With `AI_PROVIDER=ollama`, run Ollama on the same machine or private network
([AI_SETUP.md](AI_SETUP.md)), and never expose port 11434 to the internet. A server without a GPU
handles a personal mailbox with a 3B model, and an initial sync of hundreds of emails takes a while.

## Backup and recovery

**What to back up**

| Data | Where | Back up? |
| --- | --- | --- |
| Everything Specify knows | PostgreSQL | **Yes**, daily |
| `TOKEN_ENCRYPTION_KEY`, `SESSION_SECRET` | `.env` / secret store | **Yes**, once, stored apart from the database backups |
| Task queue | Redis | No. Lost tasks are recovered by the scheduler's poll |
| Ollama models | Ollama volume | No. `ollama pull` again |
| Emails | Gmail | Already in Gmail |

**Back up** (works in PowerShell and Bash; the dump is written inside the container so Windows
never re-encodes it; in Git Bash run `export MSYS_NO_PATHCONV=1` first, or it rewrites `/tmp`):

```bash
docker compose exec db pg_dump -U mailup -Fc -f /tmp/specify.dump mailup
docker compose cp db:/tmp/specify.dump ./specify-2026-10-27.dump
```

**Restore**

```bash
docker compose stop backend worker beat
docker compose cp ./specify-2026-10-27.dump db:/tmp/restore.dump
docker compose exec db pg_restore -U mailup -d mailup --clean --if-exists /tmp/restore.dump
docker compose start backend worker beat
```

The backend re-runs migrations and the row-level security script on start. When restoring into
a new PostgreSQL server, `pg_restore` warns that the role `specify_app` does not exist. That is
expected, because roles live outside the database and the backend recreates it.

Test a restore now and then: restore into a scratch database (`createdb specify_restore_test`,
then `pg_restore -d specify_restore_test ...`) and check that it opens.

**If the database is lost with no backup:** sign in again and reconnect Gmail. Specify re-reads
the last 30 days of mail (Settings → Gmail) and rebuilds folders, labels and opportunities. It
reuses the `Specify/` labels already in Gmail. Decisions, notes and edits made in Specify are
gone. The Google Sheets export keeps a readable copy of companies, opportunities and the
activity log.

**If `TOKEN_ENCRYPTION_KEY` is lost:** the data is intact, but stored Google tokens cannot be
decrypted. Set a new key and have each user reconnect Gmail and Sheets.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `Internal Server Error` on every page, backend exits at start | `SESSION_SECRET` or `TOKEN_ENCRYPTION_KEY` is missing or still a placeholder. `docker compose logs backend` names the setting. Generate both with the commands in `.env.example`. |
| Google says `redirect_uri_mismatch` | The OAuth client's redirect URI must equal `${BACKEND_URL}/api/auth/google/callback` exactly, including `http`/`https` and the port. |
| Google says `access_denied` or "app not verified" | In Testing mode, add your account under Audience → Test users. |
| Gmail shows *Reconnect* about once a week | Testing-mode refresh tokens expire after 7 days. Reconnect, or publish the app. |
| No new emails arrive | Check that the worker and scheduler run: `docker compose ps`, then `docker compose logs worker beat`. Use *Sync now* in Settings → Gmail and read the sync status there. |
| Emails stay in *Needs review* | The AI is unavailable or unsure. `docker compose logs worker` says which. Check `AI_PROVIDER`, and for Ollama run `ollama list` and check that `OLLAMA_URL` is reachable from the containers ([AI_SETUP.md](AI_SETUP.md)). |
| An action fails with "Cross-site request blocked" (403) | The page's address does not match `FRONTEND_URL`. Open Specify at exactly that URL, for example `localhost`, not `127.0.0.1`. |
| An error shows a request id | Search the logs for it: `docker compose logs backend worker | grep <request id>`. |
| Sheets sync failed | Settings → Google Sheets → *Sync history* shows each attempt and its error. Fix the cause (reconnect, shared spreadsheet deleted) and press *Retry*. Conflicts wait under *Conflicts*. |
| A workflow run failed | Activity → Workflow runs shows the failing step, its input and error. *Retry* resumes from that step. Settings → Automation → *Pause all automation* stops everything at once. |
| `permission denied for table …` in the logs | Row-level security is on and a new table has no grant yet. Restart the backend, which re-applies the script. |
| `new row violates row-level security policy` | A request tried to write another user's row. That is a bug, and the database stopped it. Please report it with the request id. |
| Gmail push requests get 401 | `GMAIL_PUSH_AUDIENCE` must equal the subscription's audience, and `GMAIL_PUSH_SERVICE_ACCOUNT` the service account it signs with. Polling keeps working meanwhile. |
| `alembic upgrade` fails after pulling new code | Read the error in `docker compose logs backend`. Restore the last backup if a migration was interrupted, then upgrade again. Migrations never run partially on PostgreSQL. |
