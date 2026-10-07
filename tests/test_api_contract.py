"""Frontend <-> backend contract: every call in frontend/src/lib/api-client.ts must exist in the
OpenAPI schema with the same HTTP method, and the TypeScript interfaces must cover the fields
the backend actually returns for the screens that depend on them."""

import re
from pathlib import Path

from app.jobs.worker import JobWorker
from app.main import app
from tests.helpers import (
    ScriptedProvider,
    builder_for,
    create_dataset_with_cases,
    create_prompt_with_versions,
    honest_handler,
    start_run,
)

FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "src"
CLIENT = (FRONTEND / "lib" / "api-client.ts").read_text(encoding="utf-8")
TYPES = (FRONTEND / "types" / "api.ts").read_text(encoding="utf-8")
PREFIX = "/api/v1"


def client_calls():
    """-> [(method, path_template)] extracted from api-client.ts."""
    calls = []
    for match in re.finditer(
        r"this\.(request|post)<[^>]*>\(\s*([`'])(.+?)\2(.*?)\)\s*;?\s*\n?\s*\}", CLIENT, re.S
    ):
        kind, _, path, rest = match.groups()
        method = "POST" if kind == "post" or "method: 'POST'" in rest else "GET"
        path = path.split("?")[0]
        path = re.sub(r"\$\{[^}]+\}", "{}", path)
        calls.append((method, path))
    return calls


def openapi_routes():
    routes = set()
    for path, ops in app.openapi()["paths"].items():
        norm = re.sub(r"\{[^}]+\}", "{}", path)
        for method in ops:
            routes.add((method.upper(), norm))
    return routes


def test_extracted_calls_are_plausible():
    calls = client_calls()
    assert len(calls) >= 20, calls
    assert ("POST", "/evaluations/runs") in calls and ("GET", "/evaluations/runs") in calls


def test_every_frontend_call_has_a_backend_route():
    routes = openapi_routes()
    missing = [(m, p) for m, p in client_calls() if (m, PREFIX + p) not in routes]
    assert not missing, f"frontend calls without a backend route: {missing}"


def interface_fields(name: str, _seen=frozenset()) -> set:
    m = re.search(rf"export interface {name}(?: extends (\w+))? \{{(.*?)\n\}}", TYPES, re.S)
    assert m, f"interface {name} missing in types/api.ts"
    fields = set(re.findall(r"^\s{2}(\w+)\??:", m.group(2), re.M))
    parent = m.group(1)
    if parent and parent not in _seen:
        fields |= interface_fields(parent, _seen | {name})
    return fields


async def test_ts_interfaces_cover_real_api_responses(client, session_factory):
    prompt_id, (v1, v2) = await create_prompt_with_versions(client)
    ds = await create_dataset_with_cases(client, n=1)
    run = await start_run(client, ds, v1, v2)
    await JobWorker(
        session_factory,
        builder_for(ScriptedProvider(honest_handler())),
        worker_id="w",
        heartbeat_interval=0.05,
    ).run_once()
    rid = run["id"]

    def check(body, ts_name, nested=()):
        fields = interface_fields(ts_name)
        extra = set(body) - fields
        assert not extra, f"{ts_name} is missing fields returned by the API: {sorted(extra)}"
        for key in nested:
            assert key in fields

    check((await client.get(f"/api/v1/prompts/{prompt_id}/versions")).json()[0], "PromptVersion")
    check((await client.get("/api/v1/prompts")).json()[0], "PromptSummary")
    check((await client.get("/api/v1/datasets")).json()[0], "EvaluationDataset")
    check((await client.get(f"/api/v1/datasets/{ds}")).json()["cases"][0], "EvaluationCase")
    check((await client.get(f"/api/v1/evaluations/runs/{rid}")).json(), "EvaluationRun")
    check((await client.get(f"/api/v1/evaluations/runs/{rid}/summary")).json(), "RunSummary")
    summary = (await client.get(f"/api/v1/evaluations/runs/{rid}/summary")).json()
    check(summary["slot_a"], "SlotMetrics")
    case = (await client.get(f"/api/v1/evaluations/runs/{rid}/cases")).json()[0]
    check(case, "CaseResult")
    check(case["outputs"][0], "CandidateOutput")
    check(case["judge_evaluations"][0], "JudgeEvaluation")
    check(case["judge_evaluations"][0]["rubric_scores"][0], "RubricScore")
    check((await client.get("/api/v1/evaluations/rubrics")).json()[0], "Rubric")
    check((await client.get(f"/api/v1/prompts/{prompt_id}/changelog")).json()[1], "ChangelogEntry")
    check((await client.get(f"/api/v1/prompts/{prompt_id}/audit")).json()[0], "AuditEvent")
    check((await client.get("/api/v1/audit/verify")).json(), "AuditVerification")
    check(
        (await client.get(f"/api/v1/prompts/{prompt_id}/versions/{v1}/integrity")).json(),
        "VersionIntegrity",
    )
    diff = (
        await client.get(
            f"/api/v1/prompts/{prompt_id}/diff", params={"version_a_id": v1, "version_b_id": v2}
        )
    ).json()
    check(diff, "PromptDiff")
    check(diff["template_diff"], "TokenDiff")
    check(diff["template_diff"]["segments"][0], "DiffSegment")
    check(diff["template_diff"]["stats"], "DiffStats")


async def test_error_envelope_matches_what_the_client_reads(client):
    """api-client.ts reads body.error.message for app errors."""
    r = await client.post("/api/v1/datasets", json={"name": "x"})
    r = await client.post("/api/v1/datasets", json={"name": "x"})
    assert r.status_code == 400 and r.json()["error"]["message"]
    assert "error?.message" in CLIENT


async def test_api_key_protects_the_api_when_configured(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "API_KEY", "s3cret")
    assert (await client.get("/api/v1/prompts")).status_code == 401
    assert (await client.get("/api/v1/prompts", headers={"X-API-Key": "wrong"})).status_code == 401
    assert (await client.get("/api/v1/prompts", headers={"X-API-Key": "s3cret"})).status_code == 200
    assert (await client.get("/health")).status_code == 200


async def test_openapi_documents_the_expected_enums(client):
    schema = app.openapi()
    assert "/api/v1/evaluations/runs/{id}/cases" in schema["paths"]
    status_ts = re.search(r"export type RunStatus = (.+?);", TYPES).group(1)
    for status in ("PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"):
        assert f"'{status}'" in status_ts
