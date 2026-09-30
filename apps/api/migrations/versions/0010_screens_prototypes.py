"""Screens, design system and prototypes (spec 4.1 "Pantalla", 7.4, D-24; plan M5).

Screen specs are spec elements (`element_type = 'screen'`), versioned like rules. The design system and each screen's
prototype are versioned rows whose code and bundle live in the object store (references only, 10.2). People comment
on a prototype and ask for changes through the chat; every request and every answer of the agent stays as evidence.
New project permissions `prototype.comment` and `prototype.edit`.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-30
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

TENANT_TABLES = ("design_system", "prototype", "prototype_comment", "ui_chat_message")
PERMISSIONS = {
    "prototype.comment": (
        "Comment on the prototypes of a project",
        ("projectOwner", "architect", "analyst", "businessReviewer", "developer", "observer"),
    ),
    "prototype.edit": (
        "Edit screen specs and ask for prototype changes",
        ("projectOwner", "architect", "analyst", "businessReviewer"),
    ),
}


def upgrade() -> None:
    op.execute("""
    ALTER TABLE spec_element DROP CONSTRAINT spec_element_element_type_check;
    ALTER TABLE spec_element ADD CONSTRAINT spec_element_element_type_check
      CHECK (element_type IN ('rule', 'capability', 'contract', 'test_case', 'screen'));

    -- The design system of a project (7.4): tokens and the components the prototypes may use. One row per version.
    CREATE TABLE design_system (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      version integer NOT NULL CHECK (version >= 1),
      source text NOT NULL CHECK (source IN ('nexti-base', 'client-brand')),
      tokens jsonb NOT NULL CHECK (jsonb_typeof(tokens) = 'object'),
      status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved')),
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (project_id, version),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE
    );

    -- One version of the prototype of a screen: its TSX and its compiled bundle, in the object store.
    CREATE TABLE prototype (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      screen_key text NOT NULL CHECK (screen_key ~ '^SCR-[A-Z0-9][A-Z0-9_-]{0,39}$'),
      version integer NOT NULL CHECK (version >= 1),
      origin text NOT NULL CHECK (origin IN ('generated', 'chat')),
      status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved')),
      source_key text NOT NULL,
      bundle_key text NOT NULL,
      bundle_sha256 text NOT NULL CHECK (bundle_sha256 ~ '^[0-9a-f]{64}$'),
      notes text NOT NULL DEFAULT '' CHECK (length(notes) <= 2000),
      run_id uuid,
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (project_id, screen_key, version),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE
    );

    -- A comment on a prototype version, anchored to a field or a point of the screen.
    CREATE TABLE prototype_comment (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      prototype_id uuid NOT NULL REFERENCES prototype (id) ON DELETE CASCADE,
      body text NOT NULL CHECK (length(body) BETWEEN 1 AND 2000),
      anchor jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(anchor) = 'object'),
      resolved boolean NOT NULL DEFAULT false,
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE
    );

    -- The change chat of a screen (D-24): what a person asked and what the UX/UI designer answered or produced.
    CREATE TABLE ui_chat_message (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL,
      project_id uuid NOT NULL,
      screen_key text NOT NULL CHECK (screen_key ~ '^SCR-[A-Z0-9][A-Z0-9_-]{0,39}$'),
      role text NOT NULL CHECK (role IN ('user', 'agent')),
      body text NOT NULL CHECK (length(body) BETWEEN 1 AND 4000),
      status text NOT NULL DEFAULT 'done' CHECK (status IN ('pending', 'done', 'failed')),
      prototype_version integer,
      question_id uuid,
      created_by uuid REFERENCES app_user (id),
      created_at timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (project_id, tenant_id) REFERENCES project (id, tenant_id) ON DELETE CASCADE
    );
    CREATE INDEX ui_chat_message_screen ON ui_chat_message (project_id, screen_key, created_at);
    """)

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_owner ON {table} TO platform_owner USING (true) WITH CHECK (true)")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} TO platform_app "
            "USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())"
        )

    # Versions are append-only; a comment can be resolved and a chat request marked done or failed.
    op.execute("""
    GRANT SELECT, INSERT ON design_system, prototype TO platform_app;
    GRANT SELECT, INSERT, UPDATE ON prototype_comment, ui_chat_message TO platform_app;
    """)

    for key, (description, roles) in PERMISSIONS.items():
        op.execute(f"INSERT INTO permission (key, description) VALUES ('{key}', '{description}')")  # noqa: S608
        op.execute(f"INSERT INTO permission_scope (permission_key, scope) VALUES ('{key}', 'project')")  # noqa: S608
        role_list = ", ".join(f"'{r}'" for r in roles)
        op.execute(f"""  -- constant keys of this module
        INSERT INTO role_permission (tenant_id, role_id, role_scope, permission_key)
        SELECT tenant_id, id, scope, '{key}' FROM role WHERE key IN ({role_list}) AND scope = 'project'
        ON CONFLICT DO NOTHING
        """)  # noqa: S608


def downgrade() -> None:
    keys = ", ".join(f"'{k}'" for k in PERMISSIONS)
    op.execute(f"""
    DELETE FROM role_permission WHERE permission_key IN ({keys});
    DELETE FROM permission_scope WHERE permission_key IN ({keys});
    DELETE FROM permission WHERE key IN ({keys});
    """)  # noqa: S608
    op.execute("DROP TABLE ui_chat_message, prototype_comment, prototype, design_system")
    op.execute("""
    DELETE FROM spec_element WHERE element_type = 'screen';
    ALTER TABLE spec_element DROP CONSTRAINT spec_element_element_type_check;
    ALTER TABLE spec_element ADD CONSTRAINT spec_element_element_type_check
      CHECK (element_type IN ('rule', 'capability', 'contract', 'test_case'));
    """)
