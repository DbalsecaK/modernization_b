"""The fitness functions of the deployment pack (spec 8.4, ADR-0021, ADR-0027), computed by code over the generated
HCL: the database encrypted at rest and not public, no secret written in the code, the mandatory tags (labels on GCP)
and the logs, for AWS, Azure and GCP, containers or serverless. A check fails with the resources that break it."""

import re
from dataclasses import dataclass

from nexti_verification.verdict import Check

_RESOURCE = re.compile(r'^resource\s+"([\w-]+)"\s+"([\w-]+)"\s*\{', re.MULTILINE)
_LITERAL_SECRET = re.compile(r'^\s*(password|admin_password|administrator_password|administrator_login_password|'
                             r'root_password|secret_string|secret_data)\s*=\s*"[^"$]{4,}"', re.MULTILINE)  # fmt: skip
_LITERAL_VALUE = re.compile(r'^\s*value\s*=\s*"[^"$]{4,}"', re.MULTILINE)
SECRET_RESOURCES = {"azurerm_key_vault_secret", "aws_secretsmanager_secret_version", "aws_ssm_parameter",
                    "google_secret_manager_secret_version"}  # fmt: skip
TAGS = ("project", "environment", "managed-by")
DATABASES = {"aws_db_instance", "azurerm_postgresql_flexible_server", "azurerm_mysql_flexible_server",
             "azurerm_mssql_server", "azurerm_oracle_autonomous_database", "google_sql_database_instance"}  # fmt: skip
UNTAGGED = {"azurerm_subnet", "azurerm_role_assignment", "azurerm_mysql_flexible_database"}  # no tags in the provider
# Encrypted at rest by the cloud, always (the note of the check says so).
ENCRYPTED_BY_THE_CLOUD = {"azurerm": "Azure encrypts its managed databases", "google": "GCP encrypts Cloud SQL"}
# How a workload sends its logs: ECS (awslogs), Lambda (logging_config), EKS control plane, Container Apps and AKS
# (Log Analytics), Cloud Run (a log sink to a bucket with retention).
LOG_SENDERS = ("awslogs", "logging_config", "enabled_cluster_log_types", "log_analytics_workspace_id",
               'resource "google_logging_project_sink"')  # fmt: skip
LOG_STORES = ("aws_cloudwatch_log_group", "azurerm_log_analytics_workspace", "google_logging_project_bucket_config")
# Each workload type and what in its own body says where its logs go.
WORKLOAD_LOGS = {"aws_lambda_function": "logging_config"}


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
    notes = sorted({note for prefix, note in ENCRYPTED_BY_THE_CLOUD.items() for r in databases
                    if r.type.startswith(f"{prefix}_")})  # fmt: skip
    found.append(_check("encryption_at_rest", unencrypted, f"{len(databases)} database(s) encrypted at rest"
                        + (f" ({'; '.join(notes)})" if notes else "")))  # fmt: skip

    public = [r.address for r in databases if not _private(r)]
    found.append(
        _check("db_not_public", public, f"{len(databases)} database(s) reachable only from the private network")
    )

    secrets = [m.group(0).strip().split("=", 1)[0].strip() for m in _LITERAL_SECRET.finditer(hcl)]
    secrets += [
        f"{r.address}.value" for r in all_resources if r.type in SECRET_RESOURCES and _LITERAL_VALUE.search(r.body)
    ]
    found.append(_check("no_secrets_in_code", secrets, "passwords are generated (random_password) and kept in the "
                        "secrets store; none is written in the code"))  # fmt: skip

    tags = re.search(r"\b(?:tags|labels)\s*=\s*\{([^}]*)\}", hcl)
    missing = [t for t in TAGS if not tags or not re.search(rf"^\s*{re.escape(t)}\s*=", tags.group(1), re.MULTILINE)]
    untagged = [r.address for r in all_resources if r.type.startswith("azurerm_") and r.type not in UNTAGGED
                and not r.has("tags", "local.tags")]  # fmt: skip
    if hcl.lstrip().find('provider "aws"') >= 0 and "default_tags" not in hcl:
        untagged.append('provider "aws" (no default_tags)')
    if 'provider "google"' in hcl and not re.search(r"^\s*default_labels\s*=", hcl, re.MULTILINE):
        untagged.append('provider "google" (no default_labels)')
    # Cloud SQL's labels live in its settings and the provider's default_labels do not reach them.
    untagged += [r.address for r in all_resources if r.type == "google_sql_database_instance"
                 and not r.has("user_labels", "local.labels")]  # fmt: skip
    found.append(_check("tags", [f"tag {t}" for t in missing] + untagged,
                        f"every resource carries the tags {', '.join(TAGS)}"))  # fmt: skip

    logs = [r for r in all_resources if r.type in LOG_STORES]
    without = [r.address for r in logs if not re.search(r"^\s*retention_(in_)?days\s*=", r.body, re.MULTILINE)]
    if not logs:
        without.append("no log group or workspace")
    elif not any(sender in hcl for sender in LOG_SENDERS):
        without.append("the service does not send its logs")
    without += [f"{r.address} does not send its logs" for r in all_resources
                if r.type in WORKLOAD_LOGS and WORKLOAD_LOGS[r.type] not in r.body]  # fmt: skip
    found.append(_check("logs", without, "the service sends its logs to a group with retention"))
    return found


def _private(database: Resource) -> bool:
    """Reachable only from the private network: Cloud SQL without a public IPv4 and on the VPC; the others not publicly
    accessible, without public network access, or placed in a subnet."""
    if database.type == "google_sql_database_instance":
        return database.has("ipv4_enabled", "false") and "private_network" in database.body
    return (database.has("publicly_accessible", "false") or database.has("public_network_access_enabled", "false")
            or "subnet_id" in database.body)  # fmt: skip


def _check(key: str, offenders: list[str], passed: str) -> Check:
    if offenders:
        return Check(key, "failed", f"{len(offenders)} problem(s): {', '.join(offenders[:6])}"[:1000],
                     {"offenders": offenders})  # fmt: skip
    return Check(key, "passed", passed)
