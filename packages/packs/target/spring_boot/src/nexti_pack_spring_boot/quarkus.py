"""Quarkus as the second framework of the Java pack (spec 8.4, 8.5, ADR-0028). The domain, the ports, the use cases
and the application services are those of Spring Boot: the same generators, the same agent prompts for the services
and their tests, the same oracle tests and the same golden master. Only the edges change:

    <base>/adapters/in/rest    JAX-RS resources (jakarta.ws.rs) instead of @RestController
    <base>/adapters/out/jdbc   JDBC adapters over javax.sql.DataSource (Agroal) instead of JdbcTemplate
    <base>/config/Wiring       CDI producers (@Produces @Singleton) instead of Spring @Bean methods
    pom.xml                    the Quarkus BOM with quarkus-rest-jackson, quarkus-agroal, quarkus-jdbc-postgresql
                               and quarkus-arc; application.properties with the datasource

The sandbox (`nexti-sandbox-java-quarkus`) compiles with javac and tests with the JUnit console like Spring Boot's;
the equivalence harness calls the application service by reflection, with plain JDBC instead of Spring JDBC."""

from collections.abc import Mapping
from typing import Any

from nexti_core.spec.characterization import GoldenMaster, Scalar
from nexti_core.spec.equivalence import EquivalenceRun
from nexti_pack_spring_boot.design import Design, UseCase
from nexti_pack_spring_boot.equivalence import harness_source, run_equivalence
from nexti_pack_spring_boot.generate import _pascal, _path, _snake, java_type
from nexti_pack_spring_boot.generate import skeleton as core_skeleton
from nexti_pack_spring_boot.pack import SCHEMA, SpringBootPack
from nexti_sandbox import Sandbox

IMAGE = "nexti-sandbox-java-quarkus:1"
QUARKUS_VERSION = "3.40.1"  # the 3.40 LTS stream
NAME = "quarkus"
PROPERTIES = "src/main/resources/application.properties"
_BODY_METHODS = ("POST", "PUT", "PATCH")


def _camel(name: str) -> str:
    return name[:1].lower() + name[1:]


def resource_file(design: Design, use_case: UseCase) -> tuple[str, str]:
    """The JAX-RS resource of a use case: the request record as the JSON body, or built from the query parameters for
    a method without a body (GET, DELETE)."""
    package = f"{design.base_package}.adapters.in.rest"
    service = f"{design.base_package}.application.{use_case.name}Service"
    path = use_case.path or "/" + _snake(use_case.name).replace("_", "-")
    method = use_case.http_method
    if method in _BODY_METHODS:
        params = f"{use_case.name}Request request"
        argument = "request"
    else:
        params = ", ".join(f'@QueryParam("{f.name}") {java_type(f.type)} {f.name}' for f in use_case.inputs)
        argument = f"new {use_case.name}Request({', '.join(f.name for f in use_case.inputs)})"
    imports = ["jakarta.inject.Inject", "jakarta.ws.rs.Consumes", f"jakarta.ws.rs.{method}", "jakarta.ws.rs.Path",
               "jakarta.ws.rs.Produces", "jakarta.ws.rs.core.MediaType"]  # fmt: skip
    if method not in _BODY_METHODS and use_case.inputs:
        imports.append("jakarta.ws.rs.QueryParam")
    lines = "".join(f"import {i};\n" for i in sorted(imports))
    return _path(package, f"{use_case.name}Resource"), (
        f"package {package};\n\n{lines}\n"
        f"/** REST resource of {use_case.name} (rules {', '.join(use_case.rules)}). */\n"
        f'@Path("/api/{design.context}")\n@Produces(MediaType.APPLICATION_JSON)\n'
        f"@Consumes(MediaType.APPLICATION_JSON)\n"
        f"public class {use_case.name}Resource {{\n\n"
        f"    private final {service} service;\n\n"
        f"    @Inject\n"
        f"    public {use_case.name}Resource({service} service) {{\n        this.service = service;\n    }}\n\n"
        f'    @{method}\n    @Path("{path}")\n'
        f"    public {use_case.name}Response handle({params}) {{\n"
        f"        return service.execute({argument});\n    }}\n}}\n"
    )


def wiring(design: Design) -> tuple[str, str]:
    """The orchestration layer: one CDI producer per use case service, built from the port beans (the adapters)."""
    package = f"{design.base_package}.config"
    producers = []
    for use_case in design.use_cases:
        params = ", ".join(f"{design.base_package}.domain.port.{p} {_camel(p)}" for p in use_case.ports)
        args = ", ".join(_camel(p) for p in use_case.ports)
        service = f"{design.base_package}.application.{use_case.name}Service"
        producers.append(
            f"    @Produces\n    @Singleton\n    public {service} {_camel(use_case.name)}Service({params}) {{\n"
            f"        return new {service}({args});\n    }}"
        )
    body = "\n\n".join(producers)
    return _path(package, "Wiring"), (
        f"package {package};\n\nimport jakarta.enterprise.context.ApplicationScoped;\n"
        "import jakarta.enterprise.inject.Produces;\nimport jakarta.inject.Singleton;\n\n"
        "/** The application services as CDI beans (the domain classes have no framework annotations). */\n"
        f"@ApplicationScoped\npublic class Wiring {{\n\n{body}\n}}\n"
    )


def pom_file(design: Design) -> tuple[str, str]:
    artifact = design.context.replace("_", "-")
    return (
        "pom.xml",
        f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>{design.base_package.rsplit(".", 1)[0]}</groupId>
  <artifactId>{artifact}</artifactId>
  <version>0.1.0</version>
  <properties>
    <maven.compiler.release>21</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    <quarkus.platform.version>{QUARKUS_VERSION}</quarkus.platform.version>
  </properties>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>io.quarkus.platform</groupId><artifactId>quarkus-bom</artifactId>
        <version>${{quarkus.platform.version}}</version><type>pom</type><scope>import</scope>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency><groupId>io.quarkus</groupId><artifactId>quarkus-rest-jackson</artifactId></dependency>
    <dependency><groupId>io.quarkus</groupId><artifactId>quarkus-agroal</artifactId></dependency>
    <dependency><groupId>io.quarkus</groupId><artifactId>quarkus-jdbc-postgresql</artifactId></dependency>
    <dependency><groupId>io.quarkus</groupId><artifactId>quarkus-arc</artifactId></dependency>
    <dependency><groupId>io.quarkus</groupId><artifactId>quarkus-junit5</artifactId><scope>test</scope></dependency>
    <dependency><groupId>org.assertj</groupId><artifactId>assertj-core</artifactId><version>3.27.4</version><scope>test</scope></dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>io.quarkus.platform</groupId><artifactId>quarkus-maven-plugin</artifactId>
        <version>${{quarkus.platform.version}}</version><extensions>true</extensions>
        <executions><execution><goals><goal>build</goal><goal>generate-code</goal><goal>generate-code-tests</goal></goals></execution></executions>
      </plugin>
    </plugins>
  </build>
</project>
""",
    )


def properties_file(design: Design) -> tuple[str, str]:
    """The datasource of the schema, from the environment (no credentials in the project)."""
    return PROPERTIES, (
        "# The Agroal datasource of the PostgreSQL schema in db/schema.sql, configured by the environment.\n"
        "quarkus.datasource.db-kind=postgresql\n"
        f"quarkus.datasource.jdbc.url=${{DB_URL:jdbc:postgresql://localhost:5432/{design.context}}}\n"
        f"quarkus.datasource.username=${{DB_USER:{design.context}}}\n"
        "quarkus.datasource.password=${DB_PASSWORD}\n"
    )


def skeleton(design: Design) -> dict[str, str]:
    """The Spring Boot skeleton's contracts, domain and schema, with the Quarkus edges: resources, wiring and build."""
    application = _path(design.base_package, _pascal(design.context) + "Application")
    files = {p: c for p, c in core_skeleton(design).items() if not p.endswith("Controller.java") and p != application}
    files.update([pom_file(design), properties_file(design), wiring(design)])
    for use_case in design.use_cases:
        files.update([resource_file(design, use_case)])
    return files


class QuarkusPack(SpringBootPack):
    """The Java pack with Quarkus at the edges (ADR-0028). The services and their tests are asked with the same
    tester prompt as Spring Boot; the developer prompt has the Quarkus adapters (DataSource-based JDBC)."""

    name = NAME
    image = IMAGE
    framework = "quarkus"
    developer_prompt = "backend-dev-quarkus"
    tester_prompt = "test-engineer"

    def skeleton(self, design: Design) -> dict[str, str]:
        return skeleton(design)

    def held_back(self, path: str) -> bool:
        """The JAX-RS resources and the CDI wiring use the services, so they join once every service exists."""
        return path.endswith("Resource.java") or path.endswith("/config/Wiring.java")

    def adapter_request(self, design: Design, port: str, files: Mapping[str, str]) -> str:
        return (
            f"Write the JDBC adapter Jdbc{port} of the port {port} for Quarkus: a class annotated "
            "@jakarta.enterprise.context.ApplicationScoped with one public constructor annotated "
            "@jakarta.inject.Inject that takes a javax.sql.DataSource (the Agroal datasource). Plain JDBC, no "
            "JdbcTemplate and no Spring: each method opens a connection with dataSource.getConnection() and a "
            "PreparedStatement with ? parameters in try-with-resources, sets nulls with setNull or setObject, maps the "
            "ResultSet to the domain records and wraps a java.sql.SQLException in an unchecked exception.\n\n"
            f"Design:\n{design.model_dump_json(indent=1)}\n\nExisting files:\n{self.existing(files, design)}\n\n"
            f"Target schema:\n{files[SCHEMA]}"
        )

    async def run_equivalence(
        self, sandbox: Sandbox, files: dict[str, str], design: Design, use_case: UseCase, master: GoldenMaster,
        defaults: dict[str, Scalar] | None = None,
    ) -> EquivalenceRun:  # fmt: skip
        return await run_equivalence(sandbox, files, design, use_case, master, defaults, harness_source("quarkus"))

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "image": self.image, "framework": self.framework}


QUARKUS_PACK = QuarkusPack()
