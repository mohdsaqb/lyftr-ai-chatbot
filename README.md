# Lyftr AI Chatbot

Lyftr is a chat app that remembers earlier messages in a conversation. Each reply shows which model answered, how long it took, and how many tokens it used.

The frontend uses React and Vite. The Python backend uses FastAPI, LiteLLM to call Groq, and SQLite for chat history.

## Live URLs

[Open the chatbot](https://frontend-nine-azure-vflfvpvcat.vercel.app/) · [Check API health](https://lyftr-chat-api-qemo.onrender.com/health)

To try a multi-turn chat, send “My dog’s name is Pepper.” Then ask “What’s my dog’s name?” Refresh the page to start a new conversation.

## Run locally: with Docker and without

From the project root, copy the settings file once. In `.env`, set `LLM_API_KEYS` to two different Groq keys separated by a comma. Set `GROQ_MODEL_1` and `GROQ_MODEL_2` to models your account can use.

```sh
cp -n .env.example .env
```

**With Docker**, start both services with one command. Open [the local chatbot](http://localhost:3000). Run `docker compose down` to stop it. The named volume keeps your chat history between runs.

```sh
docker compose up --build -d
```

**Without Docker**, use Python 3.12 and Node.js 22.12 or later in the 22.x series. Start the backend in one terminal:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
set -a
. ./.env
set +a
DATABASE_URL=sqlite:///./app.db uvicorn app.main:app --app-dir backend --port "$BACKEND_PORT"
```

In a second terminal, start the frontend from the project root:

```sh
. ./.env
cd frontend
npm ci
VITE_API_BASE_URL="$VITE_API_BASE_URL" npm run dev -- --port "$FRONTEND_PORT"
```

### Deployment

- **Render backend.** Create a Blueprint from [render.yaml](render.yaml). Set the two keys and model names as above. Set `ALLOWED_ORIGINS` to the exact Vercel origin, including `https://` and without a trailing slash. The Blueprint sets `PORT=8000` and `ENABLE_FAILURE_SIMULATION=true` for the checks below.
- **SQLite storage.** The Blueprint uses a paid Render service with a persistent disk mounted at `/data`. Its `DATABASE_URL` is `sqlite:////data/app.db`, so history survives restarts. [Render disk documentation](https://render.com/docs/disks)
- **Vercel frontend.** Import the repository, select `frontend` as the root and **Vite** as the framework. Set `VITE_API_BASE_URL` to the Render backend URL and deploy. Rebuild the frontend if this URL changes. Keep both Groq keys on the backend.

## Design decisions: key fallback, caching, SQLite session storage

- **Key fallback.** Both Groq deployments use one LiteLLM alias, `chat-model`. If the primary call fails, the router tries the backup. The API reports which key answered.
- **Caching.** LiteLLM matches the full conversation, including the system prompt. Two new sessions with the same first message can share a reply. The cache is in memory and clears when the backend restarts.
- **Session storage.** SQLite saves the user message and assistant reply together after a successful turn. The history endpoint returns them oldest first. Failed turns add no messages.

## Verification: how to see failover, cache hits and per-message token usage

Run these commands in one terminal against the local backend. To test the hosted API, set `API=https://lyftr-chat-api-qemo.onrender.com` instead. The helper sends the same message to a different session each time.

```sh
API=http://localhost:8000
run="demo-$(date +%s)"
chat() {
  id="$run-$1"
  shift
  curl -sS -w '\nHTTP %{http_code}\n' "$API/chat" \
    -H 'Content-Type: application/json' "$@" \
    -d "{\"session_id\":\"$id\",\"message\":\"Repeat $run.\"}"
}

curl -sS "$API/health"
chat first
chat cached
chat backup -H 'X-Simulate-Failure: key_1=429'
chat failed -H 'X-Simulate-Failure: *=429'
curl -sS "$API/sessions/$run-first/messages"
```

| Request | What to look for |
| --- | --- |
| `GET /health` | `status` is `ok`, two keys are configured, and caching is enabled. |
| First and cached chats | The first returns `LIVE_INFERENCE`. The second returns `LLM_CACHE` with the same reply and token counts, and a null `key_id`. |
| Primary key fails | HTTP 200 with `key_id` set to `key_2` and `fallback_attempts` set to `1`. You can also try `key_1=500`. |
| Both keys fail | HTTP 503 with `all providers unavailable`. The simulation header works when `ENABLE_FAILURE_SIMULATION=true`. |
| Session history | The user message appears first, followed by the assistant reply and its metadata. |

The chatbot shows **input tokens** for the prompt and conversation sent to the model, and **output tokens** for the reply. The API returns both in `metadata`.

Run the backend tests from the project root after installing the Python dependencies:

```sh
PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests
```

## Bonus features

Use **System prompt** before your first message to set instructions for the whole conversation, such as “Answer in one sentence.”
