import asyncio
import uuid

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.exceptions import ImmutableEntityError
from app.models.prompt import PromptVersion
from app.promptops.hashing import compute_content_hash
from app.repositories.prompt import PromptVersionRepository
from tests.helpers import create_prompt_with_versions

API = "/api/v1/prompts"


async def test_versions_coexist_and_first_is_active(client):
    prompt_id, (v1, v2) = await create_prompt_with_versions(client)
    versions = (await client.get(f"{API}/{prompt_id}/versions")).json()
    assert [v["semantic_version"] for v in versions] == ["1.0.0", "1.1.0"]
    assert [v["is_active"] for v in versions] == [True, False]
    assert all(len(v["content_hash"]) == 64 for v in versions)
    detail = (await client.get(f"{API}/{prompt_id}")).json()
    assert len(detail["versions"]) == 2


async def test_duplicate_semantic_version_rejected(client):
    prompt_id, _ = await create_prompt_with_versions(client)
    r = await client.post(
        f"{API}/{prompt_id}/versions", json={"semantic_version": "1.0.0", "template": "other"}
    )
    assert r.status_code == 400


async def test_set_as_active_moves_the_active_flag(client):
    prompt_id, (v1, _) = await create_prompt_with_versions(client)
    r = await client.post(
        f"{API}/{prompt_id}/versions",
        json={"semantic_version": "2.0.0", "template": "v2 {{input}}", "set_as_active": True},
    )
    v3 = r.json()["id"]
    versions = (await client.get(f"{API}/{prompt_id}/versions")).json()
    assert [v["id"] for v in versions if v["is_active"]] == [v3]


async def test_database_allows_only_one_active_version(db, client):
    prompt_id, (v1, v2) = await create_prompt_with_versions(client)
    with pytest.raises(IntegrityError):
        await db.execute(
            update(PromptVersion).where(PromptVersion.id == uuid.UUID(v2)).values(is_active=True)
        )
        await db.commit()


async def test_repository_refuses_update_and_delete(db, client):
    _, (v1, _) = await create_prompt_with_versions(client)
    repo = PromptVersionRepository(db)
    version = await repo.get(uuid.UUID(v1))
    with pytest.raises(ImmutableEntityError):
        await repo.update(db_obj=version, obj_in={"template": "hacked"})
    with pytest.raises(ImmutableEntityError):
        await repo.remove(id=version.id)


async def test_orm_guard_blocks_content_edits(db, client):
    _, (v1, _) = await create_prompt_with_versions(client)
    version = await db.get(PromptVersion, uuid.UUID(v1))
    version.template = "edited through the ORM"
    with pytest.raises(ImmutableEntityError):
        await db.flush()
    await db.rollback()


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE prompt_versions SET template = 'hacked'",
        "UPDATE prompt_versions SET semantic_version = '9.9.9'",
        "UPDATE prompt_versions SET metadata_json = '{\"x\": 1}'",
        "UPDATE prompt_versions SET provider_config = '{\"temperature\": 2}'",
        "UPDATE prompt_versions SET content_hash = repeat('0', 64)",
        "DELETE FROM prompt_versions",
    ],
)
async def test_database_trigger_blocks_raw_sql_tampering(db, client, sql):
    await create_prompt_with_versions(client)
    with pytest.raises((IntegrityError, DBAPIError)) as exc:
        await db.execute(text(sql))
        await db.commit()
    assert "immutable" in str(exc.value)


async def test_database_trigger_allows_activation_changes(db, client):
    _, (v1, v2) = await create_prompt_with_versions(client)
    await db.execute(text("UPDATE prompt_versions SET is_active = false"))
    await db.commit()
    assert (await db.get(PromptVersion, uuid.UUID(v1))).is_active is False


async def test_content_hash_is_deterministic_and_verifiable(client, db):
    prompt_id, (v1, _) = await create_prompt_with_versions(client)
    version = await db.get(PromptVersion, uuid.UUID(v1))
    assert version.content_hash == compute_content_hash(
        prompt_id=prompt_id,
        semantic_version="1.0.0",
        template="Answer well: {{input}}",
        metadata={},
        provider_config={"temperature": 0.2},
    )
    r = await client.get(f"{API}/{prompt_id}/versions/{v1}/integrity")
    assert r.json()["intact"] is True


async def test_content_hash_detects_tampering_done_behind_the_triggers(client, db):
    """A superuser can disable the trigger; the hash still exposes the change."""
    prompt_id, (v1, v2) = await create_prompt_with_versions(client)
    await db.execute(
        text("ALTER TABLE prompt_versions DISABLE TRIGGER trg_prompt_versions_immutable")
    )
    await db.execute(
        text("UPDATE prompt_versions SET template = 'silently changed' WHERE id = :i"),
        {"i": uuid.UUID(v1)},
    )
    await db.commit()
    tampered = (await client.get(f"{API}/{prompt_id}/versions/{v1}/integrity")).json()
    untouched = (await client.get(f"{API}/{prompt_id}/versions/{v2}/integrity")).json()
    assert tampered["intact"] is False and tampered["stored_hash"] != tampered["computed_hash"]
    assert untouched["intact"] is True


async def test_rollback_changes_state_but_not_history(client, db):
    prompt_id, (v1, v2) = await create_prompt_with_versions(client)
    await client.post(f"{API}/{prompt_id}/versions/{v2}/activate")

    def snapshot(rows):
        return {
            v["id"]: {
                k: v[k]
                for k in (
                    "template",
                    "semantic_version",
                    "metadata_json",
                    "provider_config",
                    "content_hash",
                    "created_at",
                )
            }
            for v in rows
        }

    before = snapshot((await client.get(f"{API}/{prompt_id}/versions")).json())
    r = await client.post(f"{API}/{prompt_id}/rollback", json={"target_version_id": v1})
    assert r.status_code == 200 and r.json()["id"] == v1 and r.json()["is_active"] is True
    after_rows = (await client.get(f"{API}/{prompt_id}/versions")).json()
    assert snapshot(after_rows) == before
    assert {v["id"]: v["is_active"] for v in after_rows} == {v1: True, v2: False}


async def test_rollback_and_activate_validation(client):
    prompt_id, (v1, v2) = await create_prompt_with_versions(client)
    assert (
        await client.post(f"{API}/{prompt_id}/rollback", json={"target_version_id": v1})
    ).status_code == 400
    assert (
        await client.post(f"{API}/{prompt_id}/versions/{uuid.uuid4()}/activate")
    ).status_code == 404
    other_prompt, (o1, _) = await create_prompt_with_versions(client, name="other")
    assert (await client.post(f"{API}/{prompt_id}/versions/{o1}/activate")).status_code == 404


async def test_concurrent_creation_of_the_same_version_yields_exactly_one(client):
    r = await client.post(API, json={"name": "race"})
    prompt_id = r.json()["id"]
    body = {"semantic_version": "1.0.0", "template": "t {{input}}"}
    results = await asyncio.gather(
        *(client.post(f"{API}/{prompt_id}/versions", json=body) for _ in range(6))
    )
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1
    assert all(c in (400, 409) for c in codes if c != 201)
    assert len((await client.get(f"{API}/{prompt_id}/versions")).json()) == 1


async def test_concurrent_creation_of_different_versions_keeps_single_active(client):
    r = await client.post(API, json={"name": "race2"})
    prompt_id = r.json()["id"]
    results = await asyncio.gather(
        *(
            client.post(
                f"{API}/{prompt_id}/versions",
                json={
                    "semantic_version": f"1.0.{i}",
                    "template": f"t{i}",
                    "set_as_active": i % 2 == 0,
                },
            )
            for i in range(8)
        )
    )
    assert all(r.status_code == 201 for r in results)
    versions = (await client.get(f"{API}/{prompt_id}/versions")).json()
    assert len(versions) == 8
    assert sum(v["is_active"] for v in versions) == 1


async def test_prompt_update_only_touches_description_and_tags(client):
    prompt_id, _ = await create_prompt_with_versions(client)
    r = await client.patch(f"{API}/{prompt_id}", json={"description": "new", "tags": ["a"]})
    assert r.status_code == 200 and r.json()["description"] == "new" and r.json()["tags"] == ["a"]
    assert (await client.get(f"{API}/{prompt_id}")).json()["name"] == "p1"
