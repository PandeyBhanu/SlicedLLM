# SlicedLLM

An LLM evaluation platform: versioned prompts, token-level diffs, a tamper-evident audit trail, and durable A/B evaluation runs scored by a judge LLM. FastAPI + PostgreSQL backend, Next.js 15 dashboard.

> Engineering decisions, the current-vs-target architecture, failure-mode analysis, and an interview study guide live in [decisions.md](decisions.md). The original prototype audit is in [AUDIT.md](AUDIT.md).

## What it does

- **Prompt registry** — prompts with multiple semantic-versioned, *immutable* versions. Content changes are impossible (PostgreSQL trigger) and detectable (SHA-256 `content_hash` + `GET .../integrity`).
- **Token-level diff** — `tiktoken`-backed diffs (BPE units fused at UTF-8 boundaries) with per-segment token counts, similarity stats, and a hierarchical line-anchored algorithm for large prompts. Tokenizer is selectable per model/provider.
- **Append-only audit trail** — every state change writes a hash-chained `audit_logs` event (`seq`, `prev_hash`, `event_hash`, actor, request id, before/after state) in the *same transaction* as the change. Triggers reject UPDATE/DELETE/TRUNCATE; `GET /audit/verify` re-verifies the whole chain.
- **Durable A/B evaluations** — `POST /evaluations/runs` enqueues a run row; a DB-backed worker (`SELECT ... FOR UPDATE SKIP LOCKED`, heartbeat, stale-run recovery) executes it. Per case both candidate calls run concurrently, then one or two judge passes (position-swapped to cancel position bias). Everything is persisted: rendered prompts, outputs, tokens, latency, cost, per-criterion rubric scores, raw judge responses.
- **Dashboard** — Next.js UI for prompts/versions, diffs, datasets, run creation, live status polling, per-case results with candidate outputs and rubric breakdowns, and the audit/changelog timeline.

## Tech stack

| Layer    | Choice |
|----------|--------|
| API      | FastAPI, Pydantic v2, structlog |
| DB       | PostgreSQL (asyncpg + SQLAlchemy 2 async), Alembic |
| LLMs     | Ollama (local) and Groq (OpenAI-compatible). No OpenAI provider is implemented. |
| Worker   | In-process async worker polling the `evaluation_runs` table (also runnable standalone via `python -m app.jobs`) |
| Frontend | Next.js 15 App Router, React 18, TypeScript, TanStack Query, Tailwind, Recharts |
| Tests    | pytest + pytest-asyncio against **real PostgreSQL** (triggers, SKIP LOCKED, JSONB — never SQLite) |

## Quick start

```bash
# 1. PostgreSQL (or use docker-compose below)
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=slicedllm postgres:16-alpine

# 2. Backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                              # set GROQ_API_KEY if you want the cloud provider
alembic upgrade head                              # or leave AUTO_CREATE_SCHEMA=true
uvicorn app.main:app --reload --port 8000         # API + in-app worker

# 3. Frontend
cd frontend && npm install && cp .env.example .env.local
npm run dev                                       # http://localhost:3000
```

`docker-compose up -d` also works (Postgres + API with reload).

Standalone worker instead of in-app: set `RUN_WORKER_IN_APP=false`, then `python -m app.jobs`.

## Try it end to end

1. **Prompts** → create a prompt, create two versions, activate one.
2. **Diff** → pick the two versions; see token-level inserts/deletes and similarity.
3. **Datasets** → create a dataset, add cases (input text + optional expected behavior).
4. **Evaluation** → pick dataset + version A + version B + rubric + provider/model → submit.
5. **Results** → the run card polls while `PENDING`/`RUNNING`; click it to see per-case outputs, judge scores, rubric breakdown, tokens, cost, latency, and partial failures.
6. **Changelog** → every create/activate/rollback/run appears in the hash-chained audit trail; "verify chain" recomputes all hashes.

For a judge, the default rubric is seeded automatically on first run creation. A judge with a different model than the candidates can be selected on the Evaluation page.

## API map (all under `/api/v1`)

| Area | Endpoints |
|------|-----------|
| Prompts | `POST/GET /prompts`, `GET/PATCH /prompts/{id}` |
| Versions | `POST /prompts/{id}/versions`, `GET .../versions`, `GET .../versions/{vid}`, `POST .../activate`, `POST /prompts/{id}/rollback`, `GET .../integrity` |
| Diff | `GET /prompts/{id}/diff?version_a_id=..&version_b_id=..&model=..` |
| Changelog / audit | `GET /prompts/{id}/changelog`, `GET /prompts/{id}/audit`, `GET /audit/events`, `GET /audit/verify` |
| Datasets | `POST/GET /datasets`, `GET /datasets/{id}`, `POST /datasets/{id}/cases` |
| Evaluations | `POST/GET /evaluations/runs`, `GET /evaluations/runs/{id}`, `POST .../cancel`, `GET .../cases`, `GET .../summary`, `GET/POST /evaluations/rubrics` |

Interactive docs: http://localhost:8000/docs. Error shape is `{"error": {"code", "message", "details"}}` and is what the frontend reads.

## Configuration

See [.env.example](.env.example). Notables: `API_KEY` (optional shared `X-API-Key` auth), `EVALUATION_*` (concurrency, timeouts, retries), `JOB_*` (worker poll/heartbeat/recovery), `DEFAULT_JUDGE_PROVIDER`/`DEFAULT_JUDGE_MODEL`.

## Testing

```bash
# Point at a disposable PostgreSQL DB (its schema is dropped per test session)
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/slicedllm_test
pytest -q            # 178 tests
cd frontend && npx tsc --noEmit && npm run build
```

Tests require real PostgreSQL: the suite exercises triggers, `SKIP LOCKED` claiming, JSONB, advisory locks, and transaction isolation that SQLite cannot express. Tests simulate crash recovery, cancellation, 429s, malformed judge output, and audit tampering — no live LLM is needed.

## Known limitations (the honest list)

- One worker process executes runs; the queue is polled, not pushed. Fine up to ~O(100k) runs/day, then move to a real broker (see decisions.md §Scaling).
- `X-Actor-Id`/`X-API-Key` are asserted, not authenticated — there is no per-user auth or tenancy.
- Audit-chain truncation of the *tail* is only detectable with an external head checkpoint (`verify_audit_chain(expected_head=...)`).
- Judge quality depends on the judge model; a weak judge produces weak verdicts. Position-swap mitigates, not eliminates, bias.
- Cost is estimated from provider-reported token counts and per-provider pricing where available; treat it as approximate.
