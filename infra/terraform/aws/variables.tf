variable "name" {
  type        = string
  description = "Name of the installation (resource names and the project tag)"
  default     = "nexti"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "production"
}

variable "kubernetes_version" {
  type    = string
  default = "1.31"
}

variable "node_instance_type" {
  type    = string
  default = "m6i.xlarge"
}

variable "node_count" {
  type    = number
  default = 3
}

variable "db_instance_class" {
  type    = string
  default = "db.r6g.large"
}

variable "cache_node_type" {
  type    = string
  default = "cache.r6g.large"
}
