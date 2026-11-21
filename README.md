# Lyftr AI Chatbot

A React chat app that remembers earlier messages in the same conversation. FastAPI stores the conversation in SQLite. LiteLLM calls Groq, switches keys if a call fails, and caches replies. Each assistant reply shows its source, model, latency, and token counts.

## Live URLs

| Submission item | Status |
| --- | --- |
| Vercel frontend | Awaiting verified public URL |
| Render backend | Awaiting verified public URL |
| Public GitHub repository | Awaiting confirmed repository URL |
| Narrated demo | Video link pending. |

Add the real links here after testing the public app in a signed-out browser.

## Run locally: with Docker and without

Run the commands from the project root in Bash or Zsh. Copy the example once, then edit the private `.env` file and enter two different Groq keys. Use models available to your Groq account.

```sh
cp -n .env.example .env
```

### With Docker

Start Docker Desktop or Docker Engine with Compose installed.

```sh
docker compose config --quiet
make up
docker compose ps
```

Open http://localhost:3000 and send a message. Check backend readiness at http://localhost:8000/health. Run `make down` to stop both services. The named volume `chat_data` keeps the database between runs.

### Without Docker

Use Python 3.12 and Node.js 22.12 or later in the 22.x series. In terminal one:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements.txt
set -a
. ./.env
set +a
export DATABASE_URL=sqlite:///./app.db
uvicorn app.main:app --app-dir backend --port "${BACKEND_PORT:-8000}"
```

In terminal two, also starting from the project root:

```sh
. ./.env
cd frontend
npm ci
VITE_API_BASE_URL="$VITE_API_BASE_URL" npm run dev
```

### Prepare the GitHub repository

Keep `backend/`, `frontend/`, `docker-compose.yml`, `Makefile`, `render.yaml`, `.env.example`, `.gitignore`, and `README.md` at the repository root. The backend tests are in `backend/tests/`. Commit the frontend lockfile so local and hosted builds use the same packages.

For a new repository, run `git init -b main`. Stage and check the submission before pushing to your public GitHub repository:

```sh
git add .gitignore .env.example backend frontend docker-compose.yml Makefile render.yaml README.md
git diff --cached --name-only
git check-ignore .env
git ls-files -- .env
git grep --cached -lE 'gsk_[[:alnum:]_-]{20,}' -- .
git log --all -G'gsk_[[:alnum:]_-]{20,}' --format='%h' --name-only
```

The ignore check should print `.env`. The tracked-file and key searches should print nothing. The searches show filenames only. If a real key appears in Git history, rotate it in Groq and clean the history before publishing.

For a first upload, create an empty public repository in GitHub and copy its HTTPS clone URL. After reviewing the staged files, run the following commands in the new local repository. Paste the URL when prompted:

```sh
git commit -m "Prepare Lyftr AI assignment for submission"
printf 'GitHub repository clone URL: '
read -r repo_url
git remote add origin "$repo_url"
git push -u origin main
```

### Deploy the frontend on Vercel and the backend on Render

1. **Vercel:** Import the GitHub repository. Select `frontend` as the root directory, **Vite** as the framework, Node **22.x**, `npm ci` as the install command, `npm run build` as the build command, and `dist` as the output directory. Create the project and copy its assigned production origin. The first build gives you the frontend address to enter in Render. [Vercel Vite guide](https://vercel.com/docs/frameworks/frontend/vite)
2. **Render:** Choose **New → Blueprint**, select the same repository and review `render.yaml`. It builds the backend Dockerfile, starts FastAPI on port 8000, checks `/health`, and mounts a 1 GB persistent disk at `/data`. Render requires a paid service for a persistent disk. Review the plan and disk cost before applying. [Render Blueprints](https://render.com/docs/blueprint-spec) · [Persistent disks](https://render.com/docs/disks)
3. **Render environment:** Enter the two Groq keys, both model names, and the Vercel production origin when prompted. Apply the Blueprint. Once the service starts, copy its assigned HTTPS base URL and check its `/health` endpoint.
4. **Connect Vercel:** Under the frontend project's environment variables, set `VITE_API_BASE_URL` for **Production** to the Render base URL. Redeploy the frontend so Vite includes it in the build. Send a message from the production domain. If you change that domain, update `ALLOWED_ORIGINS` on Render and redeploy the backend.
5. **Verify persistence:** Send a successful chat with the terminal commands below. Save its session ID, restart the Render service, and request that session's messages again. The saved messages and metadata should match.

### Production environment variables

| Set on | Variable | Value and purpose |
| --- | --- | --- |
| Render | `LLM_API_KEYS` | Two distinct private Groq keys separated by a comma. The first is `key_1` and the second is `key_2`. |
| Render | `GROQ_MODEL_1`, `GROQ_MODEL_2` | LiteLLM model IDs for the primary and backup deployments. The examples in `.env.example` use the `groq/` prefix. |
| Render | `DATABASE_URL` | The Blueprint sets `sqlite:////data/app.db`. The four slashes point to the absolute path on the persistent disk. |
| Render | `ALLOWED_ORIGINS` | Paste the actual Vercel production origin, including `https://`. Omit paths and trailing slashes. Separate additional trusted origins with commas. FastAPI reads this setting on startup. |
| Render | `ENABLE_FAILURE_SIMULATION` | The Blueprint sets `true` so the evaluator can test both keys with a request header. |
| Render | `PORT` | The Blueprint sets `8000`, matching Uvicorn's port in the backend image. |
| Vercel | `VITE_API_BASE_URL` | The public HTTPS base URL of the Render backend. The browser app appends `/chat`. Keep Groq keys on Render. |

`BACKEND_PORT` and `FRONTEND_PORT` configure local Compose ports. Their defaults are 8000 and 3000.

## Design decisions: key fallback, caching, SQLite session storage

- **Fallback.** Both Groq deployments share the LiteLLM alias `chat-model`. The router tries `key_1` first. On failure it can call `key_2`. Reply metadata records the answering key ID and the number of failed attempts.
- **Cache.** LiteLLM looks up the shared model alias and the full message list, including the system prompt. This lets two new sessions share an identical first reply. A hit returns the original reply, model, and usage with `key_id: null`. The in-memory cache resets when the backend restarts. A failure-simulation request skips cache reads so you can exercise the provider path.
- **Sessions.** Each page load creates a fresh session ID. The browser sends only the new message and any initial system prompt. The backend reads that session's history and saves both sides of a successful turn in one transaction. Failed turns add nothing. History is returned oldest first.

## Verification: how to see failover, cache hits and per-message token usage

Use one terminal for the following commands. For local testing use the default `API` below. For deployment testing, set `API` to the actual Render HTTPS base URL first. The `chat` helper fixes the message text for the run, prints the HTTP status, and accepts an optional failure header.

```sh
API=${API:-http://localhost:8000}
API=${API%/}
run="demo-$(date +%s)"
chat() {
  session=$1
  shift
  curl -sS -w '\nHTTP %{http_code}\n' "$API/chat" \
    -H 'Content-Type: application/json' "$@" \
    -d "{\"session_id\":\"$session\",\"message\":\"Reply with the code $run.\"}"
}

curl -fsS "$API/health"
chat "$run-first"
chat "$run-cache"
chat "$run-backup" -H 'X-Simulate-Failure: key_1=429'
chat "$run-backup500" -H 'X-Simulate-Failure: key_1=500'
chat "$run-failed" -H 'X-Simulate-Failure: key_1=429,key_2=500'
chat "$run-failed" -H 'X-Simulate-Failure: *=429'
curl -fsS "$API/sessions/$run-first/messages"
curl -sS -w '\nHTTP %{http_code}\n' "$API/sessions/$run-failed/messages"
curl -sS -w '\nHTTP %{http_code}\n' "$API/chat" \
  -H 'Content-Type: application/json' -d '{"session_id":"validation","message":" "}'
```

| Check | Expected result |
| --- | --- |
| Health | HTTP 200 with `status: ok`, `keys_configured: 2`, and `cache_enabled: true`. |
| First and cached replies | `LIVE_INFERENCE` then `LLM_CACHE`. Compare identical text and token counts. The hit should be faster, with a null key ID and zero fallback attempts. |
| Primary failure | HTTP 200 with a real reply from `key_2`, `LIVE_INFERENCE`, and one fallback attempt. |
| Both keys fail | HTTP 503 with `{"detail":"all providers unavailable"}`. |
| History and validation | The successful session contains a user message then an assistant reply. The failed session returns 404. The blank message returns 422. |

In the browser, send a follow-up and inspect the source, model, latency, input tokens, and output tokens under each reply. Input tokens include that request's context. Output tokens count only its reply.

With the Python virtual environment installed, run the local tests and then check a running backend. The second command makes real Groq calls:

```sh
PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -v
.venv/bin/python backend/tests/verify_running.py --base-url "$API"
```

To check production CORS, set `WEB` to the actual Vercel production origin and run:

```sh
curl -si -X OPTIONS "$API/chat" -H "Origin: $WEB" \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type'
```

Expect HTTP 200 and an `access-control-allow-origin` header matching `WEB`.

## Setup Used: your editor and AI tools

I used OpenAI Codex to edit the project, run tests, and prepare the documentation. The local setup uses Python 3.12, Node.js 22, npm, and Docker Compose.

## Bonus features (if any)

The optional system prompt lets you set instructions before the first message. Its value stays with the session so you can guide later replies without retyping it.
