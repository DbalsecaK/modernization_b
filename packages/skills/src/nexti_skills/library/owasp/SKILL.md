---
name: owasp
description: "Input validation, authZ checks, secrets handling and dependency hygiene."
metadata:
  title: "OWASP secure coding"
  version: 1.5.0
  type: crossCutting
  applies_to:
    agents: ["backend-dev", "frontend-dev", "fullstack-dev", "security-auditor", "code-reviewer"]
    technologies: []
  conflicts: []
  requires: []
  status: published
  eval_score: 0.9
---
# OWASP secure coding

- Validate input at the edge with allow-lists; parameterized queries only; encode output.
- Authentication and authorization on every endpoint.
- No secrets in code or logs; error messages without internals.
- Security headers; dependency scanning; follow OWASP ASVS level 2.
