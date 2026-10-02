"""The backend pack of a project (ADR-0017): chosen by `target.backend`, with the Spring Boot variant of its database
when there is one (Oracle, ADR-0021; MySQL, ADR-0027); Quarkus (ADR-0028) with PostgreSQL."""

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
    assert image({"backend": "go"}) is None


def test_quarkus_is_the_java_pack_with_quarkus_edges_on_postgresql() -> None:
    assert image({"backend": "quarkus"}) == "nexti-sandbox-java-quarkus:1"
    assert image({"backend": "quarkus", "database": "PostgreSQL"}) == "nexti-sandbox-java-quarkus:1"
    pack = backend_pack({"backend": "quarkus", "database": "postgresql"})
    assert pack is not None
    assert (pack.name, pack.developer_prompt, pack.tester_prompt) == ("quarkus", "backend-dev-quarkus", "test-engineer")
    assert image({"backend": "quarkus", "database": "mysql"}) is None
    assert image({"backend": "quarkus", "database": "oracle"}) is None
