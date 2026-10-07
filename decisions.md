# SlicedLLM — Design Decisions & Interview Study Guide

This document is the single source of truth for *why* the system looks the way it does.
Every section marks its status:

- **[implemented]** — in the code and covered by tests.
- **[design]** — a deliberate decision worth explaining.
- **[limitation]** — real, admitted gap between this and production.
- **[proposed]** — target architecture; *not* implemented.

---

## 1. What the system does

SlicedLLM answers one question well: **"did changing this prompt make the model better?"**

```
prompt + versions  ──►  diff (token-level)  ──►  A/B evaluation run
       │                                              │
       ▼                                              ▼
audit trail (hash-chained, append-only) ◄──  judge LLM scores per rubric
```

Core loop: create a prompt, create version A and B, diff them, run both against the
same dataset in parallel, have a judge LLM score both outputs against a rubric
(twice, with presentation order swapped), and keep an auditable record of every
state change along the way.

---

## 2. Current architecture  [implemented]

```
┌─────────────┐      HTTP/JSON       ┌──────────────────────────────────────────┐
│  Next.js 15 │ ◄──────────────────► │              FastAPI app                 │
│  dashboard  │   poll run status    │                                          │
└─────────────┘                      │  /api/v1/prompts | datasets | evaluations│
                                     │  /api/v1/audit                           │
                                     │                                          │
                                     │  services ──► repositories ──► models    │
                                     │      │                                   │
                                     │      └──► AuditService (same tx)         │
                                     │                                          │
                                     │  JobWorker (in-app, RUN_WORKER_IN_APP)    │
                                     │    └─► RunExecutor                       │
                                     │          ├─► ProviderGate (cap + rps)    │
                                     │          ├─► candidates: A ∥ B           │
                                     │          └─► judge: pass0 ∥ pass1        │
                                     └──────────────┬───────────────────────────┘
                                                    │ asyncpg
                                            ┌───────▼────────┐
                                            │   PostgreSQL   │
                                            │  11 tables +   │
                                            │  3 triggers    │
                                            └────────────────┘
                                                    ▲
                              Ollama / Groq ◄───────┘ (provider HTTP calls)
```

**Request flow (read):** Next.js page → TanStack Query hook → `api-client.ts` →
FastAPI endpoint → service → SQLAlchemy → Postgres → response schema → typed TS.

**Request flow (submit run):**
`POST /evaluations/runs` validates (dataset, both versions, rubric) → inserts
`evaluation_runs` row `PENDING` + audit event, commits, returns `202`.
The worker polls, claims the row with `SELECT FOR UPDATE SKIP LOCKED`, executes
the run with **its own** sessions, writes per-case results atomically, sets a
terminal status. The UI never blocks — it polls `GET /runs/{id}`.

## 3. Data model  [implemented]

```
prompts 1───n prompt_versions            (prompt_id, semantic_version) UNIQUE
                                         partial UNIQUE (prompt_id) WHERE is_active
                                         content_hash sha256; immutable via trigger

evaluation_datasets 1───n evaluation_cases   (dataset_id, ordinal) UNIQUE

rubrics            — name+version UNIQUE, criteria JSONB, definition_hash

evaluation_runs    — THE QUEUE. dataset_id, prompt_version_a_id, prompt_version_b_id,
                     rubric_id, provider, model, judge_provider, judge_model,
                     config JSONB (full RunConfig snapshot), status CHECK,
                     cancel_requested, attempts, locked_by, heartbeat_at,
                     total_cases, created_by, started_at, completed_at

evaluation_results — (run_id, case_id) UNIQUE → idempotency key.
                     status, error, winner, score_a/b, confidence, position_consistent

candidate_outputs  — (run_id, case_id, slot) UNIQUE. rendered_prompt, output_text,
                     provider, model, generation_params, prompt/completion/total
                     tokens, estimated_cost, latency_ms, attempts, started/completed_at

judge_evaluations  — (result_id, pass_index) UNIQUE. swapped flag, raw_response,
                     raw_score JSONB, winner, scores (rubric + normalized 0..1),
                     confidence, reasoning, tokens, cost, latency, attempts

rubric_scores      — (judge_evaluation_id, criterion) UNIQUE. score_a, score_b, reason

audit_logs         — seq UNIQUE gap-free, prev_hash, event_hash UNIQUE,
                     actor_id, request_id, entity_type, entity_id, action,
                     before_state/after_state JSONB, content_hash
                     append-only via 2 triggers (row + statement/TRUNCATE)
```

Why this shape: **immutable versions** make a run reproducible (the FK pins exactly
what was executed); **result uniqueness** makes case processing idempotent;
**the run row is the job** so no separate queue infra is needed; per-pass judge rows
keep both orderings so position bias is inspectable, not hidden.

## 4. Durable execution & job lifecycle  [implemented]

The prototype used `asyncio.create_task` with a request-scoped session — the task
died with the request or crashed on a closed session. Now `evaluation_runs` *is* the
queue (`app/jobs/queue.py`):

- **claim** — oldest `PENDING` row, `FOR UPDATE SKIP LOCKED`; many workers can't take the same run.
- **heartbeat** — worker refreshes `heartbeat_at` each interval and reads `cancel_requested` in the same UPDATE.
- **cancel** — API sets `cancel_requested` (PENDING → CANCELLED immediately). The heartbeat loop sees it, sets a cancel event, workers stop pulling new cases, in-flight tasks are cancelled, run ends `CANCELLED` with finished cases kept.
- **crash recovery** — `RUNNING` + stale heartbeat → back to `PENDING` (attempts < max) or `FAILED`. Startup recovery treats all `RUNNING` as orphans (single-worker assumption).
- **resume** — the plan loads case IDs already having a result and skips them; the unique `(run_id, case_id)` constraint makes a duplicate write a no-op (`IntegrityError` → rollback → skip).
- **shutdown** — `CancelledError` propagates leaving the run `RUNNING`; the next worker's recovery pass requeues it. Nothing is silently lost.

State machine: `PENDING → RUNNING → COMPLETED | FAILED | CANCELLED` (DB CHECK constraint).

## 5. Parallel A/B execution  [implemented — `app/evaluation/runner.py`]

Per case: `asyncio.gather(generate A, generate B)` — genuinely concurrent, identical
`case.input_text`, each side rendered through *its own* template with its own
`provider_config` generation params. Judge passes also run via `gather` when two
orderings are configured.

Concurrency is bounded at three levels (no unbounded task creation):

1. `case_concurrency` case-worker tasks pulling from an `asyncio.Queue` (default 4).
2. Per case: ≤2 generation + ≤2 judge tasks → live tasks ≤ `case_concurrency*2 + 2`.
3. `ProviderGate`: a shared semaphore caps total in-flight LLM calls
   (`max_inflight_requests`, default 8), optional `requests_per_second` pacing, and a
   **shared 429 cool-down** — one rate-limit pauses everyone instead of each task
   retrying into the wall.

Retries: exponential backoff in `call_llm` (`app/evaluation/calls.py`); errors are
classified (`_classify`) — timeouts/429/5xx retried, 4xx not. A failed candidate
call still persists a `candidate_outputs` row with `status=FAILED`, error, attempts,
timing — partial failure is data, not a silent gap.

Tested: temporal overlap of A and B is asserted with timestamps in
`tests/test_evaluation_pipeline.py`.

## 6. Judge LLM  [implemented — `app/evaluation/judge.py`]

The judge sees: input, expected behavior, the rubric, and two responses labelled
"Response A"/"Response B". It **never** sees version numbers, model names, latency,
or token counts — only what should drive the verdict.

- **Structured output**: JSON mode; `parse_verdict` extracts the JSON object;
  `JudgeVerdict` (Pydantic) enforces exact criterion set, scores in range,
  `confidence ∈ [0,1]`, winner consistent with criterion scores. Malformed output is
  retried with the validation error fed back to the judge; after `max_attempts` →
  `JudgeError`, recorded as a `FAILED` judge_evaluation row. **No score is ever invented.**
- **Position bias**: `judge_position_strategy` = `both` (default: two passes — A-first
  and B-first — concurrently), `alternate` (deterministic per case via
  `plan_passes`), or `none`. `normalize` maps a swapped call back to candidate terms;
  `combine_passes` averages normalized scores, derives confidence from pass
  agreement, and sets `position_consistent` when both orders pick the same winner.
- **Confidence is computed**, not hard-coded (the prototype's `0.85` is gone).
- Rubrics are versioned rows (`name`, `version`, criteria JSONB with weights,
  `definition_hash`) — a run pins `rubric_id` *and* records `rubric_version` on each
  judge row, so scores remain interpretable after a rubric is edited.

## 7. Immutability & the audit trail  [implemented]

**Prompt versions:** all content columns (`template`, `semantic_version`,
`metadata_json`, `provider_config`, `content_hash`, `created_at`, FKs) are frozen by
the `trg_prompt_versions_immutable` trigger (`app/db/ddl.py`); only `is_active` may
change. `content_hash` is a SHA-256 over canonical JSON of the content —
`GET .../integrity` recomputes it and reports tampering. Activation flips flags in
one transaction; rollback = "activate an older version" — no history is rewritten.

**Audit trail** (`app/audit/service.py`): every mutation appends an event *in the
same DB transaction* as the change (atomic — both or neither). Each event carries a
gap-free `seq`, `prev_hash`, and `event_hash = sha256(canonical_json(fields))`.
Appends are serialized by a transaction-scoped advisory lock (`pg_advisory_xact_lock`)
so two writers can never fork the chain head. Triggers reject UPDATE/DELETE/TRUNCATE.
`verify_audit_chain` recomputes everything and reports `missing_events`,
`broken_chain`, `modified_event`, `out_of_order`, and — with an externally stored
`expected_head` — tail truncation.

**Actor identity:** `X-Actor-Id` header → `AuditContext` → `actor_id` on every event;
`request_id` (middleware-generated or `X-Request-ID`) links an event to its HTTP request.

**[limitation]** Triggers don't stop a superuser; the hash chain is the tamper-*evidence*
layer. Tail deletion without a checkpoint is undetectable — production would export
signed head checkpoints (see §11).

## 8. Reproducibility  [implemented]

Rerun the same evaluation and you can explain any difference:

- `evaluation_runs` pins `prompt_version_a_id`/`b_id` (immutable content), `rubric_id`,
  provider+model for candidates *and* judge, and the full resolved `RunConfig` JSONB
  (concurrency, timeouts, retries, judge strategy, temperature).
- `candidate_outputs` stores `rendered_prompt` (post-template), `generation_params`,
  provider-reported token counts, `estimated_cost`, `latency_ms`, `attempts`.
- `judge_evaluations` stores `raw_response`, parsed `raw_score`, per-criterion
  `rubric_scores`, `rubric_version`, `swapped`.
- `total_cases` pins the case set at submission — cases added to the dataset later
  are excluded; a resume only processes cases without a result.

Non-determinism that remains: model drift on the provider side, sampling
temperature, and judge stochasticity — which is *why* the raw records matter.

## 9. Frontend architecture  [implemented]

Next.js 15 App Router; all data via `src/lib/api-client.ts` (typed against
`src/types/api.ts`) through TanStack Query hooks in `src/hooks/use-api.ts`.

| Page | Route | Shows |
|------|-------|-------|
| Dashboard | `/` | counts, recent runs, system state |
| Prompts | `/prompts` | CRUD, versions, activate/rollback, integrity badge, changelog link |
| Diff | `/diff` | token-level segment highlighting, stats, tokenizer info, line/char fallback |
| Datasets | `/datasets` | dataset + case management |
| Evaluation | `/evaluation` | dataset, A/B versions, rubric, provider/model, judge + position strategy |
| Results | `/results` | run list + per-run detail: per-case status, A/B outputs, judge verdicts, rubric bars, tokens/cost/latency, summary aggregates |
| Changelog | `/changelog` | per-prompt changelog + global audit events, chain verification |

Long evaluations (**the 30-minute answer**): submit returns `202` immediately — the
HTTP request is *not* the evaluation. The Results page polls `GET /runs/{id}` while
`PENDING`/`RUNNING` (TanStack `refetchInterval`), showing progress
(completed/failed/total). Navigating away is safe — state lives in Postgres, not in
the tab. Returning re-polls. `POST .../cancel` works mid-run; completed cases are
kept. Refreshing never resubmits — submission is an explicit POST, reads are GETs.

Contract safety: `tests/test_api_contract.py` parses `api-client.ts`, checks every
call exists in the OpenAPI schema with the right method, and asserts the TS
interfaces cover every field the real API returns (driven by an actual run).

## 10. Security  [implemented defenses; limits admitted]

| Threat | Attack | Defense | Limitation |
|--------|--------|---------|------------|
| Unauthenticated use | Anyone calls the API | Optional `API_KEY` → `X-API-Key` header gate (`deps.require_api_key`), tested in `test_api_contract` | Shared key only; no per-user authn/z |
| Authorization | User A modifies user B's prompts | — | **[limitation]** No ownership model; single-tenant assumption |
| Prompt injection | Dataset input contains "ignore your instructions" | The *evaluated* prompt is the target — injection is the thing being tested. Judge prompt keeps responses as data inside a fixed JSON-schema instruction | A judge can still be manipulated by candidate text — inherent to LLM judges; position-swap + strict schema reduce payoff |
| API abuse | Oversized diffs, giant runs | 2 MB cap per diff input; `EVALUATION_MAX_CASES_PER_RUN`; Pydantic validation everywhere | No per-actor rate limiting on the API itself |
| Audit tampering | UPDATE/DELETE history | Append-only triggers + hash chain + `verify` endpoint | Superuser can bypass; tail truncation needs external checkpoint |
| Version tampering | Edit historical prompt | Immutability trigger + `content_hash` + `/integrity` endpoint | Hash detects, trigger prevents — both live in the same DB being defended |
| Secrets leak | Keys in code/logs | `GROQ_API_KEY` env-only, never in requests/responses; structlog doesn't log bodies | Provider keys are plaintext env vars; no KMS/rotation |
| Malicious eval input | Giant/binary case text | Pydantic + DB text limits, per-call timeouts | No content scanning |
| XSS | Prompt/output text rendered in UI | React escapes by default; diff renderer escapes server-side too (`to_safe_html`) | `dangerouslySetInnerHTML` is never used — keep it that way |
| SQL injection | Crafted strings in any field | SQLAlchemy bound parameters everywhere; DDL fixed strings only | — |
| SSRF | Provider base URL points at internal IP | `OLLAMA_BASE_URL`/`GROQ_BASE_URL` are operator config, not user input | Users can't set URLs per-request, but nothing stops a bad operator config |
| Rate/cost abuse | Submit huge runs to burn provider quota | Case cap, in-flight cap, rps pacing, shared 429 cool-down, per-run cost accounting | No per-actor budget enforcement |

## 11. Failure modes  [implemented behavior]

| Component | Failure | Detection | Recovery | User impact |
|-----------|---------|-----------|----------|-------------|
| LLM call | Timeout | `asyncio.timeout` per call | Exponential backoff ×`max_retries` → output `FAILED` row | One case marked failed; run continues |
| LLM call | 429 | Response classified in `_classify` | `ProviderGate.cool_down` pauses *all* tasks, then retry | Transient slowdown, no data loss |
| LLM call | 5xx | classification | retried w/ backoff | same as timeout |
| LLM call | Malformed/4xx | classification | not retried (won't help) | case failed with the real error |
| Judge | Invalid JSON/schema | Pydantic validation | retry w/ error fed back; then `FAILED` judge row | result kept, winner = null |
| Judge | Position disagreement | both passes compared | `position_consistent=false`, confidence lowered | visible in UI, not hidden |
| Database | Down mid-run | SQLAlchemy exception | run stays RUNNING → heartbeat stales → requeued | delayed, resumed where it left off |
| Worker | Crash/kill | heartbeat staleness | `recover_interrupted` requeues (< max_attempts) | run resumes; finished cases skipped |
| Worker | Exhausted attempts | attempts ≥ max | run → `FAILED` with error | visible failure, not a hang |
| Frontend | Disconnect/refresh | — | state in Postgres; poll resumes on return | none |
| Duplicate job | Two workers claim | `SKIP LOCKED` | impossible — lock is per-row | none |
| Duplicate case write | retry/resume overlap | `(run_id,case_id)` UNIQUE | `IntegrityError` → skip | none |
| Audit | Corrupted record | `verify_audit_chain` | reported per-seq; ops unaffected | detected, must investigate |
| Audit | Tail deleted | head checkpoint mismatch | detected only with `expected_head` | [limitation] |
| Evaluation | Partial failure | per-case status | run still `COMPLETED`, error field notes N failed | honest partial results |

## 12. Observability  [implemented + proposed]

Implemented: `structlog` JSON logs; middleware binds `request_id` (or `X-Request-ID`)
to every event and emits method/path/status/duration; worker logs claim/finish with
`run_id`, recovery logs warnings; audit events carry `request_id` + `actor_id` for
correlation from HTTP request → DB change → audit row. Per-call latency, token
counts, cost, and attempt counts are persisted per output and per judge pass —
that *is* the metrics substrate.

**[proposed]** Production: expose `/metrics` (Prometheus) — run throughput, case
latency p50/p95/p99, judge agreement rate, failure rate by provider, queue depth,
heartbeat staleness; OpenTelemetry traces around run→case→call; dashboards per
provider; alerts on stale-heartbeat count, failure-rate spikes, queue depth growth,
audit verification failures.

## 13. Scaling — target ~10M evaluations/month  [proposed]

10M runs/month ≈ 4/s average, ~40/s peak; if each run has ~50 cases → ~2000
case-evaluations/s ≈ 4000+ LLM calls/s plus judge calls. Nothing about the
*design* breaks; several *mechanisms* do.

```
                         ┌──────────┐
        clients ──► LB ─►│ API pods │  (stateless FastAPI, N replicas)
                         └────┬─────┘
                              │ enqueue
                    ┌─────────▼─────────┐         ┌──────────────┐
                    │  Queue (SQS /     │◄────────│   Postgres   │ (metadata, audit,
                    │  RabbitMQ / Redis)│  ack    │  + read replica│  versions)
                    └─────────┬─────────┘         └──────┬───────┘
                              │ lease                  │ writes
                    ┌─────────▼─────────┐              │
                    │  Worker pool      │──────────────┘
                    │  (autoscaling,    │   ┌────────────────────┐
                    │   K8s/ECS, per-   │──►│ Object storage S3  │ raw outputs,
                    │   provider lanes) │   │ (versioned prompts │ large payloads)
                    └─────────┬─────────┘   └────────────────────┘
                              │                 ┌────────────────────┐
                    ┌─────────▼─────────┐       │ Analytics warehouse│
                    │ Provider gateways │       │ (ClickHouse/BQ)    │ aggregates,
                    │ (rate-limit aware)│       └────────────────────┘ dashboards
                    └───────────────────┘
                              │
                     Ollama fleet / Groq / …
```

What changes and why:

- **Brokered queue** — `SKIP LOCKED` polling tops out around thousands of pending
  rows and adds DB load per worker; SQS/RabbitMQ give visibility timeouts, dead-letter
  queues, and cheap fan-out. The `evaluation_runs` row remains the *record*; the
  broker just carries `run_id`.
- **Worker autoscaling** — per-provider worker pools with per-provider gates;
  backpressure = queue depth, not semaphore exhaustion.
- **PostgreSQL** — writes stay modest (runs+audit); heavy read paths (results
  listing, dashboards) move to a **read replica**; `audit_logs` and results tables
  **partition by month**; old partitions are cheap to archive/verify offline.
- **Object storage** — `output_text`/`raw_response`/`rendered_prompt` payloads get
  large at scale: store blobs in S3, keep pointers + hashes in Postgres. Bonus: hash
  the blob to extend tamper-evidence to payloads.
- **Analytics** — aggregates (win rates, cost/day) from a columnar store, not
  `GROUP BY` on the OLTP database.
- **Audit at scale** — periodic signed head checkpoints exported to a different
  trust domain (closes the tail-destruction gap in §7).
- **Multi-tenancy** — real auth (OIDC), `tenant_id` on every table, row-level
  security, per-tenant quotas — the single biggest functional gap.
- **Cost controls** — per-tenant token budgets enforced at claim time; provider
  routing rules (cheap model first, escalate on judge disagreement).

## 14. If I rebuilt it  [design]

- **Start with the broker** only if day-one scale demands it — the DB queue was the
  right call for this stage: zero infra, transactional enqueue, trivially testable.
- **Real auth + tenancy first**, not last: retrofitting `tenant_id` is the painful one.
- **Event-sourced prompt versions** (a versions table *is* basically this) — keep it.
- **Judge as a separate service** with its own queue so judge upgrades don't couple
  to run execution; keep the two-pass protocol identical.
- **Result payloads in object storage from the start**, pointers in Postgres.
- Keep: PostgreSQL, async SQLAlchemy, hash-chained audit, immutable versions,
  in-transaction audit writes, position-swapped judging, Pydantic-everywhere.

## 15. Implementation map — interview navigation  [implemented]

| Feature | File | Class | Function | Table | API | Frontend |
|---|---|---|---|---|---|---|
| Create prompt | `app/services/prompt.py` | `PromptService` | `create_prompt` | `prompts`, `audit_logs` | `POST /prompts` | `/prompts` |
| Create version | `app/services/prompt.py` | `PromptService` | `create_prompt_version` | `prompt_versions`, `audit_logs` | `POST /prompts/{id}/versions` | `/prompts` |
| Immutable content | `app/db/ddl.py` | — | `prompt_versions_enforce_immutability()` (trigger) | `prompt_versions` | `GET .../integrity` | `/prompts` badge |
| Content hash | `app/promptops/hashing.py` | — | `canonical_json`, `sha256_hex` | `prompt_versions.content_hash` | — | — |
| Semver | `app/promptops/versioning.py` | `SemanticVersion` | `suggest_next_version` | — | — | version picker |
| Activate / rollback | `app/services/prompt.py` | `PromptService` | `activate_version`, `rollback_prompt_version`, `_transition` | `prompt_versions.is_active` | `POST .../activate`, `POST .../rollback` | `/prompts` |
| Token diff | `app/diff/engine.py` | `DiffResult` | `diff_texts` | — | `GET /prompts/{id}/diff` | `/diff`, `diff-view.tsx` |
| Tokenizers | `app/diff/tokenizers.py` | `TiktokenTokenizer`, `Line/CharTokenizer` | `get_tokenizer` | — | `?model=&tokenizer=` | granularity picker |
| Audit append | `app/audit/service.py` | `AuditService` | `append` | `audit_logs` | `GET /audit/events` | `/changelog` |
| Audit verify | `app/audit/service.py` | `AuditVerification` | `verify_audit_chain` | `audit_logs` | `GET /audit/verify` | `/changelog` |
| Actor identity | `app/core/context.py`, `app/api/deps.py` | `AuditContext` | `get_audit_context` | `audit_logs.actor_id` | `X-Actor-Id` header | `.env.local` |
| Datasets | `app/services/evaluation.py` | `EvaluationService` | `create_dataset`, `add_case_to_dataset` | `evaluation_datasets`, `evaluation_cases` | `POST/GET /datasets*` | `/datasets` |
| Submit run | `app/services/evaluation.py` | `EvaluationService` | `create_run` | `evaluation_runs`, `audit_logs` | `POST /evaluations/runs` | `/evaluation` |
| List/poll runs | `app/services/evaluation.py` | `EvaluationService` | `list_runs`, `get_run`, `_progress` | `evaluation_runs`+counts | `GET /evaluations/runs[/{id}]` | `/results` |
| Cancel | `app/services/evaluation.py` | `EvaluationService` | `cancel_run` | `evaluation_runs.cancel_requested` | `POST .../cancel` | results page |
| Claim work | `app/jobs/queue.py` | — | `claim_next_run` (SKIP LOCKED) | `evaluation_runs` | — | — |
| Heartbeat/recovery | `app/jobs/queue.py` | — | `heartbeat`, `recover_interrupted` | `evaluation_runs` | — | — |
| Worker | `app/jobs/worker.py` | `JobWorker` | `run_once`, `run_forever` | — | — | — |
| Execute run | `app/evaluation/runner.py` | `RunExecutor` | `execute`, `_run_cases`, `_process_case`, `_persist_case`, `_finalize` | results/outputs/judge rows | — | — |
| LLM call layer | `app/evaluation/calls.py` | `ProviderGate`, `LLMCallError` | `call_llm`, `_classify` | — | — | — |
| Providers | `app/providers/{base,factory,ollama,groq}.py` | `BaseLLMProvider` | `generate` | — | — | provider select |
| Judge | `app/evaluation/judge.py` | `JudgeVerdict`, `JudgeConfig` | `run_judge_pass`, `parse_verdict`, `combine_passes`, `plan_passes`, `normalize` | `judge_evaluations`, `rubric_scores` | — | rubric bars, verdicts |
| Rubrics | `app/evaluation/rubrics.py`, `app/services/evaluation.py` | — | `validate_criteria`, `rubric_hash`, `ensure_default_rubric` | `rubrics` | `GET/POST /evaluations/rubrics` | `/evaluation` |
| Aggregates | `app/evaluation/summary.py` | — | `wilson_interval`, `percentile`, `criterion_means` | — | `GET .../summary` | results charts |
| Render template | `app/promptops/templates.py` | — | `render_template` | — | — | — |
| Error envelope | `app/core/exceptions.py` | — | `register_exception_handlers` | — | `{error:{code,message}}` | api-client error path |
| Auth gate | `app/api/deps.py` | — | `require_api_key` | — | `X-API-Key` | — |
| Migration | `alembic/versions/8e293da6f78f_*.py` | — | `upgrade` (incl. triggers) | all | — | — |

## 16. Interview questions

### Beginner
- **Why version prompts at all?** Prompts are code. Without versions you can't
  reproduce a regression or attribute a quality change to a specific edit.
- **What does the audit log record?** Actor, request, entity, action, before/after
  state, sequence, and a hash linking it to the previous event — written atomically
  with the change it describes.
- **Why PostgreSQL and not a file?** Transactions, constraints, JSONB, `SKIP LOCKED`,
  triggers — the features that make the guarantees real.

### Intermediate
- **How is a version "immutable"?** Two layers: a `BEFORE UPDATE OR DELETE` trigger
  rejects changes to content columns; `content_hash` + `/integrity` lets anyone
  verify content didn't change out-of-band.
- **Why write audit events in the same transaction?** Otherwise a crash between
  "change" and "log" produces a silent gap — exactly the events an attacker (or a
  bug) would hide.
- **Why `SKIP LOCKED` instead of a broker?** Fewest moving parts, transactional with
  the state it protects, trivially testable; the trade is polling cost and a single
  ordering dimension.
- **How do you bound concurrency?** `case_concurrency` queue workers for scheduling,
  `ProviderGate` semaphore for in-flight calls, `requests_per_second` for pacing.
  Tasks never grow with dataset size.

### Advanced
- **How does recovery work without losing work?** Heartbeats mark liveness; a stale
  `RUNNING` row is requeued; completed cases are skipped via the `(run_id, case_id)`
  uniqueness constraint, which also makes retry writes no-ops. At-least-once
  execution + idempotent writes = effectively-once results.
- **Why hash-chain the audit log?** A mutable table can be edited invisibly. Chaining
  `prev_hash → event_hash` means any edit/delete/reorder breaks verification. The
  remaining hole — deleting the newest N rows — is why you export signed head
  checkpoints (documented, not implemented).
- **How is judge position bias handled?** Two passes with A/B order swapped,
  concurrently; `normalize` maps results back to candidate terms;
  `combine_passes` averages and flags `position_consistent`. Confidence is derived
  from agreement, never assumed.
- **What happens when the judge outputs garbage?** Schema validation fails → retry
  with the validation error in the prompt → after `max_attempts`, a `FAILED`
  `judge_evaluations` row records the raw response and error. The result keeps its
  outputs; it just has no winner.

### System design
- **Scale to 10M evals/month?** See §13: broker the queue, autoscale worker pools per
  provider, read replica for dashboards, monthly partitions, S3 for payloads,
  warehouse for analytics, signed audit checkpoints, real multi-tenancy.
- **Where are the consistency boundaries?** Same-transaction: state change + audit.
  Atomic per case: result + outputs + judge rows. Eventual: queue polling delay,
  heartbeat staleness window.

### LLM/GenAI specifics
- **Why a judge LLM instead of heuristics?** Heuristic scoring can't assess
  correctness/helpfulness/tone; an LLM judge with an explicit rubric scales to
  open-ended quality — at the price of judge variance, which is why passes are
  validated, swapped, and persisted raw.
- **How do you keep the judge honest?** Fixed system prompt ("ignore order, don't
  favor length"), blind labels (never model/version names), strict JSON schema,
  position swap, persisted raw responses for auditing.
- **Why token-level diff?** Prompt cost/latency live in tokens. Whitespace splits
  mislead: `don't` is multiple tokens; punctuation is a token; Unicode varies wildly.
  The diff reports *token* counts — the unit you actually pay for.

### Database
- **Why JSONB for config/criteria?** Run config and rubric criteria are schemaless
  documents pinned at write time; JSONB keeps them queryable without a schema
  migration per field.
- **Why a partial unique index for active version?** "Exactly one active version per
  prompt" is a data invariant — enforce it where data lives, not in application
  code that races.

### Distributed systems
- **At-least-once vs exactly-once?** Claim is exactly-once (row lock); execution is
  at-least-once (crash mid-run retries); writes are idempotent (unique constraints +
  skip-existing). Exactly-once *delivery* is impossible — design for it.
- **Why heartbeats AND attempts?** Heartbeats detect death promptly; attempts cap
  infinite requeue of a poisoned run.

### Testing
- **Why real PostgreSQL in tests?** The guarantees under test *are* Postgres:
  triggers, advisory locks, `SKIP LOCKED`, JSONB, transaction isolation. SQLite
  would test a fiction.
- **How do you test a crash?** Don't crash — model it: insert a `RUNNING` row with a
  stale heartbeat, assert recovery. Plus a real `CancelledError` path for shutdown.

### Security
- **What's the trust model?** Optional shared API key at the edge; asserted actor
  identity; append-only + hash-evidence for history; DB constraints for invariants.
  Admitted gaps: no authz, no tenancy, tail-truncation needs external checkpoints.

## 17. Rapid-fire (50+)

1. **Why PostgreSQL?** Constraints, triggers, JSONB, `SKIP LOCKED`, advisory locks — the correctness features this system is built on.
2. **Why async?** Evaluation is I/O-bound: hundreds of concurrent LLM calls per run; threads would waste memory per connection.
3. **Why a queue?** Evaluations outlive HTTP requests; durable state survives restarts.
4. **Why DB-as-queue?** Zero new infra, transactional with the data, `SKIP LOCKED` gives clean claiming.
5. **Why not Kafka?** Overkill: no replay/consumer-group needs, seconds-scale latency fine, huge ops burden.
6. **Why not Redis?** Not durable enough as sole queue without careful config; adds infra.
7. **Why not Celery?** Needs a broker anyway; the DB queue delivers the same semantics with fewer parts at this scale.
8. **Why immutable prompt versions?** Evaluation results are meaningless if the prompt you "ran" can change under you.
9. **How is immutability enforced?** Postgres trigger rejecting UPDATE/DELETE on content columns + content_hash verification.
10. **Why a hash, not just the trigger?** Defense in depth: hash detects out-of-band tampering the trigger can't see (e.g., superuser).
11. **Why semantic versions?** Communicate change size; sortable; familiar.
12. **Only one active version — how?** Partial unique index `WHERE is_active` — enforced by the DB, race-free.
13. **Rollback = ?** Activate an older immutable version; history is never rewritten.
14. **Why token-level diff?** Tokens are the unit of cost and the unit models see.
15. **Which tokenizer?** `tiktoken` BPE; selectable per model; `approximate` flag when using a fallback encoding.
16. **Diff large prompts?** Hierarchical: line-diff for anchors, token-diff inside changed hunks; oversized hunks flagged `coarse`.
17. **Why A/B testing?** Isolates prompt change as the variable against identical inputs.
18. **A and B parallel?** `asyncio.gather` on both generations — tested with timestamps.
19. **Bound concurrency how?** Case-worker queue + provider semaphore + rps pacing; never unbounded tasks.
20. **Why not threads?** GIL is fine for I/O but asyncio gives cheaper concurrency and clean cancellation.
21. **429 handling?** Classify, shared gate cool-down (everyone pauses once), then backoff-retry.
22. **Timeout handling?** Per-call `asyncio.timeout`; retried with backoff; final failure persisted as a FAILED output row.
23. **Why a judge LLM?** Open-ended quality isn't heuristic-scorable.
24. **Judge sees?** Input, expected behavior, rubric, blind "Response A/B".
25. **Judge never sees?** Version ids, model names, latency, tokens — no leakage channels for bias.
26. **Why structured output?** Unparseable verdicts are worthless; JSON + Pydantic schema makes them machine-checkable.
27. **Judge output invalid?** Retry with the error fed back; after max attempts, record FAILED with raw response — never invent a score.
28. **Why two judge passes?** Position bias: order-swapped passes; agreement → consistent, disagreement → lower confidence.
29. **`position_consistent`?** Both orderings picked the same winner; surfaced in results.
30. **Confidence from?** Judge-reported confidence + pass agreement via `combine_passes` — the old hard-coded 0.85 is gone.
31. **Rubric versioning why?** Scores must stay interpretable after criteria change; runs pin `rubric_id`, rows store `rubric_version`.
32. **Worker dies mid-run?** Heartbeat stales → requeued → finished cases skipped → resumes.
33. **Worker dies mid-case?** Case has no committed result → reprocessed on resume; unique constraint kills any duplicate.
34. **Cancel semantics?** Flag on the row; heartbeat reads it; workers drain; terminal CANCELLED, partial results kept.
35. **Duplicate submissions?** Each POST creates a distinct run (by design — reruns are first-class); workers can't double-claim a row.
36. **Duplicate case write?** `(run_id, case_id)` UNIQUE → IntegrityError → skip.
37. **API returns?** 202 + run id; UI polls. The request is not the job.
38. **Long run UX?** Poll status + progress; safe to leave/return; cancel anytime.
39. **Audit append atomicity?** Same transaction as the change — both commit or neither.
40. **Chain fork prevention?** `pg_advisory_xact_lock` serializes appends per transaction.
41. **Tamper detection?** Recompute hashes: modification, deletion (seq gap), reorder, back-dating, broken links all flagged.
42. **Tail truncation?** Only detectable with an external `expected_head` checkpoint — documented limit.
43. **Actor identity?** `X-Actor-Id` → AuditContext → `actor_id` per event; asserted not authenticated [limitation].
44. **Cost calc?** Provider-reported token counts × provider pricing where known — persisted per output/judge pass; approximate.
45. **Latency?** Measured per call (`started_at`/`completed_at`, `latency_ms`); aggregated p50/p95 in summary.
46. **Reproducible how?** Immutable versions + pinned rubric/provider/model/config + rendered prompt + raw judge response stored.
47. **What's NOT reproducible?** Provider model drift, sampling, judge stochasticity — that's why raw records exist.
48. **Schema migrations?** Alembic; migration `8e293da6f78f` creates all tables + triggers; autogenerate-drift-checked.
49. **Tests against?** Real PostgreSQL only — the guarantees under test don't exist in SQLite.
50. **How many tests?** 178 — triggers, concurrency, crash recovery, cancellation, judge validation, tamper detection, API contract.
51. **Frontend↔API contract?** Test parses `api-client.ts` vs OpenAPI schema and checks TS types cover actual responses.
52. **Biggest limitation?** Single-worker execution and no tenancy — the first two things §13 fixes.
53. **What would you build next?** Broker + autoscaled workers, real auth/tenancy, S3 payloads, signed audit checkpoints.

## 18. How to study this in an interview

1. **Lead with the invariant list** (§3–§7): immutable versions, one-active constraint,
   idempotent case writes, same-transaction audit, bounded concurrency. Interviewers
   reward people who think in invariants.
2. **Draw §2 cold.** It fits on a whiteboard: UI → API → services → Postgres; worker
   loop on the side; providers external.
3. **Know the run lifecycle** (`PENDING → RUNNING → terminal`) and be able to walk
   crash/cancel/duplicate through the rows that change.
4. **Volunteer limitations unprompted** — §7 tail truncation, §13 single worker.
   It signals you know the difference between implemented and imagined.
5. **Map drill**: pick any row in §15 and trace file → function → table → API → page
   in the repo.
