# Specify

An email management and recruitment workflow assistant. Specify connects to Gmail, sorts every
email into Recruitment, University, Certifications or Other, and labels it in Gmail with a label
the AI names from the email's context. It turns recruitment emails into company and opportunity
records and keeps a decision queue for you. Google Sheets sync and reply drafts follow in later
phases. Specify never sends email without your authorization.

**Status:** Phases 1–3 (Foundation, Gmail integration, Recruitment management) are complete. See [docs/ROADMAP.md](docs/ROADMAP.md).

**AI runs locally by default** with Ollama, so email text never leaves your computer. Claude is
available as an alternative. See [docs/AI_SETUP.md](docs/AI_SETUP.md).

## Quick start (Docker)

1. Set up Google OAuth credentials: [docs/GOOGLE_SETUP.md](docs/GOOGLE_SETUP.md).
2. `cp .env.example .env`, then fill in `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, generate
   `SESSION_SECRET` and `TOKEN_ENCRYPTION_KEY` with the commands in the file, and choose an AI
   provider ([docs/AI_SETUP.md](docs/AI_SETUP.md)).
3. `docker compose up --build` starts Postgres, Redis, the API, the worker, the scheduler and the frontend.
4. Open http://localhost:5173, sign in, and connect Gmail. The first sync starts immediately.

The backend runs migrations on start. API docs are at http://localhost:8000/docs.

## Local development (without Docker)

Requires Python 3.14, Node 24, PostgreSQL and Redis.

```bash
# backend (reads ../.env; point DATABASE_URL and REDIS_URL at your local services)
cd backend
python -m venv .venv && .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload

# background worker and scheduler, each in its own terminal
celery -A app.worker worker --loglevel=info --pool=solo   # --pool=solo is needed on Windows only
celery -A app.worker beat --loglevel=info

# frontend
cd frontend
npm install
npm run dev
```

Without Redis, set `CELERY_TASK_ALWAYS_EAGER=true` to run background work inside the API process.
This is for debugging only: requests then wait for sync and classification to finish.

## How classification works

1. **Sync:** the worker fetches new Gmail messages incrementally (Gmail history API) and polls
   every few minutes. Each message is stored once.
2. **Rules first:** your rules and configured university senders decide the folder.
3. **AI:** the model (local Ollama or Claude) reads the email as untrusted data, picks the folder
   and a context label, and reuses an existing label when one fits. It cannot take any action itself.
4. **Labels:** confident results are labeled in Gmail under `Specify/`. Uncertain or suspicious
   emails go to the review queue (`Specify/Needs Review`) with a suggested label that is applied
   only when you confirm it.
5. **Learning:** your corrections suggest new rules. Nothing changes until you accept a suggestion.
6. **Recruitment:** for emails in the Recruitment folder, the AI extracts the company, recruiter
   and role. Salaries and deadlines are kept only if they appear in the email. New opportunities
   wait in the Decision Queue with an advisory suggestion, and possible duplicates wait for your
   confirmation before anything is merged.

## Tests and checks

```bash
cd backend && python -m pytest        # in-memory SQLite; Gmail and the AI are replaced by fakes
cd frontend && npm run build && npm run lint
```

## Documentation

- [Architecture and design decisions](docs/ARCHITECTURE.md)
- [Google Cloud setup and OAuth scopes](docs/GOOGLE_SETUP.md)
- [AI setup (Ollama or Claude)](docs/AI_SETUP.md)
- [Roadmap](docs/ROADMAP.md)

## Dependency versions (verified)

| Backend | | Frontend | |
| --- | --- | --- | --- |
| Python | 3.14 | Node | 24 |
| FastAPI | 0.162.0 | React | 19.3 |
| SQLAlchemy | 2.1.6 | Vite | 8.3 |
| Alembic | 1.20.1 | TypeScript | 6.0 |
| Pydantic | 2.14.1 | Tailwind CSS | 4.3 |
| Celery | 5.6.3 | TanStack Query | 5.104 |
| Anthropic SDK | 2.3.0 | React Router | 7.18 |
