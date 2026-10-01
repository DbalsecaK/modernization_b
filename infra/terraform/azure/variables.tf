variable "name" {
  type        = string
  description = "Name of the installation (lowercase letters and digits; resource names and the project tag)"
  default     = "nexti"
}

variable "location" {
  type    = string
  default = "eastus2"
}

variable "environment" {
  type    = string
  default = "production"
}

variable "kubernetes_version" {
  type    = string
  default = "1.31"
}

variable "node_vm_size" {
  type    = string
  default = "Standard_D4s_v5"
}

variable "node_count" {
  type    = number
  default = 3
}

variable "db_sku" {
  type    = string
  default = "GP_Standard_D4s_v3"
}
