---
name: quarkus
description: "Quarkus edges of the hexagonal Java pack: JAX-RS resources, JDBC over the Agroal DataSource and CDI wiring."
metadata:
  title: "Quarkus services"
  version: 1.1.0
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

- The domain, the ports and the application services have no framework dependencies (the same core as Spring Boot).
- REST adapters are JAX-RS resources (`jakarta.ws.rs`, Quarkus REST with Jackson); request and response records
  at the edge, never entities in the API.
- Persistence adapters use plain JDBC over the injected `javax.sql.DataSource` (Agroal), one connection per call in
  try-with-resources; no Panache, so the domain stays free of the framework.
- CDI wiring: adapters are `@ApplicationScoped` with constructor injection; the services come from `@Produces`
  methods.
- Configuration in `application.properties`, credentials from the environment.
- Domain tests are plain JUnit 5 with AssertJ and in-memory fakes of the ports (no `@QuarkusTest`).
