output "cluster_name" {
  value = azurerm_kubernetes_cluster.main.name
}

output "database_host" {
  value = azurerm_postgresql_flexible_server.main.fqdn
}

output "redis_host" {
  value = azurerm_redis_cache.main.hostname
}

output "storage_account" {
  value = azurerm_storage_account.artifacts.name
}

output "key_vault_uri" {
  description = "The generated credentials; synced into the chart's Secret (secretName)"
  value       = azurerm_key_vault.main.vault_uri
}
