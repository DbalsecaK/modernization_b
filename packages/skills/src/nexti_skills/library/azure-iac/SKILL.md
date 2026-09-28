---
name: azure-iac
description: "Terraform modules for AKS, Azure Database, Logic Apps and Key Vault."
metadata:
  title: "Azure IaC"
  version: 0.8.0
  type: target
  applies_to:
    agents: ["devops"]
    technologies: ["azure"]
  conflicts: []
  requires: []
  status: published
  eval_score: null
---
# Azure infrastructure as code

- Terraform / OpenTofu modules.
- Container Apps or AKS; Azure Database for PostgreSQL (flexible server) or Azure SQL; Key Vault; managed
  identities.
- VNet integration; Azure Monitor and Log Analytics.
- Legacy batch (JCL) → Logic Apps, Azure Batch or Container Apps jobs; MQ → Service Bus.
