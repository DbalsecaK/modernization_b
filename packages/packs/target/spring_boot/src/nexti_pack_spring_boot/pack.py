"""The Java Spring Boot pack behind the common backend pack contract (ADR-0017): what the orchestration needs to
generate and verify a target without naming the language. The texts sent to the agents are exactly those of M4, so
its recordings stay valid."""

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any

from nexti_core.spec.characterization import GoldenMaster, Scalar
from nexti_core.spec.equivalence import EquivalenceRun
from nexti_pack_spring_boot import mongodb, mysql, oracle
from nexti_pack_spring_boot.build import IMAGE, compile_and_test
from nexti_pack_spring_boot.canary import Mutation, mutations
from nexti_pack_spring_boot.design import Design, Port, UseCase
from nexti_pack_spring_boot.equivalence import run_equivalence
from nexti_pack_spring_boot.generate import (
    SPRING_BOOT_VERSION,
    SPRING_BOOT_VERSIONS,
    _path,
    adapter_path,
    junit_path,
    layer_of,
    service_path,
    skeleton,
)
from nexti_sandbox import Sandbox
from nexti_sandbox.build import BuildResult

SCHEMA = "src/main/resources/db/schema.sql"


class ReplyFormatError(ValueError):
    """The answer has no code block of the pack's language."""


def wiring(design: Design) -> tuple[str, str]:
    """The orchestration layer: one bean per use case service, built from the port beans (the adapters)."""
    package = f"{design.base_package}.config"
    beans = []
    for use_case in design.use_cases:
        params = ", ".join(f"{design.base_package}.domain.port.{p} {p[:1].lower() + p[1:]}" for p in use_case.ports)
        args = ", ".join(p[:1].lower() + p[1:] for p in use_case.ports)
        service = f"{design.base_package}.application.{use_case.name}Service"
        name = use_case.name[:1].lower() + use_case.name[1:] + "Service"
        beans.append(
            f"    @Bean\n    public {service} {name}({params}) {{\n        return new {service}({args});\n    }}"
        )
    path = f"src/main/java/{package.replace('.', '/')}/Wiring.java"
    body = "\n\n".join(beans)
    return path, (
        f"package {package};\n\nimport org.springframework.context.annotation.Bean;\n"
        "import org.springframework.context.annotation.Configuration;\n\n"
        "/** The application services as beans (the domain classes have no framework annotations). */\n"
        f"@Configuration\npublic class Wiring {{\n\n{body}\n}}\n"
    )


class SpringBootPack:
    name = "spring-boot"
    image = IMAGE
    developer_prompt = "backend-dev"
    tester_prompt = "test-engineer"
    spring_boot_version = SPRING_BOOT_VERSION

    def configured(self, target: Mapping[str, Any]) -> "SpringBootPack":
        """The pack with the Spring Boot version the project chose (ADR-0040), when the pack supports it."""
        chosen = SPRING_BOOT_VERSIONS.get(str(target.get("backend_version") or ""))
        if not chosen or chosen == self.spring_boot_version:
            return self
        pack = copy.copy(self)
        pack.spring_boot_version = chosen
        return pack

    def skeleton(self, design: Design) -> dict[str, str]:
        files = skeleton(design, self.spring_boot_version)
        path, content = wiring(design)
        files[path] = content
        return files

    def held_back(self, path: str) -> bool:
        """The REST controllers and the wiring use the services, so they join once every service exists."""
        return path.endswith("Controller.java") or path.endswith("/config/Wiring.java")

    def code_block(self, content: str) -> str:
        match = re.search(r"```(?:java)?\s*\n(.*?)```", content, re.DOTALL)
        code = (match.group(1) if match else content).strip()
        if "class " not in code and "interface " not in code:
            raise ReplyFormatError("the answer has no Java class in a ```java block")
        return code + "\n"

    def service_path(self, design: Design, use_case: UseCase) -> str:
        return service_path(design, use_case)

    def test_path(self, design: Design, use_case: UseCase) -> str:
        return junit_path(design, use_case)

    def adapter_path(self, design: Design, port: Port) -> str:
        return adapter_path(design, port)

    def adapter_name(self, port: str) -> str:
        return f"Jdbc{port}"

    def layer_of(self, path: str, design: Design) -> str:
        return layer_of(path, design)

    def existing(self, files: Mapping[str, str], design: Design) -> str:
        """The files the agents see: the domain and the REST contracts."""
        wanted = [p for p in files if "/domain/" in p or ("/adapters/in/rest/" in p and p.endswith(("Request.java",
                  "Response.java")))]  # fmt: skip
        return "\n\n".join(f"// {p}\n{files[p]}" for p in sorted(wanted))

    def probe(self, design: Design, path: str) -> dict[str, str]:
        """Java names a class by its file: the path already pins the package and the name."""
        return {}

    def adapter_request(self, design: Design, port: str, files: Mapping[str, str]) -> str:
        return (
            f"Write the JDBC adapter Jdbc{port} of the port {port}.\n\n"
            f"Design:\n{design.model_dump_json(indent=1)}\n\nExisting files:\n{self.existing(files, design)}\n\n"
            f"Target schema:\n{files[SCHEMA]}"
        )

    async def compile_and_test(
        self, sandbox: Sandbox, files: Mapping[str, str], *, run_tests: bool = True
    ) -> BuildResult:
        return await compile_and_test(sandbox, files, run_tests=run_tests)

    async def run_equivalence(
        self, sandbox: Sandbox, files: dict[str, str], design: Design, use_case: UseCase, master: GoldenMaster,
        defaults: dict[str, Scalar] | None = None,
    ) -> EquivalenceRun:  # fmt: skip
        return await run_equivalence(sandbox, files, design, use_case, master, defaults)

    def mutations(self, source: str) -> Sequence[Mutation]:
        return mutations(source)

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "image": self.image}


class SpringBootOraclePack(SpringBootPack):
    """The same pack with Oracle as its persistence (ADR-0021): the Oracle schema, the adapters asked for Oracle SQL,
    the Oracle JDBC driver in the project and the golden master run against Oracle in its sandbox."""

    image = oracle.IMAGE
    database = "oracle"

    def skeleton(self, design: Design) -> dict[str, str]:
        files = super().skeleton(design)
        files[SCHEMA] = oracle.schema(design)
        files["pom.xml"] = files["pom.xml"].replace(
            "<dependency><groupId>org.postgresql</groupId><artifactId>postgresql</artifactId><scope>runtime</scope>"
            "</dependency>",
            "<dependency><groupId>com.oracle.database.jdbc</groupId><artifactId>ojdbc11</artifactId>"
            "<scope>runtime</scope></dependency>",
        )
        return files

    def adapter_request(self, design: Design, port: str, files: Mapping[str, str]) -> str:
        return (
            f"Write the JDBC adapter Jdbc{port} of the port {port}. The database is Oracle Database 23ai: use "
            "Oracle SQL (no LIMIT: FETCH FIRST n ROWS ONLY; no RETURNING into the JdbcTemplate; booleans are BOOLEAN). "
            "Write the identifiers exactly as the schema does: a column the schema quotes (a reserved word, e.g. "
            '"NUMBER") is quoted the same way in every statement.\n\n'
            f"Design:\n{design.model_dump_json(indent=1)}\n\nExisting files:\n{self.existing(files, design)}\n\n"
            f"Target schema (Oracle):\n{files[SCHEMA]}"
        )

    async def run_equivalence(
        self, sandbox: Sandbox, files: dict[str, str], design: Design, use_case: UseCase, master: GoldenMaster,
        defaults: dict[str, Scalar] | None = None,
    ) -> EquivalenceRun:  # fmt: skip
        return await oracle.run_equivalence(sandbox, files, design, use_case, master, defaults)

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "image": self.image, "database": self.database}


class SpringBootMySqlPack(SpringBootPack):
    """The same pack with MySQL as its persistence (ADR-0027): the MySQL schema, the adapters asked for MySQL SQL,
    MySQL Connector/J in the project and the golden master run against MySQL in its sandbox."""

    image = mysql.IMAGE
    database = "mysql"

    def skeleton(self, design: Design) -> dict[str, str]:
        files = super().skeleton(design)
        files[SCHEMA] = mysql.schema(design)
        files["pom.xml"] = files["pom.xml"].replace(
            "<dependency><groupId>org.postgresql</groupId><artifactId>postgresql</artifactId><scope>runtime</scope>"
            "</dependency>",
            "<dependency><groupId>com.mysql</groupId><artifactId>mysql-connector-j</artifactId>"
            "<scope>runtime</scope></dependency>",
        )
        return files

    def adapter_request(self, design: Design, port: str, files: Mapping[str, str]) -> str:
        return (
            f"Write the JDBC adapter Jdbc{port} of the port {port}. The database is MySQL 8.4 with a strict sql_mode: "
            "use MySQL SQL (LIMIT n; no RETURNING; booleans are BOOLEAN, i.e. TINYINT(1); timestamps are DATETIME(3) "
            "in UTC). Write the identifiers exactly as the schema does: a name the schema quotes with backticks (a "
            "reserved word, e.g. `condition`) is quoted the same way in every statement.\n\n"
            f"Design:\n{design.model_dump_json(indent=1)}\n\nExisting files:\n{self.existing(files, design)}\n\n"
            f"Target schema (MySQL):\n{files[SCHEMA]}"
        )

    async def run_equivalence(
        self, sandbox: Sandbox, files: dict[str, str], design: Design, use_case: UseCase, master: GoldenMaster,
        defaults: dict[str, Scalar] | None = None,
    ) -> EquivalenceRun:  # fmt: skip
        return await mysql.run_equivalence(sandbox, files, design, use_case, master, defaults)

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "image": self.image, "database": self.database}


class SpringBootMongoDbPack(SpringBootPack):
    """The same pack with MongoDB as its persistence (ADR-0029): the aggregate model of the design as collections
    (`nexti_pack_spring_boot.mongodb`), the adapters asked for the official MongoDB Java sync driver, the driver in the
    project instead of Spring JDBC and PostgreSQL, and the golden master compared by collection against MongoDB in its
    sandbox. The adapters are `Mongo<Port>` in `<base>.adapters.out.mongodb`, next to the platform's
    MongoTransaction."""

    image = mongodb.IMAGE
    database = "mongodb"

    def skeleton(self, design: Design) -> dict[str, str]:
        files = super().skeleton(design)
        del files[SCHEMA]
        files[mongodb.COLLECTIONS] = mongodb.collections_script(design)
        files.update([mongodb.transaction_file(design), mongodb.config_file(design)])
        files["pom.xml"] = files["pom.xml"].replace(
            "<dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-jdbc</artifactId>"
            "</dependency>\n    <dependency><groupId>org.postgresql</groupId><artifactId>postgresql</artifactId>"
            "<scope>runtime</scope></dependency>",
            "<dependency><groupId>org.mongodb</groupId><artifactId>mongodb-driver-sync</artifactId></dependency>",
        )
        return files

    def adapter_path(self, design: Design, port: Port) -> str:
        return _path(f"{design.base_package}.adapters.out.mongodb", f"Mongo{port.name}")

    def adapter_name(self, port: str) -> str:
        return f"Mongo{port}"

    def layer_of(self, path: str, design: Design) -> str:
        return "adapters" if path == mongodb.COLLECTIONS else layer_of(path, design)

    def adapter_request(self, design: Design, port: str, files: Mapping[str, str]) -> str:
        transaction = mongodb.transaction_file(design)
        return (
            f"Write the MongoDB adapter Mongo{port} of the port {port}, in the package "
            f"{design.base_package}.adapters.out.mongodb, with the official MongoDB Java sync driver "
            "(com.mongodb.client; no Spring Data, no JDBC): a class annotated "
            "@org.springframework.stereotype.Repository with one public constructor that takes a "
            "com.mongodb.client.MongoDatabase and keeps the MongoCollection<org.bson.Document> of each collection it "
            "uses, by name. Each entity is a collection (the aggregate model is in the header of the collections "
            "script): a document keeps the entity's fields under their column names exactly as the script writes them, "
            "and nothing else but MongoDB's own _id, which the adapter never sets nor reads. Find a document by its "
            "key fields with com.mongodb.client.model.Filters (eq, and) and first(); update with "
            "com.mongodb.client.model.Updates (set, combine) and return getMatchedCount() as the rows updated. Pass "
            "MongoTransaction.current() to every driver call: when it is present, call the overload that takes the "
            "ClientSession (find(session, filter), updateOne(session, filter, update), insertOne(session, document), "
            "...) so the call joins the transaction of the use case. Types, which the collections validate: decimals "
            "as org.bson.types.Decimal128 at the scale of their type (new Decimal128(value.setScale(scale, "
            "RoundingMode.HALF_UP)), read with document.get(field, Decimal128.class).bigDecimalValue()), never double; "
            "32-bit integers as Integer and 64-bit ones as Long; timestamps and dates as java.util.Date in UTC "
            "(Date.from(value.toInstant(ZoneOffset.UTC)), read back with toInstant().atOffset(ZoneOffset.UTC)); "
            "booleans as Boolean; a missing or null field is null.\n\n"
            f"Design:\n{design.model_dump_json(indent=1)}\n\nExisting files:\n{self.existing(files, design)}\n\n"
            f"// {transaction[0]}\n{transaction[1]}\n"
            f"Target collections (MongoDB 8.0, mongosh):\n{files[mongodb.COLLECTIONS]}"
        )

    async def run_equivalence(
        self, sandbox: Sandbox, files: dict[str, str], design: Design, use_case: UseCase, master: GoldenMaster,
        defaults: dict[str, Scalar] | None = None,
    ) -> EquivalenceRun:  # fmt: skip
        return await mongodb.run_equivalence(sandbox, files, design, use_case, master, defaults)

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "image": self.image, "database": self.database}


PACK = SpringBootPack()
ORACLE_PACK = SpringBootOraclePack()
MYSQL_PACK = SpringBootMySqlPack()
MONGODB_PACK = SpringBootMongoDbPack()
