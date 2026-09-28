"""Audit log: append-only, one hash chain per tenant plus one platform chain (spec 15.6; plan M0 section 8).

The database computes the chain in a trigger, so no code path can skip or break it:
  seq        position in its chain (1, 2, 3, ... with no gaps)
  prev_hash  hash of the previous row of the chain (NULL for the first)
  hash       sha256(canonical JSON of the row, including prev_hash)
Rows can never be updated or deleted: the API has no grant for it and a trigger rejects it for every role.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
    CREATE TABLE audit_log (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      tenant_id uuid REFERENCES tenant (id),
      seq bigint NOT NULL,
      occurred_at timestamptz NOT NULL DEFAULT now(),
      actor_kind text NOT NULL CHECK (actor_kind IN ('user', 'dev-auth', 'system', 'keycloak')),
      actor_id uuid,
      actor_label text,
      action text NOT NULL CHECK (action ~ '^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$'),
      target text,
      outcome text NOT NULL CHECK (outcome IN ('success', 'failure', 'allowed', 'denied')),
      details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
      request_id text,
      prev_hash bytea,
      hash bytea NOT NULL,
      UNIQUE NULLS NOT DISTINCT (tenant_id, seq)
    );
    CREATE INDEX audit_log_tenant_time_idx ON audit_log (tenant_id, occurred_at DESC);

    -- Canonical form of a row: a JSON array has one unambiguous encoding (no delimiter tricks).
    CREATE FUNCTION audit_digest(r audit_log) RETURNS bytea LANGUAGE sql STABLE AS $$
      SELECT sha256(convert_to(jsonb_build_array(
        r.tenant_id, r.seq, to_char(r.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        r.actor_kind, r.actor_id, r.actor_label, r.action, r.target, r.outcome, r.details, r.request_id,
        encode(r.prev_hash, 'hex')
      )::text, 'UTF8'))
    $$;

    -- SECURITY DEFINER: the chain head must be found even when the caller cannot read that chain (e.g. a
    -- platform event written from a tenant session). The lock serializes writers of the same chain.
    CREATE FUNCTION audit_chain() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
      SET search_path = public, pg_temp AS $$
    DECLARE
      last audit_log%ROWTYPE;
    BEGIN
      PERFORM pg_advisory_xact_lock(hashtextextended('audit:' || coalesce(NEW.tenant_id::text, 'platform'), 0));
      SELECT * INTO last FROM audit_log
        WHERE tenant_id IS NOT DISTINCT FROM NEW.tenant_id ORDER BY seq DESC LIMIT 1;
      NEW.seq := coalesce(last.seq, 0) + 1;
      NEW.prev_hash := last.hash;
      NEW.hash := audit_digest(NEW);
      RETURN NEW;
    END $$;
    CREATE TRIGGER audit_log_chain BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION audit_chain();

    CREATE FUNCTION audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'audit_log is append-only (% rejected)', TG_OP USING ERRCODE = 'insufficient_privilege';
    END $$;
    CREATE TRIGGER audit_log_no_update_delete BEFORE UPDATE OR DELETE ON audit_log
      FOR EACH ROW EXECUTE FUNCTION audit_append_only();
    CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log
      FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only();

    -- Walks one chain and reports the first row whose seq, prev_hash or hash does not match.
    -- Only the active tenant's chain, or any chain with platform scope.
    CREATE FUNCTION audit_verify(p_tenant uuid)
      RETURNS TABLE (checked bigint, first_broken_seq bigint, reason text)
      LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DECLARE
      r audit_log%ROWTYPE;
      expected_seq bigint := 1;
      previous bytea := NULL;
    BEGIN
      IF NOT (app_platform_scope() OR (p_tenant IS NOT NULL AND p_tenant = app_current_tenant())) THEN
        RAISE EXCEPTION 'audit_verify: chain not accessible' USING ERRCODE = 'insufficient_privilege';
      END IF;
      checked := 0;
      FOR r IN SELECT * FROM audit_log WHERE tenant_id IS NOT DISTINCT FROM p_tenant ORDER BY seq LOOP
        IF r.seq <> expected_seq THEN
          first_broken_seq := expected_seq; reason := 'missing_row'; RETURN NEXT; RETURN;
        END IF;
        IF r.prev_hash IS DISTINCT FROM previous THEN
          first_broken_seq := r.seq; reason := 'prev_hash_mismatch'; RETURN NEXT; RETURN;
        END IF;
        IF r.hash <> audit_digest(r) THEN
          first_broken_seq := r.seq; reason := 'hash_mismatch'; RETURN NEXT; RETURN;
        END IF;
        previous := r.hash;
        expected_seq := expected_seq + 1;
        checked := checked + 1;
      END LOOP;
      first_broken_seq := NULL; reason := NULL; RETURN NEXT;
    END $$;
    REVOKE ALL ON FUNCTION audit_verify(uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION audit_verify(uuid) TO platform_app;

    ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
    ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;
    CREATE POLICY audit_log_owner ON audit_log TO platform_owner USING (true) WITH CHECK (true);
    -- Read: the active tenant's events; platform events only with platform scope.
    CREATE POLICY audit_log_read_tenant ON audit_log FOR SELECT TO platform_app
      USING (tenant_id = app_current_tenant());
    CREATE POLICY audit_log_read_platform ON audit_log FOR SELECT TO platform_app
      USING (app_platform_scope());
    -- Write: events of the active tenant, or platform events (sign-in, Keycloak events) from any session.
    CREATE POLICY audit_log_write ON audit_log FOR INSERT TO platform_app
      WITH CHECK (tenant_id = app_current_tenant() OR tenant_id IS NULL OR app_platform_scope());

    GRANT SELECT, INSERT ON audit_log TO platform_app;
    """)


def downgrade() -> None:
    # CASCADE also drops audit_digest(audit_log), which depends on the table's row type, and the triggers.
    op.execute("""
    DROP FUNCTION audit_verify(uuid);
    DROP TABLE audit_log CASCADE;
    DROP FUNCTION audit_chain(), audit_append_only();
    """)
