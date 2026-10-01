output "cluster_name" {
  value = aws_eks_cluster.main.name
}

output "database_endpoint" {
  value = aws_db_instance.main.address
}

output "redis_endpoint" {
  value = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "artifacts_bucket" {
  value = aws_s3_bucket.artifacts.bucket
}

output "secret_arn" {
  description = "The generated credentials; synced into the chart's Secret (secretName)"
  value       = aws_secretsmanager_secret.platform.arn
}
