from nexti_core.authz_catalog import BASE_ROLES, PERMISSIONS, TENANT_ADMIN_ROLE, permission_scopes


def test_keys_are_unique() -> None:
    assert len({p.key for p in PERMISSIONS}) == len(PERMISSIONS)
    assert len({r.key for r in BASE_ROLES}) == len(BASE_ROLES)


def test_every_role_permission_exists_and_fits_the_role_scope() -> None:
    scopes = permission_scopes()
    for role in BASE_ROLES:
        for key in role.permissions:
            assert key in scopes, f"{role.key}: unknown permission {key}"
            assert role.scope in scopes[key], f"{role.key} ({role.scope}) cannot hold {key}"


def test_every_permission_of_spec_16_2_is_in_the_catalog() -> None:
    spec = {
        "project.create", "project.configure", "input.upload", "pipeline.run", "gate.c1.approve",
        "gate.c2.approve", "gate.c3.approve", "signoff.sign", "code.view", "code.download", "code.push",
        "models.configure", "usage.view", "cost.view", "agents.select", "skills.select", "skills.publish",
        "users.manage", "audit.view",
        "question.answer",  # added with the questions of the agents (M3, 16.2 "pregunta.responder")
    }  # fmt: skip
    assert {p.key for p in PERMISSIONS} == spec


def test_tenant_admin_bundle_has_no_project_only_permission() -> None:
    admin = next(r for r in BASE_ROLES if r.key == TENANT_ADMIN_ROLE)
    assert "signoff.sign" not in admin.permissions
