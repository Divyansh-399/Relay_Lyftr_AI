# Relay — LLM inference workspace

Relay is a React chat client with a FastAPI gateway, an ordered pool of provider keys, LiteLLM response caching and persistent SQLite conversations. Each reply exposes its source, model, latency, token counts and routing decision.

## Live URLs

Public deployment is pending. During local development use http://localhost:3000 for the frontend and http://localhost:8000/health for the backend.

**Deploy both tiers.** Create a public GitHub repository from this directory. Create a Docker web service from the repo with root directory `backend`, a persistent disk mounted at `/data`, one replica, the health check path `/health` and the backend variables from `.env.example`. Enter two distinct active keys for the same model in the hosting secret settings. Set `ENABLE_FAILURE_SIMULATION=true`. Create a second Docker web service using root directory `frontend`. Set its `API_BASE_URL` to the public HTTPS backend origin. Both images accept the host-provided `PORT`. Set the backend's `ALLOWED_ORIGINS` to the exact HTTPS frontend origin (no trailing slash), redeploy and run the live checker below. Record both public URLs here before submission. A static frontend host can alternatively use `npm install && npm run build`, publish `dist` and set `VITE_API_BASE_URL` at build time.

## Run locally: with Docker and without

**Docker.** Copy `.env.example` to `.env` and replace both placeholder keys. The default model uses OpenAI credentials. Another LiteLLM provider/model can be selected with `LLM_MODEL` and its matching keys. Run `make up` (or `docker compose up -d --build` on Windows). Open http://localhost:3000. Use `make down` to stop both services. The named volume retains chat history.

**Without Docker.** Use Python 3.12 and Node 22. From the root:

```sh
python -m venv .venv
# macOS/Linux
. .venv/bin/activate
# Windows PowerShell instead: .\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements-dev.txt
```

Copy the example environment file, set real keys and change `DATABASE_URL` to `sqlite:///data/app.db` for a relative local database. Run from the root:

```sh
python -m uvicorn main:app --app-dir backend --env-file .env --port 8000 --no-access-log
```

In a second terminal run `cd frontend`, `npm install` and `npm run dev`. Both local URLs match Docker defaults. Keep keys exclusively in the backend environment. Use a single backend process.

## Design decisions: key fallback, caching, SQLite session storage

- **Routing.** One model and an ordered credential pool keep responses comparable across routes. Each attempt calls LiteLLM with the next key, a 25-second timeout and SDK retries disabled. An unusable answer or provider exception advances the pool. Exhaustion returns JSON 503. A simulation skips the specified attempts for that request only and bypasses cache reads, so a cached prompt can still exercise the actual fallback provider.
- **Cache.** LiteLLM's local cache backend stores successful reply text and the provider's usage for one hour. Its key hashes the configured model and the full ordered system/user/assistant message list. This makes identical first turns reusable across sessions and keeps different histories distinct. Hits carry a null key ID and zero fallback attempts. Latency measures elapsed gateway processing through reply resolution. A restart clears the in-memory cache.
- **Persistence.** SQLite uses WAL, an ordered session index and one transaction for the system prompt and successful turn pair. Failure leaves prior history intact. Bounded asynchronous locks serialize turns that map to the same lock while the provider is awaited. One worker and one replica are intentional. A Docker volume retains history through restarts.
- **Public demo scope.** A session ID is a bearer reference to its history. The UI creates a random UUID on every page load. There is no user authentication. Set an appropriate provider spending cap for the public demo.
- **Public API limits.** One worker admits up to 60 chat attempts per rolling minute and eight in-flight requests by default. Tune these with `CHAT_REQUESTS_PER_MINUTE` and `CHAT_MAX_CONCURRENT`. These limits apply across all users. Reaching either returns JSON 429. The gateway limits body size to 128 KiB, body receipt to 15 seconds, system instructions to 4,000 characters, input context to 64,000 characters and each completion to 1,024 tokens. When a conversation fills, its history remains readable and the UI can start a new session.
- **History privacy.** The API sends no-store and no-referrer headers. The supplied backend container disables access logs. Configure the hosting proxy to omit or redact session-history paths as well. Anyone with a session ID can read and extend that conversation. Identical prompts and histories share a cache, as required by the assignment.

## Verification: how to see failover, cache hits and per-message token usage

1. Open the health link. Confirm at least two keys and an enabled cache. Ask a unique question, for example “My code word is fern-824. What is my code word?” Use your own suffix. The reply shows LIVE_INFERENCE, key_1 and this response's usage.
2. Open **Resilience Lab → Replay first turn**. This sends the first message and original instructions in a new session. Check identical text, LLM_CACHE, stored usage and measured latency.
3. Ask “What code word did I give you?” Open **Open history JSON** to see both successful turns in order.
4. Select **First key · 429**, then send a new question. Check key_2 and one retry. Select **All keys · 429** and send again. Observe the readable error and unchanged history. Switch to **Normal routing** to retry the restored draft.
5. Run `python scripts/verify_live.py https://YOUR-BACKEND` for an independent HTTP smoke test. It makes real, billable requests. Run backend regression tests with `cd backend && python -m pytest -q`. The LiteLLM integration test uses a local HTTP provider stub and needs no paid key. CI installs the SDK and builds the frontend.

**2–3 minute demo recording guide.** 0:00–0:25 open the deployed frontend and health endpoint and introduce the stack. 0:25–0:55 send a first question and point out both token counts. 0:55–1:20 replay it and compare source and latency. 1:20–1:45 ask a follow-up and open the history endpoint. 1:45–2:20 show single-key recovery, then all-key failure and unchanged history. 2:20–2:40 show the repo and explain the atomic SQLite write. Record the deployed app with your own voice, then submit the video link with both public service URLs and the public repo.

## Setup Used: your editor and AI tools

Implemented in the Codex workspace with OpenAI Codex assistance. Toolchain: React, Vite, FastAPI, LiteLLM, SQLite, pytest and Docker Compose.

## Bonus features (if any): what you added beyond the requirements and why

- **Resilience Lab** makes request-scoped failure controls and cache replay accessible to a reviewer directly in the browser.
- **Session inspector** shows replies, cache hits, key pool size and the latest route. Direct health and history links let a reviewer compare the UI with backend evidence.
- **Automated checks** cover failure atomicity, persisted history, concurrent turns and cache context. The live verifier exercises the deployed contract with a unique prompt on each run.

