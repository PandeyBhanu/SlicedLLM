import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    """Verify that the baseline health endpoint is alive."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


@pytest.mark.asyncio
async def test_create_prompt_and_versions(client: AsyncClient) -> None:
    """Test full flow: prompt container creation, versions, diffs, and rollback state."""
    
    # 1. Create Prompt
    prompt_payload = {
        "name": "Translate English to Spanish",
        "description": "Standard translation assistant"
    }
    res = await client.post("/api/v1/prompts/", json=prompt_payload)
    assert res.status_code == 201
    prompt = res.json()
    assert prompt["name"] == prompt_payload["name"]
    prompt_id = prompt["id"]

    # 2. Add Prompt Version 1.0.0
    v1_payload = {
        "template": "Translate this text: {{input}}",
        "semantic_version": "1.0.0",
        "metadata_json": {"department": "localization"},
        "provider_config": {"temperature": 0.2, "max_tokens": 100}
    }
    res_v1 = await client.post(f"/api/v1/prompts/{prompt_id}/versions", json=v1_payload)
    assert res_v1.status_code == 201
    v1 = res_v1.json()
    assert v1["semantic_version"] == "1.0.0"
    assert v1["is_active"] is True  # The first published version becomes active by default
    v1_id = v1["id"]

    # 3. Add Prompt Version 1.1.0
    v2_payload = {
        "template": "Translate the following English phrase to high-quality Spanish: {{input}}",
        "semantic_version": "1.1.0",
        "metadata_json": {"department": "localization"},
        "provider_config": {"temperature": 0.1, "max_tokens": 150}
    }
    res_v2 = await client.post(f"/api/v1/prompts/{prompt_id}/versions", json=v2_payload)
    assert res_v2.status_code == 201
    v2 = res_v2.json()
    assert v2["semantic_version"] == "1.1.0"
    assert v2["is_active"] is False  # Subsequent versions are inactive until promoted
    v2_id = v2["id"]

    # 4. Generate Diff
    diff_res = await client.get(
        f"/api/v1/prompts/{prompt_id}/diff?version_a_id={v1_id}&version_b_id={v2_id}"
    )
    assert diff_res.status_code == 200
    diff_data = diff_res.json()
    assert "template_diff" in diff_data
    assert diff_data["config_diff"]["max_tokens"]["before"] == 100
    assert diff_data["config_diff"]["max_tokens"]["after"] == 150

    # 5. Rollback (Switch Active to 1.1.0)
    rollback_res = await client.post(
        f"/api/v1/prompts/{prompt_id}/rollback", json={"target_version_id": v2_id}
    )
    assert rollback_res.status_code == 200
    rollback_data = rollback_res.json()
    assert rollback_data["id"] == v2_id
    assert rollback_data["is_active"] is True

    # 6. Verify version 1.0.0 was deactivated
    get_res = await client.get(f"/api/v1/prompts/{prompt_id}")
    assert get_res.status_code == 200
    versions = get_res.json()["versions"]
    assert len(versions) == 2
    
    # 1.1.0 is active, 1.0.0 is inactive
    v1_rechecked = next(v for v in versions if v["id"] == v1_id)
    v2_rechecked = next(v for v in versions if v["id"] == v2_id)
    assert v1_rechecked["is_active"] is False
    assert v2_rechecked["is_active"] is True
