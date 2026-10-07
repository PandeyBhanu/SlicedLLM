from dataclasses import dataclass


@dataclass(frozen=True)
class AuditContext:
    """Who is acting and under which request. Passed explicitly into services."""

    actor_id: str = "anonymous"
    request_id: str | None = None


SYSTEM_CONTEXT = AuditContext(actor_id="system")
