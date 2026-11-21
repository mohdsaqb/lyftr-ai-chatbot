# Lyftr demo recording

**Target length: 2 minutes 35 seconds.** Record the deployed frontend and backend with your voice. Use the quoted lines as narration after the result appears on screen.

### Before recording

Open the Vercel production page in a fresh browser tab. In a terminal, set `API` to the real Render base URL. Copy the setup lines from the README verification section through the closing brace of `chat()`. They create a fresh `run` value and define the helper without making a request.

Run `printf 'My demo code is %s. Repeat it.\n' "$run"` and copy the resulting sentence. Keep it in the clipboard so you can send exactly the same first message twice. Use a fresh code for each take. Leave the optional system prompt empty.

| Time | Show on screen | Say |
| --- | --- | --- |
| 0:00–0:20 | Show the deployed chat page. In the terminal, run `curl -fsS "$API/health"`. Point to the key count and cache status. | “This is my Lyftr chatbot. React runs on Vercel and FastAPI runs on Render. The health endpoint checks the database and shows that the backend has loaded two keys and enabled its response cache.” |
| 0:20–0:45 | Paste the copied sentence in the chat and send it. Point to the five metadata fields below the reply. | “The assistant repeated my code. The source is LIVE_INFERENCE. Here’s the model that answered and how long it took. The input and output token counts belong to this one request.” |
| 0:45–1:05 | Ask **What was my demo code?** Show both turns and the code in the second reply. | “I didn’t include the code in my follow-up. The backend read the earlier messages for this session from SQLite and included them in the model request.” |
| 1:05–1:30 | Reload the page. Paste the exact original sentence again. Point to `LLM_CACHE`, the reply text, token counts, and latency. | “Reloading starts a new session. This first message matches the earlier one, so LiteLLM returns the saved reply. The token counts come from that original response. You can see this request’s latency here.” |
| 1:30–2:00 | Run `chat "$run-backup" -H 'X-Simulate-Failure: key_1=429'`. Highlight the reply, `key_id`, `fallback_attempts`, and HTTP status. | “For this request I made the primary key behave as if Groq had rate-limited it. The backup returned an answer. The response shows key two, one failed attempt, and HTTP 200.” |
| 2:00–2:20 | Run `chat "$run-failed" -H 'X-Simulate-Failure: key_1=429,key_2=500'`. Leave the JSON error and HTTP 503 visible. | “Now both keys fail in the same request. The API returns 503 with a readable error. There is no assistant reply to save.” |
| 2:20–2:35 | Run the two history commands below. Show the successful turn and then the missing session. | “The successful session contains the user message followed by the assistant reply and its metadata. The failed session returns 404. Only completed turns entered the history.” |

```sh
curl -fsS "$API/sessions/$run-backup/messages"
curl -sS -w '\nHTTP %{http_code}\n' "$API/sessions/$run-failed/messages"
```
