"""PostgreSQL-level guarantees that SQLAlchemy metadata cannot express.

These DDL statements are attached to `Base.metadata` (so `create_all` installs them) and are the
same statements Alembic runs. Each DDL object is a single statement because asyncpg cannot
execute multi-statement strings through prepared statements.
"""

from sqlalchemy import DDL, event

from app.models.base import Base

PROMPT_VERSION_FUNCTION = """
CREATE OR REPLACE FUNCTION prompt_versions_enforce_immutability() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION USING MESSAGE = 'prompt_versions rows are immutable and cannot be deleted',
                          ERRCODE = '23000';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.prompt_id IS DISTINCT FROM OLD.prompt_id
     OR NEW.semantic_version IS DISTINCT FROM OLD.semantic_version
     OR NEW.template IS DISTINCT FROM OLD.template
     OR NEW.metadata_json IS DISTINCT FROM OLD.metadata_json
     OR NEW.provider_config IS DISTINCT FROM OLD.provider_config
     OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION USING MESSAGE = 'prompt_versions content is immutable; only is_active may '
        || 'change',
                          ERRCODE = '23000';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

PROMPT_VERSION_TRIGGER = """
CREATE TRIGGER trg_prompt_versions_immutable
BEFORE UPDATE OR DELETE ON prompt_versions
FOR EACH ROW EXECUTE FUNCTION prompt_versions_enforce_immutability()
"""

AUDIT_FUNCTION = """
CREATE OR REPLACE FUNCTION audit_logs_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION USING MESSAGE = 'audit_logs is append-only: ' || TG_OP || ' is not allowed',
                        ERRCODE = '23000';
END;
$$ LANGUAGE plpgsql
"""

AUDIT_ROW_TRIGGER = """
CREATE TRIGGER trg_audit_logs_no_update_delete
BEFORE UPDATE OR DELETE ON audit_logs
FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only()
"""

AUDIT_TRUNCATE_TRIGGER = """
CREATE TRIGGER trg_audit_logs_no_truncate
BEFORE TRUNCATE ON audit_logs
FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_append_only()
"""

PROMPT_VERSION_STATEMENTS = [PROMPT_VERSION_FUNCTION, PROMPT_VERSION_TRIGGER]
AUDIT_STATEMENTS = [AUDIT_FUNCTION, AUDIT_ROW_TRIGGER, AUDIT_TRUNCATE_TRIGGER]
ALL_TRIGGER_STATEMENTS = PROMPT_VERSION_STATEMENTS + AUDIT_STATEMENTS


def _register(table_name: str, statements: list[str]) -> None:
    table = Base.metadata.tables[table_name]
    for stmt in statements:
        event.listen(table, "after_create", DDL(stmt).execute_if(dialect="postgresql"))


_register("prompt_versions", PROMPT_VERSION_STATEMENTS)
_register("audit_logs", AUDIT_STATEMENTS)
