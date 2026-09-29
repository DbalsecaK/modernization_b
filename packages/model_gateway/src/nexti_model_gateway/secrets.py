"""Provider credentials in the secrets store (ADR-0007). The client lives in `nexti_core.secrets`; the model
gateway is the only code that reads the credentials of the model providers."""

import uuid

from nexti_core.secrets import SecretsConfig, SecretsError, SecretStore

__all__ = ["SecretStore", "SecretsConfig", "SecretsError", "connection_path"]


def connection_path(tenant_id: uuid.UUID, connection_id: uuid.UUID) -> str:
    """Where a connection's credential lives: one path per tenant and connection."""
    return f"tenants/{tenant_id}/connections/{connection_id}"
