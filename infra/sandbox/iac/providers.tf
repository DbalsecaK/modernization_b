# The providers the deployment pack generates for (ADR-0021), mirrored into the image at build time: the sandbox
# validates the IaC without network.
terraform {
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.0" }
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
  }
}
