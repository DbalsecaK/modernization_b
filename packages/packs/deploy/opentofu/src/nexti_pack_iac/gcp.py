# ruff: noqa: E501 - the HCL templates keep the lines OpenTofu formats
"""The GCP IaC of a target (spec 8.4, ADR-0027), deterministic: a VPC with private services access, the service on
Cloud Run with direct VPC egress (scaling to zero when the architecture is serverless), the database on Cloud SQL
(PostgreSQL, MySQL or SQL Server) with a private IP only, its password generated and kept in Secret Manager, and the
logs of the service routed to a Cloud Logging bucket with retention. Every resource that takes labels is labelled (the
provider's default_labels, and user_labels on Cloud SQL)."""

from nexti_pack_iac.common import Target

# database_version, backup settings that only the engine accepts, and whether the engine needs a root password.
ENGINES = {
    "postgresql": ("POSTGRES_16", "      point_in_time_recovery_enabled = true\n", False),
    "mysql": ("MYSQL_8_4", "      binary_log_enabled = true\n", False),
    "sqlserver": ("SQLSERVER_2022_STANDARD", "", True),
}


def files(target: Target) -> dict[str, str]:
    version, backup, needs_root = ENGINES[target.database]
    root_password = "  root_password       = random_password.db.result\n" if needs_root else ""
    name = target.name
    min_instances = 0 if target.serverless else 1
    main = f'''terraform {{
  required_version = ">= 1.8"
  required_providers {{
    google = {{ source = "hashicorp/google", version = "~> 7.0" }}
    random = {{ source = "hashicorp/random", version = "~> 3.6" }}
  }}
}}

provider "google" {{
  project        = var.project
  region         = var.region
  default_labels = local.labels
}}

locals {{
  name = "{name}"
  labels = {{
    project     = "{name}"
    environment = var.environment
    managed-by  = "nexti"
  }}
}}

resource "google_project_service" "apis" {{
  for_each           = toset(["compute.googleapis.com", "run.googleapis.com", "sqladmin.googleapis.com", "secretmanager.googleapis.com", "servicenetworking.googleapis.com", "logging.googleapis.com"])
  service            = each.value
  disable_on_destroy = false
}}

# -- network: the service leaves through the VPC; the database has only a private IP (private services access) -----
resource "google_compute_network" "main" {{
  name                    = "${{local.name}}-vpc"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}}

resource "google_compute_subnetwork" "app" {{
  name                     = "${{local.name}}-app"
  network                  = google_compute_network.main.id
  region                   = var.region
  ip_cidr_range            = "10.40.0.0/24"
  private_ip_google_access = true
}}

resource "google_compute_global_address" "private_services" {{
  name          = "${{local.name}}-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.main.id
}}

resource "google_service_networking_connection" "private_services" {{
  network                 = google_compute_network.main.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}}

# -- secrets and logs --------------------------------------------------------------------------------------------
resource "random_password" "db" {{
  length  = 32
  special = false
}}

resource "google_secret_manager_secret" "db" {{
  secret_id = "${{local.name}}-db-password"
  replication {{
    auto {{}}
  }}
  depends_on = [google_project_service.apis]
}}

resource "google_secret_manager_secret_version" "db" {{
  secret      = google_secret_manager_secret.db.id
  secret_data = random_password.db.result
}}

resource "google_logging_project_bucket_config" "app" {{
  project        = var.project
  location       = "global"
  bucket_id      = "${{local.name}}-logs"
  retention_days = 30
}}

resource "google_logging_project_sink" "app" {{
  name                   = "${{local.name}}-logs"
  destination            = "logging.googleapis.com/${{google_logging_project_bucket_config.app.id}}"
  filter                 = "resource.type=\\"cloud_run_revision\\" AND resource.labels.service_name=\\"${{local.name}}\\""
  unique_writer_identity = true
}}

# -- database: the tables of the legacy, on Cloud SQL, with a private IP only --------------------------------------
resource "google_sql_database_instance" "main" {{
  name                = "${{local.name}}-db"
  database_version    = "{version}"
  region              = var.region
  deletion_protection = true
{root_password}  depends_on          = [google_service_networking_connection.private_services]
  settings {{
    tier              = var.db_tier
    edition           = "ENTERPRISE"
    availability_type = "REGIONAL"
    disk_autoresize   = true
    user_labels       = local.labels
    ip_configuration {{
      ipv4_enabled    = false
      private_network = google_compute_network.main.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }}
    backup_configuration {{
      enabled = true
{backup}    }}
  }}
}}

resource "google_sql_database" "main" {{
  name     = local.name
  instance = google_sql_database_instance.main.name
}}

resource "google_sql_user" "app" {{
  name     = "app"
  instance = google_sql_database_instance.main.name
  password = random_password.db.result
}}

# -- service: the generated application on Cloud Run -----------------------------------------------------------------
resource "google_service_account" "app" {{
  account_id   = "${{local.name}}-run"
  display_name = "The service ${{local.name}} on Cloud Run"
}}

resource "google_secret_manager_secret_iam_member" "app" {{
  secret_id = google_secret_manager_secret.db.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${{google_service_account.app.email}}"
}}

resource "google_project_iam_member" "sql_client" {{
  project = var.project
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${{google_service_account.app.email}}"
}}

resource "google_cloud_run_v2_service" "app" {{
  name                = local.name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = true
  template {{
    service_account = google_service_account.app.email
    scaling {{
      min_instance_count = {min_instances}
      max_instance_count = 3
    }}
    vpc_access {{
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {{
        network    = google_compute_network.main.id
        subnetwork = google_compute_subnetwork.app.id
      }}
    }}
    containers {{
      image = var.container_image
      ports {{
        container_port = 8080
      }}
      resources {{
        limits = {{
          cpu    = "1"
          memory = "1Gi"
        }}
      }}
      env {{
        name  = "DB_HOST"
        value = google_sql_database_instance.main.private_ip_address
      }}
      env {{
        name = "DB_PASSWORD"
        value_source {{
          secret_key_ref {{
            secret  = google_secret_manager_secret.db.secret_id
            version = "latest"
          }}
        }}
      }}
    }}
  }}
  depends_on = [google_secret_manager_secret_iam_member.app, google_secret_manager_secret_version.db]
}}
'''
    variables = """variable "project" {
  type        = string
  description = "The GCP project the infrastructure is created in"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "container_image" {
  type        = string
  description = "The image of the generated service, built and pushed by the pipeline of the customer"
}

variable "db_tier" {
  type    = string
  default = "db-custom-2-7680"
}
"""
    outputs = """output "url" {
  value = google_cloud_run_v2_service.app.uri
}

output "database_private_ip" {
  value = google_sql_database_instance.main.private_ip_address
}
"""
    return {"main.tf": main, "variables.tf": variables, "outputs.tf": outputs}
