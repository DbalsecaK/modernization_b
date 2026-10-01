# ruff: noqa: E501 - the HCL templates keep the lines OpenTofu formats
"""The Azure IaC of a target (spec 8.4, ADR-0021), deterministic: a resource group and a virtual network, the service on
Container Apps, the database managed and private (PostgreSQL Flexible Server, Azure SQL or Oracle Database@Azure),
its password generated and kept in Key Vault, and the logs in Log Analytics. Everything is tagged."""

from nexti_pack_iac.common import Target


def _database(database: str) -> str:
    if database == "sqlserver":
        return """resource "azurerm_mssql_server" "main" {
  name                          = "${local.name}-sql"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  version                       = "12.0"
  administrator_login           = "app"
  administrator_login_password  = random_password.db.result
  minimum_tls_version           = "1.2"
  public_network_access_enabled = false
  tags                          = local.tags
}

resource "azurerm_mssql_database" "main" {
  name      = local.name
  server_id = azurerm_mssql_server.main.id
  sku_name  = "S0"
  tags      = local.tags
}
"""
    if database == "oracle":
        return """resource "azurerm_oracle_autonomous_database" "main" {
  name                             = "${local.name}db"
  display_name                     = local.name
  resource_group_name              = azurerm_resource_group.main.name
  location                         = azurerm_resource_group.main.location
  admin_password                   = random_password.db.result
  db_version                       = "19c"
  db_workload                      = "OLTP"
  license_model                    = "LicenseIncluded"
  compute_model                    = "ECPU"
  compute_count                    = 2
  data_storage_size_in_tbs         = 1
  auto_scaling_enabled             = false
  auto_scaling_for_storage_enabled = false
  backup_retention_period_in_days  = 7
  character_set                    = "AL32UTF8"
  national_character_set           = "AL16UTF16"
  mtls_connection_required         = true
  subnet_id                        = azurerm_subnet.db.id
  virtual_network_id               = azurerm_virtual_network.main.id
  tags                             = local.tags
}
"""
    return """resource "azurerm_private_dns_zone" "db" {
  name                = "${local.name}.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "db" {
  name                  = "${local.name}-db"
  resource_group_name   = azurerm_resource_group.main.name
  private_dns_zone_name = azurerm_private_dns_zone.db.name
  virtual_network_id    = azurerm_virtual_network.main.id
  tags                  = local.tags
}

resource "azurerm_postgresql_flexible_server" "main" {
  name                          = "${local.name}-db"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  version                       = "16"
  sku_name                      = var.db_sku
  storage_mb                    = 32768
  backup_retention_days         = 7
  delegated_subnet_id           = azurerm_subnet.db.id
  private_dns_zone_id           = azurerm_private_dns_zone.db.id
  public_network_access_enabled = false
  administrator_login           = "app"
  administrator_password        = random_password.db.result
  tags                          = local.tags
  depends_on                    = [azurerm_private_dns_zone_virtual_network_link.db]
}
"""


def files(target: Target) -> dict[str, str]:
    name = target.name
    delegation = {"sqlserver": "", "oracle": "Oracle.Database/networkAttachments",
                  "postgresql": "Microsoft.DBforPostgreSQL/flexibleServers"}.get(target.database,
                                                                               "Microsoft.DBforPostgreSQL/flexibleServers")  # fmt: skip
    db_subnet_delegation = (
        f'''  delegation {{
    name = "db"
    service_delegation {{
      name = "{delegation}"
    }}
  }}
'''
        if delegation
        else ""
    )
    main = f'''terraform {{
  required_version = ">= 1.8"
  required_providers {{
    azurerm = {{ source = "hashicorp/azurerm", version = "~> 4.0" }}
    random  = {{ source = "hashicorp/random", version = "~> 3.6" }}
  }}
}}

provider "azurerm" {{
  features {{}}
}}

locals {{
  name = "{name}"
  tags = {{
    project     = "{name}"
    environment = var.environment
    managed-by  = "nexti"
  }}
}}

data "azurerm_client_config" "current" {{}}

resource "azurerm_resource_group" "main" {{
  name     = "rg-${{local.name}}"
  location = var.location
  tags     = local.tags
}}

# -- network: the service and the database in their own subnets ----------------------------------------------------
resource "azurerm_virtual_network" "main" {{
  name                = "vnet-${{local.name}}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  address_space       = ["10.30.0.0/16"]
  tags                = local.tags
}}

resource "azurerm_subnet" "app" {{
  name                 = "app"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.30.0.0/23"]
}}

resource "azurerm_subnet" "db" {{
  name                 = "db"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.30.4.0/24"]
{db_subnet_delegation}}}

# -- secrets and logs --------------------------------------------------------------------------------------------
resource "random_password" "db" {{
  length  = 32
  special = false
}}

resource "azurerm_key_vault" "main" {{
  name                       = "kv-${{local.name}}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  purge_protection_enabled   = true
  soft_delete_retention_days = 90
  tags                       = local.tags
}}

resource "azurerm_key_vault_secret" "db" {{
  name         = "db-password"
  value        = random_password.db.result
  key_vault_id = azurerm_key_vault.main.id
  tags         = local.tags
}}

resource "azurerm_log_analytics_workspace" "main" {{
  name                = "log-${{local.name}}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  retention_in_days   = 30
  tags                = local.tags
}}

# -- database: the tables of the legacy, managed and private -------------------------------------------------------
{_database(target.database)}
# -- service: the generated application on Container Apps ----------------------------------------------------------
resource "azurerm_user_assigned_identity" "app" {{
  name                = "id-${{local.name}}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags
}}

resource "azurerm_role_assignment" "secrets" {{
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}}

resource "azurerm_container_app_environment" "main" {{
  name                       = "cae-${{local.name}}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  infrastructure_subnet_id   = azurerm_subnet.app.id
  tags                       = local.tags
}}

resource "azurerm_container_app" "main" {{
  name                         = local.name
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = local.tags
  identity {{
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }}
  secret {{
    name                = "db-password"
    key_vault_secret_id = azurerm_key_vault_secret.db.id
    identity            = azurerm_user_assigned_identity.app.id
  }}
  ingress {{
    external_enabled = true
    target_port      = 8080
    traffic_weight {{
      latest_revision = true
      percentage      = 100
    }}
  }}
  template {{
    min_replicas = 1
    max_replicas = 3
    container {{
      name   = local.name
      image  = var.container_image
      cpu    = 0.5
      memory = "1Gi"
      env {{
        name        = "DB_PASSWORD"
        secret_name = "db-password"
      }}
    }}
  }}
}}
'''
    variables = """variable "location" {
  type    = string
  default = "eastus2"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "container_image" {
  type        = string
  description = "The image of the generated service, built and pushed by the pipeline of the customer"
}

variable "db_sku" {
  type    = string
  default = "GP_Standard_D2s_v3"
}
"""
    outputs = """output "url" {
  value = "https://${azurerm_container_app.main.ingress[0].fqdn}"
}
"""
    return {"main.tf": main, "variables.tf": variables, "outputs.tf": outputs}
