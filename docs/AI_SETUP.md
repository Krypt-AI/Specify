# AI setup

Specify uses AI for two jobs: sorting each email into a folder with a context label, and pulling
recruitment details (company, role, salary, deadline) out of recruitment emails. Choose the
provider with `AI_PROVIDER` in `.env`.

| `AI_PROVIDER` | Where email text is processed | Notes |
| --- | --- | --- |
| `ollama` | On your computer only | Private and free. Slower, and smaller models make more mistakes, which land in your review queue. |
| `anthropic` | Anthropic's Claude API | Most accurate. Needs `ANTHROPIC_API_KEY` and paid usage. |
| `none` | Nowhere | Your rules decide; everything else waits for you in the review queue. |

Whatever the provider, the model only returns a classification or extracted details. It cannot send,
delete or change anything, and instructions hidden in an email are ignored.

## Ollama (local, private)

1. Install Ollama for Windows from https://ollama.com/download and start it. It runs in the system tray.
2. Download a model in PowerShell:
   ```powershell
   ollama pull llama3.2:3b
   ollama list
   ```
3. Set these lines in `.env`:
   ```
   AI_PROVIDER=ollama
   OLLAMA_URL=http://host.docker.internal:11434
   OLLAMA_MODEL=llama3.2:3b
   ```
   Running the backend without Docker? Use `OLLAMA_URL=http://localhost:11434` instead.
4. Apply the change:
   ```powershell
   docker compose up -d --force-recreate backend worker beat
   ```

**If the containers cannot reach Ollama** (emails stay "Queued" and the worker log says it could
not reach Ollama): Ollama only listens to your own computer by default. Add a Windows environment
variable `OLLAMA_HOST` with the value `0.0.0.0` (Start → "Edit the system environment variables" →
Environment Variables → New), quit Ollama from the tray, and start it again.

### Choosing a model

| Model | Size | When to use |
| --- | --- | --- |
| `llama3.2:3b` | ~2 GB | Default. Works on a laptop CPU; expect several seconds per email. |
| `llama3.1:8b` | ~5 GB | Noticeably better at extraction; needs 16 GB RAM and is slower on a CPU. |

Change `OLLAMA_MODEL`, pull the model, and recreate the containers. On a laptop without a dedicated
GPU, lower **Settings → Gmail → First sync: max emails** so the first sync finishes sooner.

### Running Ollama in Docker instead

`docker compose --profile ollama up` also starts an Ollama container. Set
`OLLAMA_URL=http://ollama:11434`, then pull the model inside it:
`docker compose exec ollama ollama pull llama3.2:3b`. The native Windows app is usually faster.

## Anthropic (Claude API)

1. Create an API key at https://console.anthropic.com (Settings → API keys) and set up billing.
2. Set in `.env`:
   ```
   AI_PROVIDER=anthropic
   ANTHROPIC_API_KEY=sk-ant-...
   AI_MODEL=claude-opus-5-5
   ```
3. Recreate the containers as above.

Declined requests are re-run on another Claude model automatically (`fallbacks: "default"`).
