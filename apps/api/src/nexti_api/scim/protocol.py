"""The SCIM 2.0 subset the platform speaks (RFC 7643 and 7644), as pure functions: errors, filters, paging, PATCH.

Only what identity providers (Entra ID, Okta) send is accepted: `eq` filters on `userName`, `externalId` and
`displayName`, paging with `startIndex` and `count`, and PATCH operations on `active`, the name, the e-mails and the
members of a group. Anything else is answered with a SCIM error, never guessed.
"""

import re
from dataclasses import dataclass
from typing import Any

from fastapi.responses import JSONResponse

SCIM_JSON = "application/scim+json"
USER = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
LIST = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"
MAX_COUNT = 200
DEFAULT_COUNT = 100


class ScimError(Exception):
    """An error in the SCIM format (RFC 7644 section 3.12); `scim_type` is one of the RFC's keywords."""

    def __init__(self, status: int, detail: str, scim_type: str | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.scim_type = scim_type


def error_response(exc: ScimError) -> JSONResponse:
    body: dict[str, Any] = {"schemas": [ERROR], "status": str(exc.status), "detail": exc.detail}
    if exc.scim_type:
        body["scimType"] = exc.scim_type
    headers = {"WWW-Authenticate": 'Bearer realm="scim"'} if exc.status == 401 else None
    return JSONResponse(body, status_code=exc.status, media_type=SCIM_JSON, headers=headers)


def response(body: dict[str, Any], status: int = 200, location: str | None = None) -> JSONResponse:
    return JSONResponse(body, status_code=status, media_type=SCIM_JSON,
                        headers={"Location": location} if location else None)  # fmt: skip


# -- Filters ------------------------------------------------------------------------------------------------------
_FILTER = re.compile(r'^\s*([A-Za-z][A-Za-z0-9.]*)\s+eq\s+"((?:[^"\\]|\\.)*)"\s*$', re.IGNORECASE)


@dataclass(frozen=True)
class Filter:
    attribute: str  # the canonical name, one of the allowed ones
    value: str


def parse_filter(raw: str | None, allowed: tuple[str, ...]) -> Filter | None:
    """`attribute eq "value"` with an allowed attribute (case-insensitive name); None without a filter."""
    if raw is None or not raw.strip():
        return None
    match = _FILTER.match(raw)
    if match is None:
        raise ScimError(400, 'Only filters of the form: attribute eq "value" are supported.', "invalidFilter")
    names = {a.lower(): a for a in allowed}
    attribute = names.get(match.group(1).lower())
    if attribute is None:
        raise ScimError(400, f"Filtering is supported on: {', '.join(allowed)}.", "invalidFilter")
    value = re.sub(r"\\(.)", r"\1", match.group(2))
    return Filter(attribute, value)


# -- Paging -------------------------------------------------------------------------------------------------------
def paging(start_index: str | None, count: str | None) -> tuple[int, int]:
    """(offset, limit) from the 1-based startIndex and count (RFC 7644 3.4.2.4: out-of-range values are clamped)."""
    try:
        start = int(start_index) if start_index else 1
        size = int(count) if count is not None and count != "" else DEFAULT_COUNT
    except ValueError:
        raise ScimError(400, "startIndex and count must be integers.", "invalidValue") from None
    return max(start, 1) - 1, min(max(size, 0), MAX_COUNT)


def list_response(resources: list[dict[str, Any]], total: int, offset: int) -> dict[str, Any]:
    return {"schemas": [LIST], "totalResults": total, "startIndex": offset + 1, "itemsPerPage": len(resources),
            "Resources": resources}  # fmt: skip


# -- Values -------------------------------------------------------------------------------------------------------
def as_bool(value: Any) -> bool:
    """Entra ID sends booleans as "True"/"False" in PATCH; anything else is not a boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    raise ScimError(400, "active must be a boolean.", "invalidValue")


def text(value: Any, name: str, limit: int, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise ScimError(400, f"{name} is required.", "invalidValue")
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ScimError(400, f"{name} must be a string of at most {limit} characters.", "invalidValue")
    return value.strip()


def primary_email(emails: Any) -> str | None:
    """The primary e-mail of a SCIM `emails` list (else the work one, else the first)."""
    if emails is None:
        return None
    if not isinstance(emails, list) or not all(isinstance(e, dict) for e in emails):
        raise ScimError(400, "emails must be a list of objects.", "invalidValue")
    ordered = sorted(emails, key=lambda e: (not e.get("primary"), e.get("type") != "work"))
    for item in ordered:
        if isinstance(item.get("value"), str) and item["value"].strip():
            return str(item["value"]).strip()
    return None


@dataclass(frozen=True)
class UserFields:
    """What the platform keeps of a SCIM user; `None` means "not given" in a PATCH."""

    user_name: str | None = None
    external_id: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    display_name: str | None = None
    email: str | None = None
    active: bool | None = None


def user_fields(body: dict[str, Any]) -> UserFields:
    """The fields of a full User representation (POST and PUT)."""
    if not isinstance(body, dict):
        raise ScimError(400, "The body must be a JSON object.", "invalidSyntax")
    name = body.get("name") or {}
    if not isinstance(name, dict):
        raise ScimError(400, "name must be an object.", "invalidValue")
    user_name = text(body.get("userName"), "userName", 320, required=True)
    email = primary_email(body.get("emails")) or user_name
    return UserFields(
        user_name=user_name,
        external_id=text(body.get("externalId"), "externalId", 320),
        given_name=text(name.get("givenName"), "name.givenName", 200),
        family_name=text(name.get("familyName"), "name.familyName", 200),
        display_name=text(body.get("displayName") or name.get("formatted"), "displayName", 200),
        email=email.lower() if email else None,
        active=as_bool(body["active"]) if "active" in body else True,
    )


def _operations(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict) or PATCH not in (body.get("schemas") or []):
        raise ScimError(400, f"A PATCH needs the schema {PATCH}.", "invalidSyntax")
    operations = body.get("Operations")
    if not isinstance(operations, list) or not operations or not all(isinstance(o, dict) for o in operations):
        raise ScimError(400, "Operations must be a non-empty list.", "invalidSyntax")
    for operation in operations:
        op = str(operation.get("op", "")).lower()
        if op not in ("add", "replace", "remove"):
            raise ScimError(400, f"Unsupported operation: {operation.get('op')}.", "invalidSyntax")
        operation["op"] = op
    return operations


_USER_PATHS = {
    "active": "active", "username": "user_name", "externalid": "external_id", "displayname": "display_name",
    "name.givenname": "given_name", "name.familyname": "family_name", "emails": "email",
    'emails[type eq "work"].value': "email", "emails[primary eq true].value": "email",
}  # fmt: skip


def user_patch(body: Any) -> dict[str, Any]:
    """The changes of a User PATCH (`replace`/`add` of the supported attributes; `remove` clears optional ones)."""
    changes: dict[str, Any] = {}
    for operation in _operations(body):
        path = operation.get("path")
        value = operation.get("value")
        if path is None:
            if operation["op"] == "remove" or not isinstance(value, dict):
                raise ScimError(400, "An operation without a path needs an object value.", "noTarget")
            items = list(value.items())
        else:
            items = [(str(path), value)]
        for key, item in items:
            field = _USER_PATHS.get(key.lower())
            if field is None and key.lower() == "name" and isinstance(item, dict):
                if operation["op"] != "remove":
                    changes["given_name"] = text(item.get("givenName"), "name.givenName", 200)
                    changes["family_name"] = text(item.get("familyName"), "name.familyName", 200)
                continue
            if field is None:
                raise ScimError(400, f"Unsupported attribute: {key}.", "invalidPath")
            if operation["op"] == "remove":
                if field in ("active", "user_name", "email"):
                    raise ScimError(400, f"{key} cannot be removed.", "mutability")
                changes[field] = None
            elif field == "active":
                changes["active"] = as_bool(item)
            elif field == "email":
                email = primary_email(item) if isinstance(item, list) else text(item, "email", 320, required=True)
                changes["email"] = email.lower() if email else None
            else:
                changes[field] = text(item, key, 320 if field in ("user_name", "external_id") else 200,
                                      required=field == "user_name")  # fmt: skip
    return changes


_MEMBER_FILTER = re.compile(r'^members\[\s*value\s+eq\s+"([^"]+)"\s*\]$', re.IGNORECASE)


@dataclass(frozen=True)
class GroupPatch:
    display_name: str | None = None
    external_id: str | None = None
    replace_members: list[str] | None = None
    add: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()
    remove_all: bool = False


def member_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(m, dict) and isinstance(m.get("value"), str) for m in value):
        raise ScimError(400, "members must be a list of objects with a value.", "invalidValue")
    return [str(m["value"]) for m in value]


def group_patch(body: Any) -> GroupPatch:
    """The changes of a Group PATCH: its name, and members added, removed or replaced."""
    display_name = external_id = None
    replace: list[str] | None = None
    add: list[str] = []
    remove: list[str] = []
    remove_all = False
    for operation in _operations(body):
        path = str(operation.get("path") or "")
        value = operation.get("value")
        op = operation["op"]
        pairs = list(value.items()) if not path and op != "remove" and isinstance(value, dict) else [(path, value)]
        for key, item in pairs:
            lowered = key.lower()
            filtered = _MEMBER_FILTER.match(key)
            if lowered == "displayname" and op != "remove":
                display_name = text(item, "displayName", 256, required=True)
            elif lowered == "externalid":
                external_id = None if op == "remove" else text(item, "externalId", 320)
            elif lowered == "members" and op == "add":
                add += member_ids(item)
            elif lowered == "members" and op == "replace":
                replace = member_ids(item)
                add, remove, remove_all = [], [], False
            elif lowered == "members" and op == "remove":
                if item is None:
                    remove_all, add, replace = True, [], None
                else:
                    remove += member_ids(item)
            elif filtered and op == "remove":
                remove.append(filtered.group(1))
            else:
                raise ScimError(400, f"Unsupported operation {op} on {key or 'the group'}.", "invalidPath")
    return GroupPatch(display_name, external_id, replace, tuple(add), tuple(remove), remove_all)


# -- Discovery (RFC 7644 section 4) -------------------------------------------------------------------------------
def service_provider_config(base: str) -> dict[str, Any]:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": MAX_COUNT},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [{"type": "oauthbearertoken", "name": "Bearer",
                                   "description": "The tenant's SCIM bearer, created in Administration."}],
        "meta": {"resourceType": "ServiceProviderConfig", "location": f"{base}/ServiceProviderConfig"},
    }  # fmt: skip


def resource_types(base: str) -> list[dict[str, Any]]:
    return [
        {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"], "id": name, "name": name,
         "endpoint": f"/{name}s", "schema": schema,
         "meta": {"resourceType": "ResourceType", "location": f"{base}/ResourceTypes/{name}"}}
        for name, schema in (("User", USER), ("Group", GROUP))
    ]  # fmt: skip


def _attribute(name: str, kind: str = "string", **extra: Any) -> dict[str, Any]:
    return {"name": name, "type": kind, "multiValued": False, "required": False, "caseExact": False,
            "mutability": "readWrite", "returned": "default", "uniqueness": "none", **extra}  # fmt: skip


def schemas(base: str) -> list[dict[str, Any]]:
    user = [
        _attribute("userName", required=True, uniqueness="server"),
        _attribute("externalId", caseExact=True),
        _attribute("displayName"),
        _attribute("active", "boolean"),
        _attribute("name", "complex", subAttributes=[_attribute("givenName"), _attribute("familyName")]),
        _attribute("emails", "complex", multiValued=True,
                   subAttributes=[_attribute("value"), _attribute("type"), _attribute("primary", "boolean")]),
    ]  # fmt: skip
    group = [
        _attribute("displayName", required=True, uniqueness="server"),
        _attribute("externalId", caseExact=True),
        _attribute("members", "complex", multiValued=True,
                   subAttributes=[_attribute("value", mutability="immutable"),
                                  _attribute("display", mutability="readOnly")]),
    ]  # fmt: skip
    return [
        {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Schema"], "id": schema, "name": name,
         "attributes": attributes, "meta": {"resourceType": "Schema", "location": f"{base}/Schemas/{schema}"}}
        for schema, name, attributes in ((USER, "User", user), (GROUP, "Group", group))
    ]  # fmt: skip
