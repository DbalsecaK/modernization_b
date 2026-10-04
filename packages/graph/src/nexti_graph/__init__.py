"""The knowledge graph (spec 5): the only way to Neo4j.

Isolation (5.3, minimum acceptable): every node carries `tenant_id` and `project_id`, every query takes both as
mandatory parameters and filters by them, and no other module runs Cypher (an architecture test enforces it). Node
labels and relationship types come from closed lists, never from user input, because Cypher cannot parameterise
them. The source text of the code never enters the graph: only file and line references (5).
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, LiteralString

from neo4j import AsyncDriver, AsyncGraphDatabase

from nexti_core.adapters import Edge, Inventory, Node

LABELS = frozenset({
    "StoredProcedure", "Program", "Paragraph", "Block", "Statement", "Table", "Column", "Field", "File",
    "Mapset", "BmsMap", "Transaction", "Copybook",
    "Rule", "Capability", "Contract", "Story", "TestCase", "Question", "Domain", "Screen",
    "Service", "Module", "Class", "Method", "Endpoint",
})  # fmt: skip
EDGE_TYPES = frozenset({
    "CALLS", "READS", "WRITES", "CONTAINS", "DECLARES", "EXEC_SQL",
    "COPIES", "PERFORMS", "EXEC_CICS", "USES_MAP", "STARTS", "REDEFINES",
    "DERIVED_FROM", "BELONGS_TO", "VERIFIES", "COVERS", "DEPENDS_ON", "IMPLEMENTS", "MAPS_TO",
    "NEXT", "GOTO", "ON_ERROR",
})  # fmt: skip
CODE_LABELS = (
    "StoredProcedure", "Program", "Paragraph", "Block", "Statement", "Table", "Column", "Field", "File", "Mapset",
    "BmsMap", "Transaction", "Copybook",
)  # fmt: skip


class GraphError(ValueError):
    pass


@dataclass(frozen=True)
class Scope:
    """Every graph operation happens inside one project of one tenant."""

    tenant_id: uuid.UUID
    project_id: uuid.UUID

    @property
    def params(self) -> dict[str, str]:
        return {"tenant": str(self.tenant_id), "project": str(self.project_id)}

    def uid(self, key: str) -> str:
        return f"{self.tenant_id}:{self.project_id}:{key}"


@dataclass(frozen=True)
class GraphNode:
    key: str
    labels: tuple[str, ...]
    name: str
    properties: dict[str, Any]


def _label(label: str) -> LiteralString:
    if label not in LABELS:
        raise GraphError(f"unknown node label {label!r}")
    return label


def _edge_type(kind: str) -> LiteralString:
    if kind not in EDGE_TYPES:
        raise GraphError(f"unknown relationship type {kind!r}")
    return kind


def _props(node: Node) -> dict[str, Any]:
    return {
        **{k: v for k, v in node.properties.items() if v is not None},
        "name": node.name, "file": node.file, "line_start": node.line_start, "line_end": node.line_end,
    }  # fmt: skip


class GraphStore:
    def __init__(self, driver: AsyncDriver, database: str = "neo4j") -> None:
        self.driver = driver
        self.database = database

    @classmethod
    def connect(cls, uri: str, user: str, password: str, database: str = "neo4j") -> "GraphStore":
        return cls(AsyncGraphDatabase.driver(uri, auth=(user, password)), database)

    async def close(self) -> None:
        await self.driver.close()

    async def _run(self, query: LiteralString, scope: Scope, **params: Any) -> list[dict[str, Any]]:
        result = await self.driver.execute_query(query, {**params, **scope.params}, database_=self.database)
        return [record.data() for record in result.records]

    async def setup(self) -> None:
        """Constraints and indexes (idempotent). One unique `uid` per node: tenant, project and key together."""
        await self.driver.execute_query(
            "CREATE CONSTRAINT node_uid IF NOT EXISTS FOR (n:Node) REQUIRE n.uid IS UNIQUE", database_=self.database
        )
        await self.driver.execute_query(
            "CREATE INDEX node_scope IF NOT EXISTS FOR (n:Node) ON (n.tenant_id, n.project_id)",
            database_=self.database,
        )

    # -- writing -------------------------------------------------------------------------------------------------
    async def upsert_nodes(self, scope: Scope, nodes: Sequence[Node]) -> None:
        by_label: dict[str, list[dict[str, Any]]] = {}
        for node in nodes:
            by_label.setdefault(node.label, []).append(
                {"uid": scope.uid(node.key), "key": node.key, "props": _props(node)}
            )
        for label, rows in by_label.items():
            query = (
                "UNWIND $rows AS row "
                "MERGE (n:Node {uid: row.uid}) "
                "SET n += row.props, n.key = row.key, n.tenant_id = $tenant, n.project_id = $project, "
                "n:" + _label(label)
            )
            await self._run(query, scope, rows=rows)

    async def upsert_edges(self, scope: Scope, edges: Sequence[Edge]) -> None:
        by_type: dict[str, list[dict[str, Any]]] = {}
        for edge in edges:
            by_type.setdefault(edge.type, []).append(
                {"source": scope.uid(edge.source), "target": scope.uid(edge.target), "props": dict(edge.properties)}
            )
        for kind, rows in by_type.items():
            query = (
                "UNWIND $rows AS row "
                "MATCH (a:Node {uid: row.source, tenant_id: $tenant, project_id: $project}) "
                "MATCH (b:Node {uid: row.target, tenant_id: $tenant, project_id: $project}) "
                "MERGE (a)-[r:" + _edge_type(kind) + "]->(b) SET r += row.props"
            )
            await self._run(query, scope, rows=rows)

    async def replace_code_layer(self, scope: Scope, inventory: Inventory) -> None:
        """The code and data layers of the project are rebuilt from a new inventory; knowledge nodes stay."""
        await self._run(
            "MATCH (n:Node {tenant_id: $tenant, project_id: $project}) WHERE any(l IN labels(n) WHERE l IN $labels) "
            "DETACH DELETE n",
            scope, labels=list(CODE_LABELS),
        )  # fmt: skip
        await self.upsert_nodes(scope, inventory.nodes)
        await self.upsert_edges(scope, inventory.edges)

    async def delete_project(self, scope: Scope) -> None:
        await self._run("MATCH (n:Node {tenant_id: $tenant, project_id: $project}) DETACH DELETE n", scope)

    # -- reading -------------------------------------------------------------------------------------------------
    async def nodes(self, scope: Scope, label: str | None = None) -> list[GraphNode]:
        rows = await self._run(
            "MATCH (n:Node {tenant_id: $tenant, project_id: $project}) WHERE $label IS NULL OR $label IN labels(n) "
            "RETURN n.key AS key, labels(n) AS labels, n.name AS name, properties(n) AS props ORDER BY n.key",
            scope, label=_label(label) if label else None,
        )  # fmt: skip
        return [
            GraphNode(r["key"], tuple(sorted(set(r["labels"]) - {"Node"})), r["name"] or "", _public(r["props"]))
            for r in rows
        ]

    async def edges(self, scope: Scope) -> list[tuple[str, str, str]]:
        rows = await self._run(
            "MATCH (a:Node {tenant_id: $tenant, project_id: $project})-[r]->(b:Node {tenant_id: $tenant, "
            "project_id: $project}) RETURN a.key AS source, type(r) AS type, b.key AS target "
            "ORDER BY source, type, target",
            scope,
        )
        return [(r["source"], r["type"], r["target"]) for r in rows]

    async def relationships(self, scope: Scope) -> list[dict[str, Any]]:
        """The edges of the project with their properties (the line, the kind of call, the CICS command)."""
        return await self._run(
            "MATCH (a:Node {tenant_id: $tenant, project_id: $project})-[r]->(b:Node {tenant_id: $tenant, "
            "project_id: $project}) RETURN a.key AS source, type(r) AS type, b.key AS target, properties(r) AS props "
            "ORDER BY source, type, target",
            scope,
        )

    async def impact(self, scope: Scope, key: str, depth: int = 3) -> list[str]:
        """What may break if `key` changes (5.2): who reads, writes or calls it, up to `depth` hops back."""
        if not 1 <= depth <= 6:
            raise GraphError("depth must be between 1 and 6")
        query = (
            "MATCH (t:Node {uid: $uid, tenant_id: $tenant, project_id: $project}) "
            "MATCH (n:Node {tenant_id: $tenant, project_id: $project})"
            "-[:READS|WRITES|CALLS|COPIES|USES_MAP|STARTS|PERFORMS|CONTAINS|DECLARES|DERIVED_FROM|IMPLEMENTS*1.."
            + str(int(depth))
            + "]->(t) "
            "RETURN DISTINCT n.key AS key ORDER BY key"
        )
        return [r["key"] for r in await self._run(query, scope, uid=scope.uid(key))]

    async def orphans(self, scope: Scope) -> list[str]:
        """Isolated nodes, and programs, copybooks or files nobody uses (5.2): candidates for dead code or missing
        references. A program started by a transaction, or that does something itself, is an entry point."""
        rows = await self._run(
            "MATCH (n:Node {tenant_id: $tenant, project_id: $project}) "
            "WHERE NOT (n)--() "
            "OR ((n:StoredProcedure OR n:Program) AND coalesce(n.external, false) = false "
            "    AND NOT ()-[:CALLS|STARTS]->(n) AND NOT (n)-[:CALLS|READS|WRITES|USES_MAP]->()) "
            "OR (n:Copybook AND NOT ()-[:COPIES]->(n)) "
            "OR (n:File AND NOT ()-[:READS|WRITES]->(n)) "
            "RETURN n.key AS key ORDER BY key",
            scope,
        )
        return [r["key"] for r in rows]

    async def shared_tables(self, scope: Scope, keys: Iterable[str]) -> list[tuple[str, str, str]]:
        """Pairs of the given nodes that touch the same table (one writes it): the source of story dependencies."""
        rows = await self._run(
            "MATCH (a:Node {tenant_id: $tenant, project_id: $project})-[:WRITES]->(t:Table)"
            "<-[:READS|WRITES]-(b:Node {tenant_id: $tenant, project_id: $project}) "
            "WHERE a.key IN $keys AND b.key IN $keys AND a <> b RETURN a.key AS writer, b.key AS user, "
            "t.key AS table ORDER BY writer, user, table",
            scope, keys=list(keys),
        )  # fmt: skip
        return [(r["writer"], r["user"], r["table"]) for r in rows]


def _public(props: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in props.items() if k not in ("uid", "tenant_id", "project_id", "key", "name")}


__all__ = ["EDGE_TYPES", "LABELS", "GraphError", "GraphNode", "GraphStore", "Scope"]
