import asyncio
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.audit import AuditService, verify_audit_chain
from app.core.context import AuditContext
from app.core.exceptions import AppendOnlyError
from app.models.audit import GENESIS_HASH, AuditLog
from tests.helpers import create_prompt_with_versions

API = "/api/v1/prompts"


async def seed_events(client, n_versions=3):
    prompt_id, ids = await create_prompt_with_versions(
        client, templates=[(f"1.0.{i}", f"template {i} {{{{input}}}}") for i in range(n_versions)]
    )
    await client.post(f"{API}/{prompt_id}/versions/{ids[1]}/activate")
    await client.post(f"{API}/{prompt_id}/rollback", json={"target_version_id": ids[0]})
    return prompt_id, ids


async def test_mutations_create_audit_events_with_actor_and_request_id(client, db):
    headers = {"X-Actor-Id": "alice", "X-Request-ID": "req-123"}
    r = await client.post(API, json={"name": "audited"}, headers=headers)
    prompt_id = r.json()["id"]
    v = await client.post(
        f"{API}/{prompt_id}/versions",
        json={"semantic_version": "1.0.0", "template": "x"},
        headers=headers,
    )
    version_id = v.json()["id"]
    events = (await client.get(f"{API}/{prompt_id}/audit")).json()
    assert [e["action"] for e in reversed(events)] == ["CREATE", "CREATE"]
    assert {e["entity_type"] for e in events} == {"Prompt", "PromptVersion"}
    for e in events:
        assert e["actor_id"] == "alice" and e["request_id"] == "req-123"
        assert len(e["event_hash"]) == 64 and e["occurred_at"]
    version_event = next(e for e in events if e["entity_type"] == "PromptVersion")
    assert version_event["entity_id"] == version_id
    assert version_event["content_hash"] == v.json()["content_hash"]
    assert version_event["after_state"]["template"] == "x" and version_event["before_state"] is None


async def test_activation_and_rollback_are_audited_with_before_and_after(client):
    prompt_id, ids = await seed_events(client)
    events = list(reversed((await client.get(f"{API}/{prompt_id}/audit")).json()))
    actions = [e["action"] for e in events]
    assert actions == ["CREATE", "CREATE", "CREATE", "CREATE", "ACTIVATE", "ROLLBACK"]
    activate, rollback = events[-2], events[-1]
    assert (
        activate["before_state"]["version_id"] == ids[0]
        and activate["after_state"]["version_id"] == ids[1]
    )
    assert (
        rollback["before_state"]["version_id"] == ids[1]
        and rollback["after_state"]["version_id"] == ids[0]
    )
    assert rollback["actor_id"] == "anonymous"


async def test_chain_is_valid_and_linked(client, db):
    await seed_events(client)
    result = await verify_audit_chain(db)
    assert result.valid and result.events_checked == 6 and result.errors == []
    rows = (await db.execute(select(AuditLog).order_by(AuditLog.seq))).scalars().all()
    assert [r.seq for r in rows] == list(range(1, 7))
    assert rows[0].prev_hash == GENESIS_HASH
    assert all(rows[i].prev_hash == rows[i - 1].event_hash for i in range(1, 6))
    api = (await client.get("/api/v1/audit/verify")).json()
    assert api["valid"] is True and api["head_seq"] == 6


async def test_empty_chain_is_valid(db):
    result = await verify_audit_chain(db)
    assert result.valid and result.events_checked == 0 and result.head_seq is None


@pytest.mark.parametrize(
    "sql",
    ["UPDATE audit_logs SET action = 'HACKED'", "DELETE FROM audit_logs", "TRUNCATE audit_logs"],
)
async def test_database_rejects_update_delete_truncate(client, db, sql):
    await seed_events(client)
    with pytest.raises((IntegrityError, DBAPIError)) as exc:
        await db.execute(text(sql))
        await db.commit()
    assert "append-only" in str(exc.value)


async def test_orm_blocks_audit_updates_and_deletes(client, db):
    await seed_events(client)
    row = (await db.execute(select(AuditLog).limit(1))).scalars().first()
    row.action = "HACKED"
    with pytest.raises(AppendOnlyError):
        await db.flush()
    await db.rollback()
    row = (await db.execute(select(AuditLog).limit(1))).scalars().first()
    await db.delete(row)
    with pytest.raises(AppendOnlyError):
        await db.flush()
    await db.rollback()


async def tamper(db, sql, **params):
    """Simulate a privileged attacker (superuser) who disables the trigger first."""
    await db.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER USER"))
    await db.execute(text(sql), params)
    await db.commit()


async def test_verification_detects_modified_event(client, db):
    await seed_events(client)
    await tamper(db, 'UPDATE audit_logs SET after_state = \'{"template": "forged"}\' WHERE seq = 3')
    result = await verify_audit_chain(db)
    assert not result.valid
    assert [(e["seq"], e["kind"]) for e in result.errors] == [(3, "modified_event")]


async def test_verification_detects_modified_actor(client, db):
    await seed_events(client)
    await tamper(db, "UPDATE audit_logs SET actor_id = 'mallory' WHERE seq = 5")
    result = await verify_audit_chain(db)
    assert any(e["seq"] == 5 and e["kind"] == "modified_event" for e in result.errors)


async def test_verification_detects_broken_hash_even_if_contents_untouched(client, db):
    await seed_events(client)
    await tamper(db, "UPDATE audit_logs SET event_hash = repeat('a', 64) WHERE seq = 2")
    kinds = {(e["seq"], e["kind"]) for e in (await verify_audit_chain(db)).errors}
    assert (2, "modified_event") in kinds  # stored hash no longer matches contents
    assert (3, "broken_chain") in kinds  # next event's prev_hash no longer matches


async def test_verification_detects_deleted_event_in_the_middle(client, db):
    await seed_events(client)
    await tamper(db, "DELETE FROM audit_logs WHERE seq = 4")
    kinds = {(e["seq"], e["kind"]) for e in (await verify_audit_chain(db)).errors}
    assert (5, "missing_events") in kinds and (5, "broken_chain") in kinds


async def test_verification_detects_deleted_first_event(client, db):
    await seed_events(client)
    await tamper(db, "DELETE FROM audit_logs WHERE seq = 1")
    kinds = {e["kind"] for e in (await verify_audit_chain(db)).errors}
    assert "missing_events" in kinds and "broken_chain" in kinds


async def test_tail_truncation_needs_an_external_checkpoint(client, db):
    await seed_events(client)
    checkpoint = await AuditService(db).head()
    await tamper(db, "DELETE FROM audit_logs WHERE seq = 6")
    assert (
        await verify_audit_chain(db)
    ).valid  # documented limitation: a shorter chain is still consistent
    result = await verify_audit_chain(db, expected_head=checkpoint)
    assert not result.valid and result.errors[-1]["kind"] == "head_mismatch"


async def test_verification_detects_reordered_events(client, db):
    await seed_events(client)
    await tamper(
        db,
        "UPDATE audit_logs SET occurred_at = "
        "(SELECT occurred_at FROM audit_logs WHERE seq = 2) - interval '1 day' WHERE seq = 4",
    )
    kinds = {(e["seq"], e["kind"]) for e in (await verify_audit_chain(db)).errors}
    assert (4, "out_of_order") in kinds


async def test_swapped_sequence_numbers_are_detected(client, db):
    await seed_events(client)
    await db.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER USER"))
    await db.execute(text("UPDATE audit_logs SET seq = seq + 1000 WHERE seq IN (2, 3)"))
    await db.execute(
        text(
            "UPDATE audit_logs SET seq = CASE seq WHEN 1002 THEN 3 ELSE 2 END "
            "WHERE seq IN (1002, 1003)"
        )
    )
    await db.commit()
    result = await verify_audit_chain(db)
    assert not result.valid and {e["kind"] for e in result.errors} & {
        "broken_chain",
        "modified_event",
    }


async def test_concurrent_appends_produce_a_gap_free_valid_chain(client, db):
    results = await asyncio.gather(*(client.post(API, json={"name": f"p{i}"}) for i in range(12)))
    assert all(r.status_code == 201 for r in results)
    result = await verify_audit_chain(db)
    assert result.valid and result.events_checked == 12 and result.head_seq == 12


async def test_audit_event_is_rolled_back_with_its_transaction(session_factory):
    async with session_factory() as s:
        await AuditService(s).append(
            entity_type="X", entity_id=uuid.uuid4(), action="CREATE", ctx=AuditContext("bob")
        )
        await s.rollback()
    async with session_factory() as s:
        assert await AuditService(s).count() == 0
