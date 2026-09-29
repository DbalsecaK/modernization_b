---
name: spring-hexagonal
description: "Ports and adapters layout, conventions and test setup for Spring Boot."
metadata:
  title: "Spring Boot hexagonal"
  version: 2.0.0
  type: target
  applies_to:
    agents: ["backend-dev", "fullstack-dev", "code-reviewer"]
    technologies: ["spring-boot"]
  conflicts: ["quarkus"]
  requires: []
  status: published
  eval_score: 0.93
---
# Spring Boot hexagonal

- The domain module has no framework dependencies.
- Ports are interfaces owned by the domain / application layer; adapters (REST controllers, JPA repositories,
  messaging) live in infrastructure.
- Constructor injection only; DTOs at the edge, never entities in the API.
- Transactions at the application service level.
- Tests: domain unit tests, slice tests for adapters (`@WebMvcTest`, `@DataJpaTest` with Testcontainers) and
  contract tests from the OpenAPI document.
