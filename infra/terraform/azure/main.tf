# The NexTI platform on Azure (spec 14.4, ADR-0024): a private AKS cluster for the Helm chart (infra/helm/nexti),
# PostgreSQL Flexible Server, Azure Cache for Redis and a storage account for the inputs and artifacts, all private,
# the credentials generated and kept in Key Vault, and the logs in Log Analytics. Everything is tagged.
terraform {
  required_version = ">= 1.8"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "azurerm" {
  features {}
}

locals {
  name = var.name
  tags = {
    project     = var.name
    environment = var.environment
    managed-by  = "nexti"
  }
}

data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "main" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = local.tags
}

# -- network ------------------------------------------------------------------------------------------------------
resource "azurerm_virtual_network" "main" {
  name                = "vnet-${local.name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  address_space       = ["10.50.0.0/16"]
  tags                = local.tags
}

resource "azurerm_subnet" "cluster" {
  name                 = "cluster"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.50.0.0/20"]
}

resource "azurerm_subnet" "db" {
  name                 = "db"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.50.16.0/24"]
  delegation {
    name = "db"
    service_delegation {
      name = "Microsoft.DBforPostgreSQL/flexibleServers"
    }
  }
}

# -- secrets and logs ---------------------------------------------------------------------------------------------
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "azurerm_key_vault" "main" {
  name                       = "kv-${local.name}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  purge_protection_enabled   = true
  soft_delete_retention_days = 90
  tags                       = local.tags
}

resource "azurerm_key_vault_secret" "db" {
  name         = "database-password"
  value        = random_password.db.result
  key_vault_id = azurerm_key_vault.main.id
  tags         = local.tags
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${local.name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  retention_in_days   = 90
  tags                = local.tags
}

# -- cluster: private AKS, Entra ID with Azure RBAC, no local accounts, network policies -------------------------------
resource "azurerm_kubernetes_cluster" "main" {
  name                    = "aks-${local.name}"
  resource_group_name     = azurerm_resource_group.main.name
  location                = azurerm_resource_group.main.location
  dns_prefix              = local.name
  kubernetes_version      = var.kubernetes_version
  private_cluster_enabled = true
  local_account_disabled  = true
  tags                    = local.tags
  default_node_pool {
    name           = "system"
    vm_size        = var.node_vm_size
    node_count     = var.node_count
    vnet_subnet_id = azurerm_subnet.cluster.id
  }
  identity {
    type = "SystemAssigned"
  }
  azure_active_directory_role_based_access_control {
    azure_rbac_enabled = true
    tenant_id          = data.azurerm_client_config.current.tenant_id
  }
  network_profile {
    network_plugin = "azure"
    network_policy = "azure"
  }
  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  }
  key_vault_secrets_provider {
    secret_rotation_enabled = true
  }
}

# -- data: PostgreSQL, Redis and storage, private ----------------------------------------------------------------
resource "azurerm_private_dns_zone" "db" {
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
  name                          = "psql-${local.name}"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  version                       = "16"
  sku_name                      = var.db_sku
  storage_mb                    = 131072
  backup_retention_days         = 14
  geo_redundant_backup_enabled  = true
  delegated_subnet_id           = azurerm_subnet.db.id
  private_dns_zone_id           = azurerm_private_dns_zone.db.id
  public_network_access_enabled = false
  administrator_login           = "nexti_owner"
  administrator_password        = random_password.db.result
  tags                          = local.tags
  depends_on                    = [azurerm_private_dns_zone_virtual_network_link.db]
}

resource "azurerm_redis_cache" "main" {
  name                          = "redis-${local.name}"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  capacity                      = 1
  family                        = "P"
  sku_name                      = "Premium"
  non_ssl_port_enabled          = false
  minimum_tls_version           = "1.2"
  public_network_access_enabled = false
  subnet_id                     = azurerm_subnet.cluster.id
  tags                          = local.tags
}

resource "azurerm_storage_account" "artifacts" {
  name                              = replace("st${local.name}artifacts", "-", "")
  resource_group_name               = azurerm_resource_group.main.name
  location                          = azurerm_resource_group.main.location
  account_tier                      = "Standard"
  account_replication_type          = "ZRS"
  min_tls_version                   = "TLS1_2"
  https_traffic_only_enabled        = true
  allow_nested_items_to_be_public   = false
  public_network_access_enabled     = false
  shared_access_key_enabled         = false
  infrastructure_encryption_enabled = true
  tags                              = local.tags
  blob_properties {
    versioning_enabled = true
  }
}
