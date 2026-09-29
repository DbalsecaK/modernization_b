---
name: dotnet10
description: "Minimal APIs, EF Core and hexagonal layout for .NET 10."
metadata:
  title: ".NET 10 minimal APIs"
  version: 1.1.0
  type: target
  applies_to:
    agents: ["backend-dev", "fullstack-dev", "code-reviewer"]
    technologies: ["dotnet-10"]
  conflicts: []
  requires: []
  status: published
  eval_score: 0.9
---
# .NET 10 minimal APIs

- Endpoints grouped with `MapGroup`, typed results and problem details for errors.
- Dependency injection with `IServiceCollection` and the options pattern for configuration.
- A domain project without infrastructure references; EF Core with migrations in infrastructure.
- Nullable reference types enabled.
- xUnit tests; `WebApplicationFactory` for integration tests.
