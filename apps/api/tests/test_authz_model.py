"""The OpenFGA model and the permission catalog must describe the same permissions."""

from nexti_api.authz.fga import load_model
from nexti_api.authz.names import permission_key, relation
from nexti_core.authz_catalog import PERMISSIONS

STRUCTURAL = {"platform", "tenant", "member", "admin", "viewer"}


def relations_of(type_name: str) -> set[str]:
    model = load_model()
    definition = next(t for t in model["type_definitions"] if t["type"] == type_name)
    return set(definition.get("relations", {}))


def test_every_tenant_permission_is_a_tenant_relation_and_nothing_else() -> None:
    expected = {relation(p.key) for p in PERMISSIONS if "tenant" in p.scopes}
    assert relations_of("tenant") - STRUCTURAL == expected


def test_every_project_permission_is_a_project_relation_and_nothing_else() -> None:
    expected = {relation(p.key) for p in PERMISSIONS if "project" in p.scopes}
    assert relations_of("project") - STRUCTURAL == expected


def test_relation_names_round_trip_to_permission_keys() -> None:
    for p in PERMISSIONS:
        assert permission_key(relation(p.key)) == p.key
