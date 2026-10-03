"""The SCIM subset as pure functions (ADR-0031): filters, paging, PATCH operations and the error format."""

import json

import pytest

from nexti_api.scim import protocol
from nexti_api.scim.protocol import ScimError


def test_eq_filters_on_the_allowed_attributes_only() -> None:
    found = protocol.parse_filter('UserName eq "Ana@AndesBank.example"', ("userName", "externalId"))
    assert found == protocol.Filter("userName", "Ana@AndesBank.example")
    assert protocol.parse_filter('externalId eq "a\\"b"', ("userName", "externalId")) == protocol.Filter(
        "externalId", 'a"b'
    )
    assert protocol.parse_filter(None, ("userName",)) is None
    for bad in ('userName co "a"', 'emails eq "a"', 'userName eq "a" or userName eq "b"'):
        with pytest.raises(ScimError) as caught:
            protocol.parse_filter(bad, ("userName", "externalId"))
        assert (caught.value.status, caught.value.scim_type) == (400, "invalidFilter")


def test_paging_is_one_based_and_clamped() -> None:
    assert protocol.paging(None, None) == (0, protocol.DEFAULT_COUNT)
    assert protocol.paging("3", "10") == (2, 10)
    assert protocol.paging("0", "-5") == (0, 0)
    assert protocol.paging("1", "100000") == (0, protocol.MAX_COUNT)
    with pytest.raises(ScimError):
        protocol.paging("x", "1")


def test_a_user_takes_its_primary_email_or_its_user_name() -> None:
    fields = protocol.user_fields({
        "userName": "ana", "name": {"givenName": "Ana", "familyName": "Paz"},
        "emails": [{"value": "other@x.example"}, {"value": "Ana@AndesBank.example", "primary": True}],
    })  # fmt: skip
    assert (fields.email, fields.given_name, fields.active) == ("ana@andesbank.example", "Ana", True)
    assert protocol.user_fields({"userName": "B@x.example", "active": False}).email == "b@x.example"
    with pytest.raises(ScimError):
        protocol.user_fields({"name": {}})


def _patch(*operations: dict[str, object]) -> dict[str, object]:
    return {"schemas": [protocol.PATCH], "Operations": list(operations)}


def test_user_patch_understands_entra_and_okta() -> None:
    assert protocol.user_patch(_patch({"op": "Replace", "value": {"active": "False"}})) == {"active": False}
    assert protocol.user_patch(_patch({"op": "replace", "path": "active", "value": True})) == {"active": True}
    changes = protocol.user_patch(_patch(
        {"op": "replace", "path": "name.givenName", "value": "Ana"},
        {"op": "replace", "path": 'emails[type eq "work"].value', "value": "Ana@x.example"},
        {"op": "remove", "path": "externalId"},
    ))  # fmt: skip
    assert changes == {"given_name": "Ana", "email": "ana@x.example", "external_id": None}
    with pytest.raises(ScimError) as caught:
        protocol.user_patch(_patch({"op": "replace", "path": "roles", "value": "x"}))
    assert caught.value.scim_type == "invalidPath"
    with pytest.raises(ScimError):
        protocol.user_patch({"Operations": [{"op": "replace", "value": {"active": False}}]})  # no PatchOp schema


def test_group_patch_adds_removes_and_replaces_members() -> None:
    patch = protocol.group_patch(_patch(
        {"op": "add", "path": "members", "value": [{"value": "u1"}, {"value": "u2"}]},
        {"op": "remove", "path": 'members[value eq "u3"]'},
        {"op": "replace", "path": "displayName", "value": "Auditors"},
    ))  # fmt: skip
    assert (patch.add, patch.remove, patch.display_name) == (("u1", "u2"), ("u3",), "Auditors")
    assert protocol.group_patch(_patch({"op": "replace", "path": "members", "value": []})).replace_members == []
    assert protocol.group_patch(_patch({"op": "remove", "path": "members"})).remove_all


def test_errors_use_the_scim_format() -> None:
    res = protocol.error_response(ScimError(409, "taken", "uniqueness"))
    assert res.media_type == protocol.SCIM_JSON
    assert json.loads(bytes(res.body)) == {"schemas": [protocol.ERROR], "status": "409", "detail": "taken",
                                           "scimType": "uniqueness"}  # fmt: skip
    assert protocol.error_response(ScimError(401, "no")).headers["www-authenticate"].startswith("Bearer")
