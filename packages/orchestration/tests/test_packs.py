"""The backend pack of a project (ADR-0017): chosen by `target.backend`, with the Spring Boot variant of its database
when there is one (Oracle, ADR-0021; MySQL, ADR-0027); Quarkus (ADR-0028) and Go (ADR-0029) with PostgreSQL."""

from typing import Any

from nexti_orchestration.packs import backend_pack


def image(target: dict[str, Any]) -> str | None:
    pack = backend_pack(target)
    return pack.image if pack else None


def test_spring_boot_takes_the_variant_of_its_database() -> None:
    assert image({}) == "nexti-sandbox-java:2"
    assert image({"backend": "spring-boot", "database": "postgresql"}) == "nexti-sandbox-java:2"
    assert image({"backend": "spring-boot", "database": "Oracle"}) == "nexti-sandbox-java-oracle:1"
    assert image({"backend": "spring-boot", "database": "MySQL"}) == "nexti-sandbox-java-mysql:1"


def test_quarkus_is_the_java_pack_with_quarkus_edges_on_postgresql() -> None:
    assert image({"backend": "quarkus"}) == "nexti-sandbox-java-quarkus:1"
    assert image({"backend": "quarkus", "database": "PostgreSQL"}) == "nexti-sandbox-java-quarkus:1"
    pack = backend_pack({"backend": "quarkus", "database": "postgresql"})
    assert pack is not None
    assert (pack.name, pack.developer_prompt, pack.tester_prompt) == ("quarkus", "backend-dev-quarkus", "test-engineer")
    assert image({"backend": "quarkus", "database": "mysql"}) is None
    assert image({"backend": "quarkus", "database": "oracle"}) is None


def test_spring_boot_with_mongodb_takes_its_variant() -> None:
    assert image({"backend": "spring-boot", "database": "MongoDB"}) == "nexti-sandbox-java-mongodb:1"
    pack = backend_pack({"backend": "spring-boot", "database": "mongodb"})
    assert pack is not None
    assert pack.adapter_name("AccountRepository") == "MongoAccountRepository"
    assert image({"backend": "quarkus", "database": "mongodb"}) is None


def test_go_is_its_own_pack_on_postgresql() -> None:
    assert image({"backend": "go"}) == "nexti-sandbox-go:1"
    assert image({"backend": "go", "database": "PostgreSQL"}) == "nexti-sandbox-go:1"
    pack = backend_pack({"backend": "go", "database": "postgresql"})
    assert pack is not None
    assert (pack.name, pack.developer_prompt, pack.tester_prompt) == ("go", "backend-dev-go", "test-engineer-go")
    assert image({"backend": "go", "database": "sqlserver"}) is None
    assert image({"backend": "go", "database": "mongodb"}) is None


def test_dotnet_takes_its_oracle_variant() -> None:
    assert image({"backend": "dotnet-10"}) == "nexti-sandbox-dotnet:1"
    assert image({"backend": "dotnet-10", "database": "sqlserver"}) == "nexti-sandbox-dotnet:1"
    assert image({"backend": "dotnet-10", "database": "Oracle"}) == "nexti-sandbox-dotnet-oracle:1"
    pack = backend_pack({"backend": "dotnet-10", "database": "oracle"})
    assert pack is not None
    assert (pack.name, pack.adapter_name("AccountRepository")) == ("dotnet-10", "SqlAccountRepository")
