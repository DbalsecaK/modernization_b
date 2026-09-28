"""Permission catalog and base roles (spec 16.1 and 16.2).

Roles are configurable bundles: when a tenant is created it gets a copy of every base tenant and project
role, which its administrator can then edit. Platform roles are not bundles; they are assigned directly.
The keys match the prototype (`apps/web`) so the UI needs no mapping.
"""

from dataclasses import dataclass
from typing import Literal

Scope = Literal["tenant", "project"]
PlatformRole = Literal["superAdmin", "supportOperator"]
PLATFORM_ROLES: tuple[PlatformRole, ...] = ("superAdmin", "supportOperator")

# The tenant administrator inherits every permission on the tenant and its projects, except signing
# sign-offs (16.3); that inheritance lives in the OpenFGA model, not in the bundle.
TENANT_ADMIN_ROLE = "tenantAdmin"


@dataclass(frozen=True)
class Permission:
    key: str
    scopes: tuple[Scope, ...]
    description: str


PERMISSIONS: tuple[Permission, ...] = (
    Permission("project.create", ("tenant",), "Create projects in the tenant"),
    Permission("project.configure", ("project",), "Change the configuration of a project"),
    Permission("input.upload", ("project",), "Upload inputs to a project"),
    Permission("pipeline.run", ("project",), "Run the pipeline of a project"),
    Permission("gate.c1.approve", ("project",), "Approve gate C1"),
    Permission("gate.c2.approve", ("project",), "Approve gate C2"),
    Permission("gate.c3.approve", ("project",), "Approve gate C3"),
    Permission("signoff.sign", ("project",), "Sign the sign-off of a project"),
    Permission("code.view", ("tenant", "project"), "View generated and source code"),
    Permission("code.download", ("project",), "Download code"),
    Permission("code.push", ("project",), "Push code to the customer repository"),
    Permission("models.configure", ("tenant",), "Configure AI connections, catalog and profiles"),
    Permission("usage.view", ("tenant", "project"), "View token usage"),
    Permission("cost.view", ("tenant",), "View costs in money"),
    Permission("agents.select", ("project",), "Select the agents of a project"),
    Permission("skills.select", ("project",), "Select the skills of a project"),
    Permission("skills.publish", ("tenant",), "Publish customer skills"),
    Permission("users.manage", ("tenant",), "Manage users, invitations, roles and permissions"),
    Permission("audit.view", ("tenant",), "View the audit log"),
)


@dataclass(frozen=True)
class BaseRole:
    key: str
    scope: Scope
    name: str
    permissions: tuple[str, ...]


BASE_ROLES: tuple[BaseRole, ...] = (
    BaseRole(
        TENANT_ADMIN_ROLE,
        "tenant",
        "Customer admin",
        (
            "project.create",
            "models.configure",
            "usage.view",
            "cost.view",
            "skills.publish",
            "users.manage",
            "audit.view",
            "code.view",
        ),
    ),
    BaseRole("auditor", "tenant", "Auditor", ("audit.view", "usage.view", "code.view")),
    BaseRole("finance", "tenant", "Finance", ("usage.view", "cost.view")),
    BaseRole(
        "projectOwner",
        "project",
        "Project owner",
        (
            "project.configure",
            "input.upload",
            "pipeline.run",
            "gate.c1.approve",
            "gate.c2.approve",
            "signoff.sign",
            "code.view",
            "code.download",
            "usage.view",
            "agents.select",
            "skills.select",
        ),
    ),
    BaseRole(
        "architect",
        "project",
        "Architect",
        ("gate.c3.approve", "signoff.sign", "code.view", "agents.select", "skills.select"),
    ),
    BaseRole("analyst", "project", "Analyst / Delivery", ("input.upload", "pipeline.run", "code.view")),
    BaseRole("businessReviewer", "project", "Business reviewer / PO", ("gate.c1.approve", "gate.c2.approve")),
    BaseRole("developer", "project", "Developer", ("code.view", "code.download", "code.push")),
    BaseRole("observer", "project", "Observer / Customer", ()),
)


def permission_scopes() -> dict[str, tuple[Scope, ...]]:
    return {p.key: p.scopes for p in PERMISSIONS}
