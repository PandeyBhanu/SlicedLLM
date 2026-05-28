import asyncio
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_evaluation_datasets_and_runs(client: AsyncClient) -> None:
    """Test full evaluation pipeline from dataset construction to concurrent comparative runs."""
    
    # 1. Create Prompt and Active Version
    prompt_res = await client.post(
        "/api/v1/prompts/",
        json={"name": "Sentiment Analyser", "description": "Detects user feedback mood"},
    )
    prompt_id = prompt_res.json()["id"]
    
    v1_res = await client.post(
        f"/api/v1/prompts/{prompt_id}/versions",
        json={
            "template": "Analyze the sentiment of this: {{input}}",
            "semantic_version": "1.0.0",
            "metadata_json": {},
            "provider_config": {},
        },
    )
    v1_id = v1_res.json()["id"]

    # 2. Create Evaluation Dataset
    dataset_res = await client.post(
        "/api/v1/datasets/",
        json={"name": "Sentiment Test Suite", "description": "Validation set for mood classifier"},
    )
    assert dataset_res.status_code == 201
    dataset = dataset_res.json()
    dataset_id = dataset["id"]

    # 3. Add Test Case
    case_payload = {
        "input_text": "I absolutely love SlicedLLM, it is incredibly fast and clean!",
        "expected_behavior": {"keywords": ["positive", "assistant"]},
    }
    case_res = await client.post(f"/api/v1/datasets/{dataset_id}/cases", json=case_payload)
    assert case_res.status_code == 201
    case_data = case_res.json()
    assert case_data["input_text"] == case_payload["input_text"]

    # 4. Trigger Async Evaluation Run
    run_payload = {
        "dataset_id": dataset_id,
        "prompt_version_a_id": v1_id,
        "prompt_version_b_id": None,  # Standalone evaluation
        "provider": "openai",
        "model": "gpt-4o",
    }
    run_res = await client.post("/api/v1/evaluations/runs", json=run_payload)
    assert run_res.status_code == 202
    run_data = run_res.json()
    run_id = run_data["id"]
    assert run_data["status"] == "RUNNING"

    # 5. Poll for completion (background task processing)
    # Since our mock delay is extremely fast, 1-2 seconds is more than enough.
    completed = False
    for _ in range(10):
        await asyncio.sleep(0.2)
        get_run = await client.get(f"/api/v1/evaluations/runs/{run_id}")
        assert get_run.status_code == 200
        run_status_data = get_run.json()
        if run_status_data["status"] == "COMPLETED":
            completed = True
            break
        elif run_status_data["status"] == "FAILED":
            pytest.fail("Evaluation run transitioned directly to FAILED state.")

    assert completed is True
    
    # 6. Verify Results are populated
    results = run_status_data["results"]
    assert len(results) == 1
    result = results[0]
    assert result["evaluation_case_id"] == case_data["id"]
    assert "version_a" in result["token_usage"]
    assert result["estimated_cost"] > 0
    assert result["latency_ms"] > 0
