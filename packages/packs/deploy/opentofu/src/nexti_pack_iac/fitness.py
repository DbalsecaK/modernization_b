"""The fitness functions of the deployment pack (spec 8.4, ADR-0021), computed by code over the generated HCL: the
database encrypted at rest and not public, no secret written in the code, the mandatory tags and the logs. A check
fails with the resources that break it."""

import re
from dataclasses import dataclass

from nexti_verification.verdict import Check

_RESOURCE = re.compile(r'^resource\s+"([\w-]+)"\s+"([\w-]+)"\s*\{', re.MULTILINE)
_LITERAL_SECRET = re.compile(r'^\s*(password|admin_password|administrator_password|administrator_login_password|'
                             r'secret_string)\s*=\s*"[^"$]{4,}"', re.MULTILINE)  # fmt: skip
_LITERAL_VALUE = re.compile(r'^\s*value\s*=\s*"[^"$]{4,}"', re.MULTILINE)
SECRET_RESOURCES = {"azurerm_key_vault_secret", "aws_secretsmanager_secret_version", "aws_ssm_parameter"}
TAGS = ("project", "environment", "managed-by")
DATABASES = {"aws_db_instance", "azurerm_postgresql_flexible_server", "azurerm_mssql_server",
             "azurerm_oracle_autonomous_database"}  # fmt: skip
UNTAGGED = {"azurerm_subnet", "azurerm_role_assignment"}  # resources without tags in the provider
# How a workload sends its logs: ECS (awslogs), EKS control plane, Container Apps and AKS (Log Analytics).
LOG_SENDERS = ("awslogs", "enabled_cluster_log_types", "log_analytics_workspace_id")


@dataclass(frozen=True)
class Resource:
    type: str
    name: str
    body: str

    @property
    def address(self) -> str:
        return f"{self.type}.{self.name}"

    def has(self, attribute: str, value: str) -> bool:
        return (
            re.search(rf"^\s*{re.escape(attribute)}\s*=\s*{re.escape(value)}\s*$", self.body, re.MULTILINE) is not None
        )


def resources(hcl: str) -> list[Resource]:
    found = []
    for match in _RESOURCE.finditer(hcl):
        depth, index = 0, match.end() - 1
        while index < len(hcl):
            depth += {"{": 1, "}": -1}.get(hcl[index], 0)
            if depth == 0:
                break
            index += 1
        found.append(Resource(match.group(1), match.group(2), hcl[match.end() : index]))
    return found


def checks(hcl: str) -> list[Check]:
    all_resources = resources(hcl)
    databases = [r for r in all_resources if r.type in DATABASES]
    found: list[Check] = []

    unencrypted = [
        r.address for r in databases if r.type == "aws_db_instance" and not r.has("storage_encrypted", "true")
    ]
    found.append(_check("encryption_at_rest", unencrypted, f"{len(databases)} database(s) encrypted at rest"
                        + (" (Azure encrypts its managed databases)" if any(r.type.startswith("azurerm")
                                                                            for r in databases) else "")))  # fmt: skip

    public = [r.address for r in databases if not (
        r.has("publicly_accessible", "false") or r.has("public_network_access_enabled", "false")
        or "subnet_id" in r.body)]  # fmt: skip
    found.append(
        _check("db_not_public", public, f"{len(databases)} database(s) reachable only from the private network")
    )

    secrets = [m.group(0).strip().split("=", 1)[0].strip() for m in _LITERAL_SECRET.finditer(hcl)]
    secrets += [
        f"{r.address}.value" for r in all_resources if r.type in SECRET_RESOURCES and _LITERAL_VALUE.search(r.body)
    ]
    found.append(_check("no_secrets_in_code", secrets, "passwords are generated (random_password) and kept in the "
                        "secrets store; none is written in the code"))  # fmt: skip

    tags = re.search(r"tags\s*=\s*\{([^}]*)\}", hcl)
    missing = [t for t in TAGS if not tags or not re.search(rf"^\s*{re.escape(t)}\s*=", tags.group(1), re.MULTILINE)]
    untagged = [r.address for r in all_resources if r.type.startswith("azurerm_") and r.type not in UNTAGGED
                and not r.has("tags", "local.tags")]  # fmt: skip
    if hcl.lstrip().find('provider "aws"') >= 0 and "default_tags" not in hcl:
        untagged.append('provider "aws" (no default_tags)')
    found.append(_check("tags", [f"tag {t}" for t in missing] + untagged,
                        f"every resource carries the tags {', '.join(TAGS)}"))  # fmt: skip

    logs = [r for r in all_resources if r.type in ("aws_cloudwatch_log_group", "azurerm_log_analytics_workspace")]
    without = [r.address for r in logs if "retention_in_days" not in r.body]
    if not logs:
        without.append("no log group or workspace")
    elif not any(sender in hcl for sender in LOG_SENDERS):
        without.append("the service does not send its logs")
    found.append(_check("logs", without, "the service sends its logs to a group with retention"))
    return found


def _check(key: str, offenders: list[str], passed: str) -> Check:
    if offenders:
        return Check(key, "failed", f"{len(offenders)} problem(s): {', '.join(offenders[:6])}"[:1000],
                     {"offenders": offenders})  # fmt: skip
    return Check(key, "passed", passed)
