"""The third party's target, read by code (spec 3.3, ADR-0025): its stack, its endpoints with the fields they take and
return, its tables, the main class or runnable artifact, its configuration keys, and the methods of its services as
slices for the rule extractors. Spring Boot is read in full; ASP.NET Core for the inventory and the slices."""

import re
from dataclasses import dataclass, field
from typing import Literal

from nexti_core.adapters import SourceFile

Stack = Literal["spring-boot", "aspnet-core", "unknown"]
_HTTP = {"GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT", "PatchMapping": "PATCH",
         "DeleteMapping": "DELETE"}  # fmt: skip
_DOTNET_HTTP = {"HttpGet": "GET", "HttpPost": "POST", "HttpPut": "PUT", "HttpPatch": "PATCH", "HttpDelete": "DELETE"}


@dataclass(frozen=True)
class FieldInfo:
    name: str
    type: str


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    handler: str  # Class.method
    file: str
    line: int
    request: tuple[FieldInfo, ...] = ()
    response: tuple[FieldInfo, ...] = ()


@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: tuple[str, ...]
    key: tuple[str, ...] = ()


@dataclass(frozen=True)
class Slice:
    """A method of a service of the target: what the rule extractors read."""

    unit: str  # Class.method
    file: str
    first: int
    last: int


@dataclass(frozen=True)
class TargetInventory:
    stack: Stack
    endpoints: tuple[Endpoint, ...] = ()
    tables: tuple[TableInfo, ...] = ()
    main_class: str | None = None
    artifact: str | None = None  # a runnable jar of the target, when the archive has one
    schema: str | None = None  # the SQL that creates its tables
    properties: dict[str, str] = field(default_factory=dict)
    slices: tuple[Slice, ...] = ()

    def endpoint(self, method: str, path: str) -> Endpoint | None:
        return next((e for e in self.endpoints if e.method == method.upper() and e.path == path), None)

    def table(self, name: str) -> TableInfo | None:
        return next((t for t in self.tables if t.name.lower() == name.lower()), None)


def detect(files: list[SourceFile]) -> Stack:
    paths = [f.path for f in files]
    if any(p.endswith("pom.xml") or p.endswith("build.gradle") for p in paths) and any(
        "@SpringBootApplication" in f.text for f in files if f.path.endswith(".java")
    ):
        return "spring-boot"
    if any(p.endswith(".csproj") for p in paths) and any("[ApiController]" in f.text or "MapPost(" in f.text
                                                           for f in files if f.path.endswith(".cs")):  # fmt: skip
        return "aspnet-core"
    return "unknown"


def inventory(files: list[SourceFile], artifacts: list[str] | None = None) -> TargetInventory:
    """The target's inventory; `artifacts` are the paths of binary files in the archive (a runnable jar)."""
    stack = detect(files)
    jar = next((a for a in sorted(artifacts or []) if a.endswith(".jar")), None)
    if stack == "spring-boot":
        return _spring(files, jar)
    if stack == "aspnet-core":
        return _dotnet(files)
    return TargetInventory("unknown", artifact=jar)


# -- Spring Boot ---------------------------------------------------------------------------------------------------
_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
_CLASS = re.compile(r"\b(?:class|record|interface)\s+(\w+)")
_RECORD = re.compile(r"\brecord\s+(\w+)\s*\((.*?)\)\s*(?:implements[^{]*)?\{", re.DOTALL)
_JAVA_FIELD = re.compile(r"^\s*(?:private|protected|public)\s+(?:final\s+)?([\w.<>,\s?]+?)\s+(\w+)\s*(?:=[^;]*)?;",
                         re.MULTILINE)  # fmt: skip
_MAPPING = re.compile(r'@(RequestMapping|GetMapping|PostMapping|PutMapping|PatchMapping|DeleteMapping)\s*'
                      r'(?:\(\s*(?:value\s*=\s*|path\s*=\s*)?"([^"]*)"[^)]*\))?')  # fmt: skip
_METHOD = re.compile(r"(?:public|protected|private)?\s*(?:static\s+)?([\w.<>,\s?]+?)\s+(\w+)\s*\(([^)]*)\)\s*"
                     r"(?:throws[^{]*)?\{")  # fmt: skip


def _java_types(files: list[SourceFile]) -> dict[str, list[FieldInfo]]:
    """The fields of every record and class of the project, by simple name."""
    found: dict[str, list[FieldInfo]] = {}
    for f in files:
        if not f.path.endswith(".java"):
            continue
        for match in _RECORD.finditer(f.text):
            parts = [p.strip() for p in re.split(r",(?![^<]*>)", match.group(2)) if p.strip()]
            fields = []
            for part in parts:
                bits = re.sub(r"@\w+(\([^)]*\))?\s*", "", part).split()
                if len(bits) >= 2:
                    fields.append(FieldInfo(bits[-1], " ".join(bits[:-1])))
            found[match.group(1)] = fields
        for name in _CLASS.findall(f.text):
            if name not in found and re.search(rf"\bclass\s+{name}\b", f.text):
                found[name] = [FieldInfo(m.group(2), m.group(1).strip()) for m in _JAVA_FIELD.finditer(f.text)]
    return found


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _block_end(text: str, start: int) -> int:
    """The offset of the brace that closes the block opened at or after `start`."""
    depth, index = 0, text.index("{", start)
    while index < len(text):
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        if depth == 0:
            return index
        index += 1
    return len(text) - 1


def _unwrap(type_name: str) -> str:
    """ResponseEntity<PaymentResult> -> PaymentResult; Optional<X> -> X; List<X> stays (a collection)."""
    match = re.fullmatch(r"\s*(?:ResponseEntity|Optional|Mono|CompletableFuture)\s*<\s*(.+)\s*>\s*", type_name)
    return match.group(1).strip() if match else type_name.strip()


def _spring(files: list[SourceFile], jar: str | None) -> TargetInventory:
    types = _java_types(files)
    endpoints: list[Endpoint] = []
    slices: list[Slice] = []
    main_class = None
    for f in sorted(files, key=lambda x: x.path):
        if not f.path.endswith(".java"):
            continue
        package = (_PACKAGE.search(f.text) or [None, ""])[1]
        class_match = _CLASS.search(f.text)
        if class_match is None:
            continue
        class_name = class_match.group(1)
        if "@SpringBootApplication" in f.text:
            main_class = f"{package}.{class_name}" if package else class_name
        if "@RestController" in f.text or "@Controller" in f.text:
            head = f.text[: class_match.start()]
            prefix_match = re.search(r'@RequestMapping\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?"([^"]*)"', head)
            prefix = prefix_match.group(1) if prefix_match else ""
            for mapping in _MAPPING.finditer(f.text, class_match.end()):
                if mapping.group(1) == "RequestMapping":
                    continue
                method = _METHOD.search(f.text, mapping.end())
                if method is None:
                    continue
                body = re.search(r"@RequestBody\s+(?:final\s+)?([\w.<>]+)\s+\w+", method.group(3))
                request = types.get(body.group(1).split(".")[-1], []) if body else []
                returned = _unwrap(method.group(1).split()[-1] if method.group(1).split() else "")
                path = "/" + "/".join(p.strip("/") for p in (prefix, mapping.group(2) or "") if p.strip("/"))
                endpoints.append(Endpoint(_HTTP[mapping.group(1)], path, f"{class_name}.{method.group(2)}", f.path,
                                          _line(f.text, mapping.start()), tuple(request),
                                          tuple(types.get(returned.split(".")[-1], []))))  # fmt: skip
        if "@Service" in f.text or "@Component" in f.text:
            for method in _METHOD.finditer(f.text, class_match.end()):
                kind = method.group(1).split()[-1] if method.group(1).split() else ""
                if method.group(2) in (class_name, "if", "for", "while", "switch", "catch", "synchronized") or kind in (
                    "record",
                    "class",
                    "interface",
                    "enum",
                    "new",
                    "return",
                ):
                    continue
                end = _block_end(f.text, method.end() - 1)
                slices.append(Slice(f"{class_name}.{method.group(2)}", f.path, _line(f.text, method.start()),
                                    _line(f.text, end)))  # fmt: skip
    schema_file = next((f for f in files if f.path.endswith("schema.sql")), None)
    properties: dict[str, str] = {}
    for f in files:
        if f.path.endswith("application.properties"):
            for line in f.text.splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    properties[key.strip()] = value.strip()
    return TargetInventory("spring-boot", tuple(endpoints), tuple(_tables(schema_file.text if schema_file else "")),
                           main_class, jar, schema_file.text if schema_file else None, properties,
                           tuple(slices))  # fmt: skip


_CREATE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.\"]+)\s*\((.*?)\)\s*;", re.IGNORECASE | re.DOTALL)


def _tables(sql: str) -> list[TableInfo]:
    tables = []
    for match in _CREATE.finditer(sql):
        columns, key = [], []
        for part in re.split(r",(?![^(]*\))", match.group(2)):
            part = part.strip()
            primary = re.match(r"PRIMARY\s+KEY\s*\(([^)]*)\)", part, re.IGNORECASE)
            if primary:
                key = [c.strip().strip('"') for c in primary.group(1).split(",")]
                continue
            if not part or re.match(r"(CONSTRAINT|UNIQUE|FOREIGN|CHECK)\b", part, re.IGNORECASE):
                continue
            name = part.split()[0].strip('"')
            columns.append(name)
            if re.search(r"PRIMARY\s+KEY", part, re.IGNORECASE):
                key.append(name)
        tables.append(TableInfo(match.group(1).strip('"'), tuple(columns), tuple(key)))
    return tables


# -- ASP.NET Core --------------------------------------------------------------------------------------------------
_CS_RECORD = re.compile(r"\brecord\s+(\w+)\s*\((.*?)\)\s*;", re.DOTALL)
_CS_PROPERTY = re.compile(r"public\s+([\w.<>?]+)\s+(\w+)\s*\{\s*get;")
_CS_ACTION = re.compile(r"\[(HttpGet|HttpPost|HttpPut|HttpPatch|HttpDelete)(?:\(\s*\"([^\"]*)\"\s*\))?\]\s*"
                        r"(?:\[[^\]]*\]\s*)*public\s+(?:async\s+)?([\w<>.,\s]+?)\s+(\w+)\s*\(([^)]*)\)")  # fmt: skip


def _dotnet(files: list[SourceFile]) -> TargetInventory:
    types: dict[str, list[FieldInfo]] = {}
    for f in files:
        if f.path.endswith(".cs"):
            for match in _CS_RECORD.finditer(f.text):
                types[match.group(1)] = [FieldInfo(p.split()[-1], " ".join(p.split()[:-1]))
                                         for p in (x.strip() for x in match.group(2).split(",")) if p]  # fmt: skip
            for name in re.findall(r"\bclass\s+(\w+)", f.text):
                types.setdefault(name, [FieldInfo(m.group(2), m.group(1)) for m in _CS_PROPERTY.finditer(f.text)])
    endpoints, slices = [], []
    for f in sorted(files, key=lambda x: x.path):
        if not f.path.endswith(".cs"):
            continue
        class_match = re.search(r"\bclass\s+(\w+)", f.text)
        if class_match is None:
            continue
        class_name = class_match.group(1)
        route = re.search(r'\[Route\(\s*"([^"]*)"\s*\)\]', f.text[: class_match.start()])
        prefix = (route.group(1) if route else "").replace(
            "[controller]", class_name.removesuffix("Controller").lower()
        )
        for action in _CS_ACTION.finditer(f.text):
            body = re.search(r"\[FromBody\]\s*([\w.<>]+)\s+\w+", action.group(5))
            returned = re.sub(r"^(Task|ActionResult|IActionResult)<?|>$", "", action.group(3).strip()).strip("<> ")
            path = "/" + "/".join(p.strip("/") for p in (prefix, action.group(2) or "") if p.strip("/"))
            endpoints.append(Endpoint(_DOTNET_HTTP[action.group(1)], path, f"{class_name}.{action.group(4)}", f.path,
                                      _line(f.text, action.start()),
                                      tuple(types.get(body.group(1), [])) if body else (),
                                      tuple(types.get(returned, []))))  # fmt: skip
        if class_name.endswith("Service"):
            for method in re.finditer(r"public\s+(?:async\s+)?[\w<>.,\s?]+?\s+(\w+)\s*\([^)]*\)\s*\{", f.text):
                end = _block_end(f.text, method.end() - 1)
                slices.append(Slice(f"{class_name}.{method.group(1)}", f.path, _line(f.text, method.start()),
                                    _line(f.text, end)))  # fmt: skip
    tables = [TableInfo(name, ()) for f in files if f.path.endswith(".cs")
              for name in re.findall(r'ToTable\(\s*"([^"]+)"', f.text)]  # fmt: skip
    return TargetInventory("aspnet-core", tuple(endpoints), tuple(tables), slices=tuple(slices))
