"""Object ids and relation names of the OpenFGA model (infra/openfga/model.fga)."""

import uuid
from dataclasses import dataclass

from nexti_core.authz_catalog import PlatformRole

PLATFORM = "platform:nexti"
PLATFORM_RELATION: dict[PlatformRole, str] = {"superAdmin": "super_admin", "supportOperator": "support_operator"}


@dataclass(frozen=True, order=True)
class Tuple:
    user: str
    relation: str
    object: str

    def as_key(self) -> dict[str, str]:
        return {"user": self.user, "relation": self.relation, "object": self.object}


def relation(permission_key: str) -> str:
    """users.manage -> users_manage"""
    return permission_key.replace(".", "_")


def permission_key(relation_name: str) -> str:
    """users_manage -> users.manage; gate_c1_approve -> gate.c1.approve"""
    return relation_name.replace("_", ".")


def user(user_id: uuid.UUID) -> str:
    return f"user:{user_id}"


def tenant(tenant_id: uuid.UUID) -> str:
    return f"tenant:{tenant_id}"


def project(project_id: uuid.UUID) -> str:
    return f"project:{project_id}"


def role_assignees(role_id: uuid.UUID) -> str:
    return f"role:{role_id}#assignee"


def role(role_id: uuid.UUID) -> str:
    return f"role:{role_id}"


def binding(project_id: uuid.UUID, role_id: uuid.UUID) -> str:
    return f"role_binding:{project_id}_{role_id}"


def binding_assignees(project_id: uuid.UUID, role_id: uuid.UUID) -> str:
    return f"{binding(project_id, role_id)}#assignee"
