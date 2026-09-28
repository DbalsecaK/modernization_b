---
name: quarkus
description: "Quarkus layout, Panache persistence and native build settings."
metadata:
  title: "Quarkus services"
  version: 1.0.0
  type: target
  applies_to:
    agents: ["backend-dev", "fullstack-dev", "code-reviewer"]
    technologies: ["quarkus"]
  conflicts: ["spring-hexagonal"]
  requires: []
  status: published
  eval_score: 0.86
---
# Quarkus

- CDI beans (`@ApplicationScoped`) and RESTEasy Reactive endpoints.
- Panache with the repository pattern, so the domain stays free of the framework.
- Configuration in `application.properties` read with `@ConfigProperty` or config mappings.
- Native builds need reflection registration for anything accessed reflectively.
- Tests with `@QuarkusTest` and Testcontainers (dev services).
