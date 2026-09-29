---
name: aws-iac
description: "Terraform modules for ECS/EKS, RDS, Step Functions and KMS."
metadata:
  title: "AWS IaC"
  version: 0.9.0
  type: target
  applies_to:
    agents: ["devops"]
    technologies: ["aws"]
  conflicts: []
  requires: []
  status: published
  eval_score: null
---
# AWS infrastructure as code

- Terraform / OpenTofu modules.
- Containers on ECS Fargate or EKS; RDS for PostgreSQL; Secrets Manager for credentials.
- Least-privilege IAM per service; private subnets; CloudWatch logs and alarms.
- Legacy batch (JCL) → Step Functions with AWS Batch; MQ → SQS / SNS or Amazon MQ.
