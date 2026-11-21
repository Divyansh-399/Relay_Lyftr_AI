# Security and assignment review

Reviewed 21 November 2026 against the six-page Lyftr AI full-stack assignment.

## Submission status

| PDF requirement | Evidence | Status |
| --- | --- | --- |
| Three API routes, field names, JSON validation, 404 and 503 | FastAPI in-process tests check health, successful turns, malformed input, unknown histories and provider exhaustion | Passed with a controlled provider |
| Ordered failover and request-only simulation | Tests exercise 429, 500, 502, 503, wildcard and multiple-key rules, disabling the hook and normal routing after a simulation | Passed with a controlled provider. Live keys remain unverified |
| Model, reply, elapsed milliseconds and per-request usage | Tests compare first turns and verify identical cached text and usage, null cache key ID, zero cache retries and lower measured latency | Passed with test usage and controlled live latency. Real provider timings remain unmeasured |
| LiteLLM cache and HTTP provider integration | Production path uses LiteLLM and its local cache. A separate integration test drives the SDK against a local HTTP provider | Test included, skipped locally because LiteLLM was unavailable |
| Multi-turn, isolated sessions, system prompt, durable SQLite history | Tests reopen the database in a new application instance, overlap turns, and check failed writes leave history intact | Passed locally. Container restart with a mounted volume remains unverified |
| React UI, new session on refresh, metadata, input clearing and error recovery | All nine required or optional test IDs present. Browser contract test included in CI | Source checked. Browser test has not run here |
| Docker, Makefile, ports, volume, schema creation and environment variables | Both multi-stage Dockerfiles reviewed. Compose YAML parsed. CI job builds both images and checks their local URLs | Configuration present. Docker unavailable locally |
| Repository structure, tests, README and demo instructions | Required directories and configuration present. README has all six requested sections and a timed demo outline | Present. Live URLs section still needs the actual public URLs |
| Public frontend and backend, public GitHub repo, narrated 2–3 minute video and submission form | No public deployment, repo or recording was supplied for review | Outstanding. Verify all four links without login. The assignment sets a 24-hour deadline from receipt |

## Security findings

| Finding | Change or remaining exposure |
| --- | --- |
| Vite 6.4.1 fell in published dev-server advisory ranges and the dev command listened on all interfaces | Pinned Vite 6.4.6 and restored the loopback development default. The production image serves built files with Nginx |
| Anonymous requests could use provider capacity without an application-wide admission limit | Added a rolling-minute limit and an in-flight request cap, including simulated requests. Limits are shared across users. A provider-side spending cap is still needed to bound monetary exposure |
| Large request bodies, unlimited system instructions and long completions increased resource exposure | Limited streamed request bytes, body-read time, prompt and context size, and output tokens. Over-limit turns leave stored history intact |
| History URLs contain the session ID, and the original configuration allowed access logging and browser caching | Disabled Uvicorn access logs in the supplied launch commands and added no-store, no-referrer and nosniff API headers. Redact these paths in external proxy logs |
| The frontend interpolates the operator-provided API origin into runtime configuration | Docker startup now validates the configured origin. An Nginx CSP limits scripts to local files, connections to the app and configured API, and prevents framing. Static hosts require equivalent response-header configuration |
| Public session IDs grant read and append access to the associated chat | The browser generates random UUIDs. The PDF permits client-selected short IDs and anonymous history reads. Anyone with a known ID has access. Use the public deployment for demo content |
| Dependency and image assurance | CI now runs npm audit and pip-audit. Registries were unreachable locally. Transitive dependencies are not locked and container digests are not pinned. No clean dependency or image scan is claimed |

SQLite uses bound parameters for session identifiers and message text. React renders prompts and replies as text nodes. The application exposes no model-callable shell, filesystem or database tools. A pattern scan of project sources found no matching provider-key, GitHub-token or private-key patterns. These checks cover the reviewed files.

## Verification record

- **23 backend contract tests passed and one SDK integration test skipped.** Tests used FastAPI, SQLite, an in-process HTTP client, a controlled provider and a memory cache fixture. The restricted Windows runner used a socket-free test event loop. Its installed Starlette emitted one TestClient deprecation warning.
- Python source and YAML/JSON manifests parsed. Nine frontend selectors matched the PDF. Docker, hosted TLS/CORS, the actual frontend build, provider calls, dependency scans and the recorded demo remain unverified here.
- The repository includes a CI browser test with controlled chat responses and a live HTTP verifier that uses real provider calls. Once hosted, run the verifier with the public backend URL and repeat the demo in the deployed frontend.

Advisory references: [Vite dev-server advisory](https://github.com/advisories/GHSA-p9ff-h696-f583), [Vite releases](https://github.com/vitejs/vite/releases), [OWASP API resource consumption](https://api-security.owasp.org/editions/2023/en/0xa4-unrestricted-resource-consumption/).
