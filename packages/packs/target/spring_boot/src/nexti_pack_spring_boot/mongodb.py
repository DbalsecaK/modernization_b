"""MongoDB as the persistence of the Spring Boot pack (spec 8.4, 8.5, ADR-0029): the aggregate model, the neutral types
in BSON, the collections, and the golden master compared by collection against a throwaway `mongod` inside the sandbox
(`nexti-sandbox-java-mongodb`). The adapters use the official MongoDB Java sync driver, never Spring Data or JDBC.

Aggregate modelling, decided by code from the design (8.5: what is embedded and what is referenced):

    - each entity of the design with a target table is a collection named like that table (an aggregate root), and
      each of its documents keeps the entity's fields under their column names, plus MongoDB's own `_id`;
    - an entity is embedded in another only when the design marks it as part of that other one. The design model has
      no such marker yet, so the rule is deterministic: nothing is embedded;
    - an entity refers to another by the other's key: when its fields include every key field of another entity (same
      name and neutral type) it keeps those fields as the reference (no DBRef, no copy of the other document);
    - the key of an entity is a unique index of its collection, and a $jsonSchema validator holds the BSON types.

`aggregate_decision` writes that model as a design decision, and the skeleton carries it in the header of the
collections script (`src/main/resources/db/collections.js`), which replaces the SQL schema.

Types (the same in the adapters, the collections and the harness): decimals are Decimal128 at the scale of their type,
integers Int32 or Int64 as their Java type, text and enums strings, dates and timestamps BSON dates in UTC (a date at
midnight UTC), booleans booleans, binaries BinData.

Equivalence: one legacy table is one collection and one row one document. The legacy rows of each case are translated
into documents (MongoDB Extended JSON) that the harness inserts; after the use case the harness prints every
collection as Extended JSON and `row` turns each document back into a row whose fields are the columns, in the same
canonical texts as the other databases (decimals at their scale, ISO timestamps). Transactions need a replica set, so
the sandbox starts `mongod` as a single-node replica set on loopback with its data in /work: the default hardening of
the sandbox holds (no network, read-only root, user nobody), none of the exceptions of ADR-0021."""

import base64
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from nexti_core.spec import neutral_types as nt
from nexti_core.spec.characterization import GoldenMaster, Observation, Scalar, canonical
from nexti_core.spec.equivalence import (
    CaseRun,
    EquivalenceRun,
    actual_view,
    column_of,
    entities_by_legacy,
    expected_view,
    masks,
)
from nexti_core.spec.equivalence import target_case as neutral_target_case
from nexti_pack_spring_boot.build import compile_and_test
from nexti_pack_spring_boot.design import Decision, Design, Entity, UseCase
from nexti_pack_spring_boot.equivalence import harness_source
from nexti_pack_spring_boot.generate import _path
from nexti_sandbox import Limits, Sandbox

IMAGE = "nexti-sandbox-java-mongodb:1"
COLLECTIONS = "src/main/resources/db/collections.js"
# The default hardening of the sandbox (no network, read-only root, user nobody): mongod listens on loopback and keeps
# its data in /work. More memory and /work than the base image: the JVM and mongod run side by side.
MONGODB_LIMITS = Limits(cpus=2.0, memory_mb=2048, pids=512, timeout_seconds=900, work_mb=768,
                        max_output_bytes=2 * 1024 * 1024)  # fmt: skip
REPLICA_SET, HOST, DATABASE = "rs0", "127.0.0.1:27017", "nexti"
INIT_URI = f"mongodb://{HOST}/?directConnection=true"  # before the replica set exists
URI = f"mongodb://{HOST}/?replicaSet={REPLICA_SET}&serverSelectionTimeoutMS=30000"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MILLISECOND = timedelta(milliseconds=1)


@dataclass(frozen=True)
class Aggregate:
    """An entity as MongoDB keeps it: its collection, the key fields (columns) of its unique index, the entities
    embedded in its documents and the references by key to other collections."""

    entity: str
    collection: str
    key: tuple[str, ...]
    embedded: tuple[str, ...] = ()
    references: tuple[tuple[tuple[str, ...], str], ...] = ()  # (columns, referenced collection)


def bson_type(neutral: str) -> str:
    """The BSON type ($jsonSchema bsonType alias) of a neutral type."""
    value = nt.parse(neutral)
    if isinstance(value, nt.Decimal):
        return "decimal"
    if isinstance(value, nt.Integer):
        return "long" if value.bits == 64 or (value.bits == 32 and not value.signed) else "int"
    if isinstance(value, nt.Text | nt.Enum):
        return "string"
    if isinstance(value, nt.Date | nt.Timestamp):
        return "date"
    if isinstance(value, nt.Boolean):
        return "bool"
    return "binData"


def _columns(entity: Entity) -> dict[str, str]:
    return {f.name: column_of(f.name, f.column) for f in entity.fields}


def aggregates(design: Design) -> list[Aggregate]:
    """The aggregate model of the design (see the module docstring): one collection per entity with a table, nothing
    embedded, references by key."""
    persisted = [e for e in design.entities if e.table]
    found = []
    for entity in persisted:
        types = {f.name: f.type for f in entity.fields}
        references = []
        for other in persisted:
            if other is entity or not other.key or list(other.key) == list(entity.key):
                continue
            other_types = {f.name: f.type for f in other.fields}
            if all(types.get(k) == other_types[k] for k in other.key):
                references.append((tuple(_columns(entity)[k] for k in other.key), other.table or ""))
        found.append(Aggregate(entity.name, entity.table or "", tuple(_columns(entity)[k] for k in entity.key),
                               references=tuple(references)))  # fmt: skip
    return found


def aggregate_decision(design: Design) -> Decision:
    """The aggregate model as a design decision (ADR-0029: the design records it)."""
    lines = []
    for aggregate in aggregates(design):
        refs = "; ".join(f"refers to {c} by {', '.join(k)}" for k, c in aggregate.references)
        key = f"unique key ({', '.join(aggregate.key)})" if aggregate.key else "no key"
        lines.append(f"{aggregate.entity} is the collection {aggregate.collection}, {key}" + (f"; {refs}" if refs
                                                                                               else ""))  # fmt: skip
    return Decision(
        title="MongoDB aggregates: one collection per entity, references by key",
        context="MongoDB needs an aggregate model: what is embedded and what is referenced (spec 8.5, ADR-0029).",
        decision="Each entity is a collection whose documents keep its fields under their column names. The design "
        "marks no entity as part of another, so none is embedded; an entity refers to another by the other's key "
        "fields. " + ". ".join(lines) + ".",
        consequences="One legacy table is one collection and one row one document: the golden master compares "
        "collection by collection. A use case spanning collections runs in a multi-document transaction.",
    )


def validator(entity: Entity) -> dict[str, Any]:
    """The $jsonSchema of an entity's collection: the BSON type of each field (null allowed but in the key), the
    length of bounded text and the values of an enum."""
    properties: dict[str, Any] = {}
    key = {column_of(k, next(f.column for f in entity.fields if f.name == k)) for k in entity.key}
    for field in entity.fields:
        column = column_of(field.name, field.column)
        kind = bson_type(field.type)
        spec: dict[str, Any] = {"bsonType": kind if column in key else [kind, "null"]}
        value = nt.parse(field.type)
        if isinstance(value, nt.Text) and value.length is not None:
            spec["maxLength"] = value.length
        if isinstance(value, nt.Enum):
            spec["enum"] = [*value.values, *([] if column in key else [None])]
        properties[column] = spec
    schema: dict[str, Any] = {"bsonType": "object", "properties": properties}
    if key:
        schema["required"] = sorted(key)
    return {"$jsonSchema": schema}


def collections(design: Design) -> list[dict[str, Any]]:
    """The collections of the design: name, key (columns of the unique index) and validator."""
    by_name = {e.name: e for e in design.entities}
    return [{"name": a.collection, "key": list(a.key), "validator": validator(by_name[a.entity])}
            for a in aggregates(design)]  # fmt: skip


def collections_script(design: Design) -> str:
    """The mongosh script that creates the collections, their validators and the unique indexes of their keys; its
    header is the aggregate model. It replaces the SQL schema of the other databases."""
    decision = aggregate_decision(design)
    lines = [
        f"// MongoDB collections of the {design.context} context (ADR-0029), generated from the design. Run with",
        "// mongosh against the application's database before the service starts.",
        f"// {decision.title}.",
        *[f"// - {part.strip()}." for part in decision.decision.removesuffix(".").split(". ") if part.strip()],
        "",
    ]
    for collection in collections(design):
        name = collection["name"]
        lines.append(f'db.createCollection("{name}", {{validator: {json.dumps(collection["validator"])}, '
                     'validationLevel: "strict", validationAction: "error"});')  # fmt: skip
        if collection["key"]:
            keys = ", ".join(f'"{k}": 1' for k in collection["key"])
            lines.append(f'db.getCollection("{name}").createIndex({{{keys}}}, {{unique: true, name: "{name}_key"}});')
    return "\n".join(lines) + "\n"


def _millis(moment: datetime) -> str:
    return str((moment - _EPOCH) // _MILLISECOND)


def _moment(text: str) -> datetime:
    moment = datetime.fromisoformat(text.strip().replace(" ", "T"))
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def bson_value(neutral: str, text: str | None) -> Any:
    """A canonical value as MongoDB Extended JSON (canonical mode) of its BSON type."""
    if text is None:
        return None
    value = nt.parse(neutral)
    kind = bson_type(neutral)
    if kind == "decimal":
        return {"$numberDecimal": text}
    if kind == "int":
        return {"$numberInt": text}
    if kind == "long":
        return {"$numberLong": text}
    if kind == "bool":
        return text == "true"
    if isinstance(value, nt.Date):
        return {"$date": {"$numberLong": _millis(datetime.combine(date.fromisoformat(text[:10]), time(), UTC))}}
    if isinstance(value, nt.Timestamp):
        return {"$date": {"$numberLong": _millis(_moment(text))}}
    if kind == "binData":
        return {"$binary": {"base64": base64.b64encode(bytes.fromhex(text)).decode("ascii"), "subType": "00"}}
    return text


def text_value(neutral: str, value: Any) -> str | None:
    """A BSON value read back as Extended JSON (canonical or relaxed), in the canonical text of its neutral type."""
    if value is None:
        return None
    kind = nt.parse(neutral)
    if isinstance(value, dict):
        if "$numberDecimal" in value or "$numberDouble" in value:
            text = str(value.get("$numberDecimal", value.get("$numberDouble")))
            if isinstance(kind, nt.Decimal):
                try:
                    return str(Decimal(text).quantize(Decimal(1).scaleb(-kind.scale)))
                except InvalidOperation:
                    return text
            return canonical(neutral, text)
        if "$numberInt" in value or "$numberLong" in value:
            return canonical(neutral, str(value.get("$numberInt", value.get("$numberLong"))))
        if "$date" in value:
            raw = value["$date"]
            if isinstance(raw, dict):
                moment = _EPOCH + int(raw["$numberLong"]) * _MILLISECOND
            else:
                moment = _moment(str(raw).replace("Z", "+00:00"))
            if isinstance(kind, nt.Date):
                return moment.date().isoformat()
            if isinstance(kind, nt.Timestamp) and kind.tz:
                return moment.isoformat(timespec="milliseconds")
            return moment.replace(tzinfo=None).isoformat(timespec="milliseconds")
        if "$binary" in value:
            return base64.b64decode(value["$binary"]["base64"]).hex()
        return json.dumps(value, sort_keys=True)  # an embedded document: never equal to a scalar column
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return json.dumps(value, sort_keys=True)
    return canonical(neutral, value if isinstance(value, str) else str(value))


def document(entity: Entity, values: dict[str, str | None]) -> dict[str, Any]:
    """The document of a row: `values` by column, in canonical text; a column the row does not have is left out."""
    types = {column_of(f.name, f.column): f.type for f in entity.fields}
    return {column: bson_value(types[column], value) for column, value in values.items() if column in types}


def row(entity: Entity, found: dict[str, Any]) -> dict[str, str | None]:
    """The row of a document: every field of the entity by column (None when the document lacks it), without _id."""
    return {column_of(f.name, f.column): text_value(f.type, found.get(column_of(f.name, f.column)))
            for f in entity.fields}  # fmt: skip


def target_case(design: Design, use_case: UseCase, case: Any, defaults: dict[str, Scalar] | None = None
                ) -> dict[str, Any]:  # fmt: skip
    """A legacy case in target terms: the request and the answers of the external ports as in every database, and
    the legacy rows as documents of their collections."""
    found = neutral_target_case(design, use_case, case, defaults, str)
    entities = entities_by_legacy(design)
    setup = []
    for table, rows in case.setup.items():
        entity = entities.get(table.lower())
        if entity is None:
            continue
        by_legacy = {(f.legacy or "").lower(): f for f in entity.fields if f.legacy}
        for legacy_row in rows:
            fields = [(by_legacy[c.lower()], v) for c, v in legacy_row.items() if c.lower() in by_legacy]
            values = {column_of(f.name, f.column): canonical(f.type, v) for f, v in fields}
            setup.append({"collection": entity.table, "document": document(entity, values)})
    found["setup"] = setup
    return found


def adapter_class(design: Design, port: str) -> str:
    return f"{design.base_package}.adapters.out.mongodb.Mongo{port}"


def mongodb_plan(design: Design, use_case: UseCase) -> dict[str, Any]:
    """The plan of the MongoDB harness: the server, the collections, the classes and the ports (adapter or fake)."""
    ports = []
    for name in use_case.ports:
        port = next(p for p in design.ports if p.name == name)
        ports.append({"interface": f"{design.base_package}.domain.port.{name}",
                      "adapter": None if port.legacy_program else adapter_class(design, name)})  # fmt: skip
    return {
        "init_uri": INIT_URI,
        "uri": URI,
        "replica_set": REPLICA_SET,
        "host": HOST,
        "database": DATABASE,
        "collections": collections(design),
        "transaction": f"{design.base_package}.adapters.out.mongodb.MongoTransaction",
        "service": f"{design.base_package}.application.{use_case.name}Service",
        "request": f"{design.base_package}.adapters.in.rest.{use_case.name}Request",
        "ports": ports,
    }


def transaction_file(design: Design) -> tuple[str, str]:
    """The transaction of the running use case, which every adapter joins (written by the platform)."""
    package = f"{design.base_package}.adapters.out.mongodb"
    return (
        _path(package, "MongoTransaction"),
        f"""package {package};

import com.mongodb.ReadConcern;
import com.mongodb.TransactionOptions;
import com.mongodb.WriteConcern;
import com.mongodb.client.ClientSession;
import com.mongodb.client.MongoClient;
import java.util.Optional;
import java.util.function.Supplier;

/**
 * The MongoDB transaction of the running use case (ADR-0029): one ClientSession per thread. A use case runs inside
 * {{@link #inTransaction}}; every adapter passes {{@link #current()}} to the driver (the overloads that take a
 * ClientSession), so its reads and writes join the transaction and a rejection undoes them all, as the legacy
 * ROLLBACK did. Outside a transaction current() is empty and the adapters work without a session. Written by the
 * platform: the adapters use it, never change it.
 */
public final class MongoTransaction {{

    private static final ThreadLocal<ClientSession> CURRENT = new ThreadLocal<>();

    private MongoTransaction() {{
    }}

    public static Optional<ClientSession> current() {{
        return Optional.ofNullable(CURRENT.get());
    }}

    public static <T> T inTransaction(MongoClient client, Supplier<T> work) {{
        if (CURRENT.get() != null) {{
            return work.get();
        }}
        try (ClientSession session = client.startSession()) {{
            session.startTransaction(TransactionOptions.builder().readConcern(ReadConcern.SNAPSHOT)
                    .writeConcern(WriteConcern.MAJORITY).build());
            CURRENT.set(session);
            T result;
            try {{
                result = work.get();
            }} catch (RuntimeException | Error e) {{
                session.abortTransaction();
                throw e;
            }} finally {{
                CURRENT.remove();
            }}
            session.commitTransaction();
            return result;
        }}
    }}
}}
""",
    )


def config_file(design: Design) -> tuple[str, str]:
    """The MongoDB client and database as beans, configured by the environment (no credentials in the project)."""
    package = f"{design.base_package}.config"
    return (
        _path(package, "MongoConfig"),
        f"""package {package};

import com.mongodb.client.MongoClient;
import com.mongodb.client.MongoClients;
import com.mongodb.client.MongoDatabase;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** The MongoDB client (official sync driver) and the database of the collections in db/collections.js. */
@Configuration
public class MongoConfig {{

    @Bean(destroyMethod = "close")
    public MongoClient mongoClient(@Value("${{MONGODB_URI}}") String uri) {{
        return MongoClients.create(uri);
    }}

    @Bean
    public MongoDatabase mongoDatabase(MongoClient client,
            @Value("${{MONGODB_DATABASE:{design.context}}}") String name) {{
        return client.getDatabase(name);
    }}
}}
""",
    )


SCRIPT = r"""
mkdir -p /work/harness-out /work/mongo
if ! javac -nowarn -encoding UTF-8 -d /work/harness-out -cp "/work/out:/opt/lib/*" \
    /input/harness/EquivalenceHarness.java 2> /work/javac.txt; then
  echo "===HARNESS-FAILED==="; cat /work/javac.txt; exit 4
fi
mongod --dbpath /work/mongo --bind_ip 127.0.0.1 --port 27017 --replSet rs0 --unixSocketPrefix /work \
  --wiredTigerCacheSizeGB 0.25 --oplogSize 64 --setParameter diagnosticDataCollectionEnabled=false \
  --logpath /work/mongod.log > /dev/null 2>&1 &
for i in $(seq 1 120); do
  grep -q '"Waiting for connections"' /work/mongod.log 2> /dev/null && break
  sleep 1
done
if ! grep -q '"Waiting for connections"' /work/mongod.log 2> /dev/null; then
  echo "===HARNESS-FAILED==="; echo "MongoDB did not start"; tail -c 3000 /work/mongod.log; exit 5
fi
echo "===EQUIVALENCE==="
java -cp "/work/out:/work/harness-out:/opt/lib/*" nexti.equivalence.EquivalenceHarness \
  /input/harness/plan.json /input/harness/cases.json 2>&1 || true
echo "===EQUIVALENCE-END==="
mongod --dbpath /work/mongo --shutdown > /dev/null 2>&1 || true
"""


def tables(design: Design, documents: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, str | None]]]:
    """The collections the harness printed, as the rows of their tables (field = column)."""
    by_collection = {e.table: e for e in design.entities if e.table}
    return {name: [row(by_collection[name], d) for d in found] for name, found in documents.items()
            if name in by_collection}  # fmt: skip


async def run_equivalence(
    sandbox: Sandbox, files: dict[str, str], design: Design, use_case: UseCase, master: GoldenMaster,
    defaults: dict[str, Scalar] | None = None,
) -> EquivalenceRun:  # fmt: skip
    """Compiles the project and runs every golden case on it against MongoDB, compared collection by collection."""
    recorded = [r for r in master.results if r.observation.error is None]
    cases = [target_case(design, use_case, r.case, defaults) for r in recorded]
    extra = {
        "harness/EquivalenceHarness.java": harness_source("mongodb"),
        "harness/plan.json": json.dumps(mongodb_plan(design, use_case)),
        "harness/cases.json": json.dumps(cases),
    }
    build = await compile_and_test(sandbox, files, extra_inputs=extra, after=SCRIPT, limits=MONGODB_LIMITS)
    found = masks(design, use_case, master)
    if not build.compiled:
        return EquivalenceRun(build, [], found, f"the project does not compile: {build.compile_errors[:300]}")
    if "===HARNESS-FAILED===" in build.after_output:
        return EquivalenceRun(build, [], found, build.after_output.split("===HARNESS-FAILED===", 1)[1][:3000])
    raw = {}
    for line in build.after_output.split("===EQUIVALENCE===", 1)[-1].splitlines():
        if line.startswith("NXE "):
            item = json.loads(line[4:])
            item["tables"] = tables(design, item.pop("documents", {}) or {})
            raw[item["name"]] = item
    runs = []
    for recorded_case in recorded:
        item = raw.get(recorded_case.case.name)
        expected = expected_view(design, use_case, recorded_case.observation, found)
        if item is None or item.get("failure"):
            failure = (item or {}).get("failure") or "the harness printed nothing for this case"
            runs.append(CaseRun(recorded_case.case.name, expected, Observation(), failure))
            continue
        rejected = recorded_case.observation.returns not in (0, None)
        actual = actual_view(design, use_case, item, found, rejected)
        if master.from_traces and actual.returns not in (0, None):
            actual = actual.model_copy(update={"returns": -1})
        runs.append(CaseRun(recorded_case.case.name, expected, actual))
    return EquivalenceRun(build, runs, found)


__all__ = ["COLLECTIONS", "IMAGE", "MONGODB_LIMITS", "Aggregate", "aggregate_decision", "aggregates", "bson_type",
           "bson_value", "collections", "collections_script", "config_file", "document", "mongodb_plan", "row",
           "run_equivalence", "target_case", "text_value", "transaction_file", "validator"]  # fmt: skip
