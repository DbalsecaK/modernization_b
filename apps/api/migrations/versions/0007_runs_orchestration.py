"""Runs of the project pipeline (spec 10, 11.1, 18.4, 18.8; plan M3 section 3).

Tenant data with forced RLS: run, phase_run, agent_invocation, gate, question and activity_event (append-only).
Infrastructure without tenant_id (ADR-0009): the Procrastinate queue and the LangGraph checkpointer, which hold only
references. New permission `question.answer` (project), granted to the base roles that answer questions.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-29
"""

from alembic import op
from langgraph.checkpoint.postgres import PostgresSaver
from procrastinate import schema as procrastinate_schema

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TENANT_TABLES = ("run", "phase_run", "agent_invocation", "gate", "question", "activity_event")
ANSWERING_ROLES = ("projectOwner", "architect", "analyst", "businessReviewer")
RUN_STATUS = "('queued', 'running', 'waiting', 'succeeded', 'failed', 'cancelled')"
GATES = "('C1', 'C2', 'C3', 'C4')"


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE run (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      config_version integer NOT NULL,
      kind text NOT NULL CHECK (kind IN ('pipeline', 'demo')),
      status text NOT NULL DEFAULT 'queued' CHECK (status IN {RUN_STATUS}),
      -- Why a run waits: a gate, a question, an escalation or a phase not available in this version.
      waiting_reason text CHECK (waiting_reason IN ('gate', 'question', 'escalation', 'phaseUnavailable')),
      current_phase text,
      autonomy text NOT NULL CHECK (autonomy IN ('guided', 'balanced', 'autonomous')),
      max_iterations integer NOT NULL CHECK (max_iterations BETWEEN 1 AND 10),
      error text,
      started_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      started_at timestamptz,
      finished_at timestamptz,
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (id, tenant_id),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE,
      FOREIGN KEY (project_id, config_version, tenant_id)
        REFERENCES project_config (project_id, version, tenant_id)
    );
    CREATE INDEX run_project_idx ON run (project_id, created_at DESC);
    CREATE TRIGGER run_updated_at BEFORE UPDATE ON run FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    CREATE TABLE phase_run (
      tenant_id uuid NOT NULL,
      run_id uuid NOT NULL,
      phase text NOT NULL,
      position integer NOT NULL,
      status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'waiting', 'succeeded', 'failed', 'skipped', 'unavailable')),
      iterations integer NOT NULL DEFAULT 0,
      detail text,
      started_at timestamptz,
      finished_at timestamptz,
      PRIMARY KEY (run_id, phase),
      FOREIGN KEY (run_id, tenant_id) REFERENCES run (id, tenant_id) ON DELETE CASCADE
    );

    CREATE TABLE agent_invocation (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      run_id uuid NOT NULL,
      phase text NOT NULL,
      agent_key text NOT NULL,
      shard text,
      iteration integer NOT NULL DEFAULT 1,
      status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed', 'escalated')),
      model text,
      input_tokens integer NOT NULL DEFAULT 0,
      output_tokens integer NOT NULL DEFAULT 0,
      cost_usd numeric(18, 8) NOT NULL DEFAULT 0,
      summary text,
      -- Already redacted by the worker (no credentials or tokens, spec 18.8).
      error jsonb,
      started_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz,
      UNIQUE (id, tenant_id),
      FOREIGN KEY (run_id, tenant_id) REFERENCES run (id, tenant_id) ON DELETE CASCADE
    );
    CREATE INDEX agent_invocation_run_idx ON agent_invocation (run_id, started_at);

    CREATE TABLE gate (
      tenant_id uuid NOT NULL,
      run_id uuid NOT NULL,
      gate text NOT NULL CHECK (gate IN {GATES}),
      -- Required gates stop the run; the others are reviewed asynchronously (the template decides, 18.3).
      required boolean NOT NULL,
      status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
      requested_at timestamptz NOT NULL DEFAULT now(),
      decided_by uuid REFERENCES app_user (id),
      decided_at timestamptz,
      comment text CHECK (length(comment) <= 2000),
      PRIMARY KEY (run_id, gate),
      FOREIGN KEY (run_id, tenant_id) REFERENCES run (id, tenant_id) ON DELETE CASCADE
    );

    -- Decision cards (10.4): the agent's question with its evidence and a recommended answer.
    CREATE TABLE question (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      run_id uuid NOT NULL,
      phase text NOT NULL,
      agent_key text NOT NULL,
      question_text text NOT NULL CHECK (length(question_text) BETWEEN 1 AND 2000),
      context text NOT NULL DEFAULT '',
      evidence jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(evidence) = 'array'),
      reason text NOT NULL CHECK (reason IN ('lowConfidence', 'contradiction', 'judgesDisagree',
        'missingInformation', 'retriesExhausted')),
      impact text NOT NULL CHECK (impact IN ('high', 'low')),
      recommended jsonb NOT NULL CHECK (jsonb_typeof(recommended) = 'object'),
      alternatives jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(alternatives) = 'array'),
      affects jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(affects) = 'array'),
      status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'cancelled')),
      answer text CHECK (length(answer) <= 2000),
      was_recommended boolean,
      answered_by uuid REFERENCES app_user (id),
      answered_at timestamptz,
      comment text CHECK (length(comment) <= 2000),
      created_at timestamptz NOT NULL DEFAULT now(),
      CHECK ((status = 'answered') = (answer IS NOT NULL)),
      FOREIGN KEY (run_id, tenant_id) REFERENCES run (id, tenant_id) ON DELETE CASCADE,
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE
    );
    CREATE INDEX question_open_idx ON question (project_id) WHERE status = 'open';

    -- Events of the activity panel (18.8), in order; the payload is redacted before it is written.
    CREATE TABLE activity_event (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      run_id uuid NOT NULL,
      invocation_id uuid,
      agent_key text,
      phase text,
      kind text NOT NULL CHECK (kind IN ('runStarted', 'phaseStarted', 'started', 'completed', 'failed',
        'verificationFailed', 'selfCorrected', 'escalated', 'gateWaiting', 'gateDecided', 'questionAsked',
        'questionAnswered', 'fanOut', 'phaseCompleted', 'runFinished', 'info')),
      status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'waiting')),
      message text NOT NULL CHECK (length(message) <= 2000),
      model text,
      tokens integer NOT NULL DEFAULT 0,
      cost_usd numeric(18, 8) NOT NULL DEFAULT 0,
      payload jsonb NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
      occurred_at timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (run_id, tenant_id) REFERENCES run (id, tenant_id) ON DELETE CASCADE
    );
    CREATE INDEX activity_event_project_idx ON activity_event (project_id, id);
    """)

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_owner ON {table} TO platform_owner USING (true) WITH CHECK (true)")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} TO platform_app "
            "USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())"
        )

    # Queue (ADR-0009): the Procrastinate schema of the pinned version.
    op.execute(procrastinate_schema.SchemaManager.get_schema())
    # LangGraph checkpointer: its migrations, recorded so PostgresSaver.setup() finds nothing left to do. The tables
    # are empty here, so the concurrent index builds (not allowed in a transaction) run as plain ones.
    for version, statement in enumerate(PostgresSaver.MIGRATIONS):
        op.execute(statement.replace("CONCURRENTLY ", ""))
        op.execute(f"INSERT INTO checkpoint_migrations (v) VALUES ({int(version)}) ON CONFLICT DO NOTHING")  # noqa: S608

    op.execute("""
    GRANT SELECT, INSERT, UPDATE ON run, phase_run, agent_invocation, gate, question TO platform_app;
    GRANT SELECT, INSERT ON activity_event TO platform_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON procrastinate_jobs, procrastinate_workers, procrastinate_periodic_defers,
      procrastinate_events, checkpoints, checkpoint_blobs, checkpoint_writes TO platform_app;
    GRANT SELECT ON checkpoint_migrations TO platform_app;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO platform_app;
    GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO platform_app;
    """)

    # Answering questions (10.4): a new project permission, granted to the base roles that answer them.
    op.execute("""
    INSERT INTO permission (key, description) VALUES ('question.answer', 'Answer the questions of the agents');
    INSERT INTO permission_scope (permission_key, scope) VALUES ('question.answer', 'project');
    """)
    roles = ", ".join(f"'{r}'" for r in ANSWERING_ROLES)
    op.execute(f"""  -- constant role keys of this module
    INSERT INTO role_permission (tenant_id, role_id, role_scope, permission_key)
    SELECT tenant_id, id, scope, 'question.answer' FROM role WHERE key IN ({roles}) AND scope = 'project'
    ON CONFLICT DO NOTHING;
    """)  # noqa: S608


def downgrade() -> None:
    op.execute("""
    DELETE FROM role_permission WHERE permission_key = 'question.answer';
    DELETE FROM permission_scope WHERE permission_key = 'question.answer';
    DELETE FROM permission WHERE key = 'question.answer';
    DROP TABLE IF EXISTS checkpoint_writes, checkpoint_blobs, checkpoints, checkpoint_migrations;
    DROP TABLE IF EXISTS procrastinate_events, procrastinate_periodic_defers, procrastinate_jobs, procrastinate_workers
      CASCADE;
    DROP TYPE IF EXISTS procrastinate_job_to_defer_v1, procrastinate_job_event_type, procrastinate_job_status CASCADE;
    DROP TABLE activity_event, question, gate, agent_invocation, phase_run, run;
    """)
    op.execute("""
    DO $$ DECLARE f record; BEGIN
      FOR f IN SELECT oid::regprocedure AS sig FROM pg_proc WHERE proname LIKE 'procrastinate\\_%' LOOP
        EXECUTE 'DROP FUNCTION IF EXISTS ' || f.sig || ' CASCADE';
      END LOOP;
    END $$;
    """)
