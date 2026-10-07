"""The ASP.NET WebForms source adapter (spec 8.2, 8.3; ADR-0020): recognises pages (`.aspx` with their code-behind),
App_Code classes and `web.config`, parses them deterministically and builds the code layer of the knowledge graph:
page -> event handlers -> the App_Code classes they call -> the tables their SQL reads and writes, and the screen each
page draws. It gives the screen specs (fields with their validators, buttons and navigation), the neutral types, the
classification of the statements, the slices the extractor reads (one per event handler and per App_Code method), the
data a range of lines reads and writes, and the uplift assessment. It never uses a model and never executes
anything; the legacy is observed through recorded traces (`traces/*.json`)."""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from nexti_adapter_aspx.parser import (
    CSHARP_TYPES,
    Control,
    CSharpClass,
    Markup,
    Method,
    parse_csharp,
    parse_markup,
)
from nexti_adapter_aspx.uplift import UpliftItem, assess
from nexti_adapter_cobol.traces import is_trace, load_traces
from nexti_core.adapters import Edge, Inventory, Node, SliceView, SourceFile
from nexti_core.spec.characterization import CoveredBranch, EngineQuirk
from nexti_core.spec.model import SourceRef
from nexti_core.spec.screens import ScreenAction, ScreenField, ScreenSpec

INPUTS = ("TextBox", "DropDownList", "CheckBox", "RadioButtonList", "ListBox")
BUTTONS = ("Button", "LinkButton", "ImageButton")
VALIDATORS = ("RequiredFieldValidator", "RangeValidator", "RegularExpressionValidator", "CompareValidator")
EVENTS = ("OnClick", "OnSelectedIndexChanged", "OnTextChanged", "OnCheckedChanged", "OnCommand")
RANGE_TYPES = {"currency": "decimal(19,4,signed)", "double": "decimal(19,4,signed)", "integer": "integer(32,signed)",
               "date": "date(yyyy-MM-dd)"}  # fmt: skip
_INFRASTRUCTURE = re.compile(r"\b(SqlConnection|SqlCommand|SqlTransaction|SqlDataReader|ConfigurationManager|Parameters"
                             r"\.AddWithValue|\.Open\(\)|\.Close\(\)|ExecuteNonQuery|ExecuteReader|ExecuteScalar|"
                             r"Response\.Redirect|BeginTransaction|Commit\(\)|Rollback\(\)|using\s*\()")  # fmt: skip
_CONTROL_FLOW = re.compile(r"^\s*(if|else|return|for|foreach|while|switch|case|break|continue|try|catch|finally)\b")


def _stem(path: str) -> str:
    return PurePosixPath(path).name.split(".", 1)[0]


def screen_id(page: str) -> str:
    return "SCR-" + re.sub(r"[^A-Z0-9_-]", "", page.upper())[:40]


@dataclass
class Workspace:
    pages: list[Markup]
    classes: list[CSharpClass]  # code-behind and App_Code
    files: dict[str, SourceFile]
    problems: list[str]

    def page_class(self, page: Markup) -> CSharpClass | None:
        name = page.inherits.rsplit(".", 1)[-1] or page.name
        return next((c for c in self.classes if c.name == name), None)

    def code_file(self, page: Markup) -> str | None:
        owner = self.page_class(page)
        return owner.path if owner else None

    def library(self) -> list[CSharpClass]:
        """App_Code classes: the code that is not a page's code-behind."""
        behind = {self.page_class(p).name for p in self.pages if self.page_class(p)}  # type: ignore[union-attr]
        return [c for c in self.classes if c.name not in behind]


class AspxAdapter:
    name = "aspx-webforms"

    def _workspace(self, files: list[SourceFile]) -> Workspace:
        pages, classes, problems = [], [], []
        for f in files:
            lower = f.path.lower()
            if lower.endswith((".aspx", ".ascx", ".master")):
                markup = parse_markup(f.path, f.text)
                if markup.kind != "Page":
                    problems.append(f"{f.path}:1: {markup.kind.lower()} files are detected but not migrated in this "
                                    "version")  # fmt: skip
                    continue
                if markup.registers:
                    problems.append(f"{f.path}:1: {markup.registers} registered user or third-party control(s) are "
                                    "outside the supported subset")  # fmt: skip
                pages.append(markup)
            elif lower.endswith(".cs"):
                classes += parse_csharp(f.path, f.text)
        return Workspace(pages, classes, {f.path: f for f in files}, problems)

    def detect(self, files: list[SourceFile]) -> float:
        pages = [f for f in files if f.path.lower().endswith(".aspx")]
        if not pages:
            return 0.0
        behind = sum(1 for f in files if f.path.lower().endswith(".aspx.cs"))
        return min(1.0, 0.6 + 0.2 * min(behind, 2) / 2 + (0.2 if any("<asp:" in f.text for f in pages) else 0.0))

    # -- screens ---------------------------------------------------------------------------------------------------
    def screens(self, files: list[SourceFile]) -> list[ScreenSpec]:
        workspace = self._workspace(files)
        names = {p.name.lower() for p in workspace.pages}
        return [self._screen(page, workspace, names) for page in workspace.pages]

    def _screen(self, page: Markup, workspace: Workspace, pages: set[str]) -> ScreenSpec:
        owner = workspace.page_class(page)
        written = {c for m in (owner.methods if owner else []) for c in m.writes}
        redirects = {r for m in (owner.methods if owner else []) for r in m.redirects}
        captions = {c.get("AssociatedControlID"): c for c in page.controls if c.kind == "Label" and
                    c.get("AssociatedControlID")}  # fmt: skip
        validators = [c for c in page.controls if c.kind in VALIDATORS]
        fields: list[ScreenField] = []
        for control in page.controls:
            if control.kind in INPUTS:
                fields.append(self._input(control, captions.get(control.id), validators, page.path))
            elif control.kind == "Label" and not control.get("AssociatedControlID") and (
                    control.id in written or not control.get("Text")):  # fmt: skip
                caption = next((c for c in page.controls if c.kind == "Label" and
                                c.get("AssociatedControlID") == control.id), None)  # fmt: skip
                fields.append(ScreenField(
                    name=control.id, kind="output", label=(caption.get("Text") if caption else "") or control.id,
                    length=0, source=SourceRef(file=page.path, line_start=control.line, line_end=control.line_end),
                ))  # fmt: skip
        actions: list[ScreenAction] = []
        for control in page.controls:
            if control.kind in BUTTONS:
                target_page = _page_of(control.get("PostBackUrl"))
                handler = next((control.get(e) for e in EVENTS if control.get(e)), "")
                method = next((m for m in (owner.methods if owner else []) if m.name == handler), None)
                goes = target_page or (next(iter(method.redirects), "") if method else "")
                goes = _page_of(goes)
                target = screen_id(goes) if goes and goes.lower() in pages else None
                description = (f"Runs {handler}" if handler else "") + (
                    f"; navigates to {goes}" if goes and target is None else "")  # fmt: skip
                actions.append(ScreenAction(key=control.id, label=control.get("Text"), target=target,
                                            description=description.strip("; ")))  # fmt: skip
            elif control.kind == "HyperLink":
                goes = _page_of(control.get("NavigateUrl"))
                target = screen_id(goes) if goes and goes.lower() in pages else None
                actions.append(ScreenAction(key=control.id, label=control.get("Text"), target=target,
                                            description="" if target else f"navigates to {goes}"))  # fmt: skip
        if not fields:
            fields.append(ScreenField(name="title", kind="literal", label=page.title or page.name,
                                      length=len(page.title or page.name)))  # fmt: skip
        out = tuple(sorted({a.target for a in actions if a.target} | {screen_id(_page_of(r)) for r in redirects
                                                                      if _page_of(r).lower() in pages}))  # fmt: skip
        lines = [c.line for c in page.controls] or [1]
        last = max([c.line_end for c in page.controls] or [1])
        return ScreenSpec(
            id=screen_id(page.name), name=page.title or page.name, fields=tuple(fields), actions=tuple(actions),
            states=("error",) if validators else (), navigation_out=out,
            sources=(SourceRef(file=page.path, line_start=min(lines), line_end=last),),
        )  # fmt: skip

    def _input(self, control: Control, caption: Control | None, validators: list[Control], path: str) -> ScreenField:
        mine = [v for v in validators if v.get("ControlToValidate") == control.id]
        required = any(v.kind == "RequiredFieldValidator" for v in mine)
        rules: list[str] = []
        neutral = None
        for validator in mine:
            if validator.kind == "RangeValidator":
                rules.append(f"range {validator.get('MinimumValue')}..{validator.get('MaximumValue')} "
                             f"({validator.get('Type') or 'String'})")  # fmt: skip
                neutral = RANGE_TYPES.get(validator.get("Type").lower())
            elif validator.kind == "RegularExpressionValidator":
                rules.append(f"pattern {validator.get('ValidationExpression')}")
            elif validator.kind == "CompareValidator":
                rules.append(f"compare {validator.get('Operator') or 'Equal'} "
                             f"{validator.get('ValueToCompare') or validator.get('ControlToCompare')}")  # fmt: skip
        if required:
            rules.insert(0, "required")
        length = int(control.get("MaxLength") or 0)
        if control.kind == "DropDownList" and control.items:
            neutral = "enum(" + "|".join(control.items) + ")"
            length = max(len(i) for i in control.items)
        elif control.kind == "CheckBox":
            neutral = "boolean"
        elif neutral is None:
            neutral = f"text(var,{length},utf8)" if length else "text(var,max,utf8)"
        messages = "; ".join(v.get("ErrorMessage") for v in mine if v.get("ErrorMessage"))
        return ScreenField(
            name=control.id, kind="input", label=(caption.get("Text") if caption else "") or control.id,
            length=length, type=neutral, required=required, validation="; ".join(rules)[:500], message=messages[:200],
            source=SourceRef(file=path, line_start=control.line, line_end=max([control.line_end] +
                                                                             [v.line_end for v in mine])),
        )  # fmt: skip

    # -- the graph -------------------------------------------------------------------------------------------------
    def inventory(self, files: list[SourceFile]) -> Inventory:
        workspace = self._workspace(files)
        inv = Inventory(adapter=self.name, problems=list(workspace.problems))
        uplift = {item.file: item for item in assess(files)}
        library = {c.name: c for c in workspace.library()}
        tables: set[str] = set()
        for page in workspace.pages:
            owner = workspace.page_class(page)
            key = f"page:{page.name}"
            if owner is None:
                inv.problems.append(f"{page.path}:1: the code-behind {page.code_file or '(none)'} is not in the inputs")
            inv.nodes.append(Node(
                key, "Program", page.name, owner.path if owner else page.path, owner.line_start if owner else 1,
                owner.line_end if owner else None,
                {"kind": "aspx-page", "markup": page.path, "uplift": uplift[page.path].verdict if page.path in uplift
                 else "rewrite", "controls": len(page.controls)},
            ))  # fmt: skip
            inv.nodes.append(Node(f"screen:{screen_id(page.name)}", "Screen", page.title or page.name, page.path))
            inv.edges.append(Edge(key, "USES_MAP", f"screen:{screen_id(page.name)}"))
            for method in owner.methods if owner else []:
                self._method(inv, key, method, library, tables)
        for name, cls in library.items():
            inv.nodes.append(Node(f"class:{name}", "Class", name, cls.path, cls.line_start, cls.line_end,
                                  {"kind": "app-code", "uplift": uplift[cls.path].verdict if cls.path in uplift
                                   else "uplift"}))  # fmt: skip
            for method in cls.methods:
                self._method(inv, f"class:{name}", method, library, tables)
        inv.nodes += [Node(f"table:{t}", "Table", t) for t in sorted(tables)]
        traces, problems = load_traces(files)
        inv.problems += problems
        for trace in traces:
            inv.nodes.append(Node(f"trace:{trace.program}", "TestCase", trace.program, trace.file,
                                  properties={"cases": len(trace.results), "engine": trace.engine}))  # fmt: skip
        inv.metrics = {
            "pages": len(workspace.pages), "classes": len(library),
            "methods": sum(len(c.methods) for c in workspace.classes), "tables": len(tables),
            "controls": sum(len(p.controls) for p in workspace.pages), "files": len(files),
        }  # fmt: skip
        return inv

    def _method(self, inv: Inventory, owner: str, method: Method, library: dict[str, CSharpClass],
                tables: set[str]) -> None:  # fmt: skip
        key = f"method:{method.owner}.{method.name}"
        file = next((n.file for n in inv.nodes if n.key == owner), None)
        inv.nodes.append(Node(key, "Method", f"{method.owner}.{method.name}", file, method.line_start,
                              method.line_end, {"returns": method.returns}))  # fmt: skip
        inv.edges.append(Edge(owner, "CONTAINS", key))
        for table in method.tables_read:
            tables.add(table)
            inv.edges += [Edge(owner, "READS", f"table:{table}"), Edge(key, "READS", f"table:{table}")]
        for table in method.tables_written:
            tables.add(table)
            inv.edges += [Edge(owner, "WRITES", f"table:{table}"), Edge(key, "WRITES", f"table:{table}")]
        for cls, name in method.calls:
            if cls in library:
                inv.edges += [Edge(owner, "CALLS", f"class:{cls}", {"kind": "CALL"}),
                              Edge(key, "CALLS", f"method:{cls}.{name}", {"kind": "CALL"})]  # fmt: skip

    def types(self, files: list[SourceFile]) -> dict[str, str]:
        workspace = self._workspace(files)
        found: dict[str, str] = {}
        for cls in workspace.classes:
            for method in cls.methods:
                for text in [method.returns, *[p.strip().split(" ")[0] for p in method.parameters.split(",") if p]]:
                    if text and text in CSHARP_TYPES:
                        found[text] = CSHARP_TYPES[text]
        return found

    def classification(self, files: list[SourceFile]) -> dict[str, int]:
        workspace = self._workspace(files)
        counts = {"infrastructure": 0, "control_flow": 0, "business": 0}
        for cls in workspace.classes:
            lines = workspace.files[cls.path].text.split("\n")
            for method in cls.methods:
                for line in lines[method.line_start : method.line_end - 1]:
                    text = line.strip()
                    if not text or text in ("{", "}") or text.startswith("//"):
                        continue
                    if _CONTROL_FLOW.match(text):
                        counts["control_flow"] += 1
                    elif _INFRASTRUCTURE.search(text) or text.startswith(('"', '+ "')):
                        counts["infrastructure"] += 1
                    elif text.endswith(";"):
                        counts["business"] += 1
        return counts

    def slices(self, files: list[SourceFile]) -> list[SliceView]:
        """One slice per event handler of a page (and its Page_Load) and per App_Code method."""
        workspace = self._workspace(files)
        views: list[SliceView] = []
        for page in workspace.pages:
            owner = workspace.page_class(page)
            handlers = {c.get(e) for c in page.controls for e in EVENTS if c.get(e)} | {"Page_Load"}
            for method in owner.methods if owner else []:
                if method.name in handlers:
                    inputs = tuple(sorted(set(method.reads)))
                    views.append(SliceView(f"{page.name}.{method.name}", owner.path,  # type: ignore[union-attr]
                                           ((method.line_start, method.line_end),), inputs,
                                           tuple(sorted({*method.tables_read, *method.tables_written}))))  # fmt: skip
        for cls in workspace.library():
            for method in cls.methods:
                params = tuple(p.strip().split(" ")[-1] for p in method.parameters.split(",") if p.strip())
                views.append(SliceView(f"{cls.name}.{method.name}", cls.path, ((method.line_start, method.line_end),),
                                       params, tuple(sorted({*method.tables_read, *method.tables_written}))),
                             )  # fmt: skip
        return views

    def data_of(
        self, files: list[SourceFile], file: str, ranges: list[tuple[int, int]]
    ) -> tuple[frozenset[str], frozenset[str]]:
        workspace = self._workspace(files)
        read: set[str] = set()
        written: set[str] = set()
        for cls in workspace.classes:
            if cls.path != file:
                continue
            for method in cls.methods:
                if any(start <= method.line_end and method.line_start <= end for start, end in ranges):
                    read |= set(method.tables_read)
                    written |= set(method.tables_written)
        return frozenset(read), frozenset(written)

    def uplift(self, files: list[SourceFile]) -> list[UpliftItem]:
        return assess(files)

    def engine_quirks(self, files: list[SourceFile]) -> list[EngineQuirk]:
        """No engine quirk catalogued for this technology yet (M28)."""
        return []

    def coverage_branches(self, files: list[SourceFile], program: str) -> list[CoveredBranch]:
        """The methods of the page's code-behind and of the App_Code classes, the unit a WebForms trace reports as
        executed (step 11 of the plan, ADR-0047): a trace result lists `Class.Method` under `executed`."""
        workspace = self._workspace(files)
        page = next((p for p in workspace.pages if p.name.upper() == program.upper()
                     or _stem(p.path).upper() == program.upper()), None)  # fmt: skip
        owner = workspace.page_class(page) if page is not None else None
        classes = ([owner] if owner else []) + workspace.library()
        return [CoveredBranch(id=f"{c.name}.{m.name}", kind="method", line_start=m.line_start, line_end=m.line_end,
                              file=c.path) for c in classes for m in c.methods]  # fmt: skip

    def digest(self, files: list[SourceFile]) -> str:
        workspace = self._workspace(files)
        lines = ["ASP.NET WebForms application (.NET Framework). Entry points are the pages' event handlers."]
        for page in workspace.pages:
            owner = workspace.page_class(page)
            inputs = [f"{c.id} ({c.kind}{', max ' + c.get('MaxLength') if c.get('MaxLength') else ''})"
                      for c in page.controls if c.kind in INPUTS]  # fmt: skip
            lines.append(f"- Page {page.name} ({page.path}, code-behind {owner.path if owner else 'missing'}): inputs "
                         f"{', '.join(inputs) or 'none'}")  # fmt: skip
            for method in owner.methods if owner else []:
                lines.append(f"  - {method.name} (lines {method.line_start}-{method.line_end}): reads "
                             f"{', '.join(method.tables_read) or 'no table'}, writes "
                             f"{', '.join(method.tables_written) or 'no table'}; shows "
                             f"{', '.join(method.writes) or 'nothing'}"
                             + (f"; to {', '.join(method.redirects)}" if method.redirects else ""))  # fmt: skip
        for cls in workspace.library():
            for method in cls.methods:
                lines.append(f"- App_Code {cls.name}.{method.name}({method.parameters}) -> {method.returns} "
                             f"({cls.path}:{method.line_start}-{method.line_end})")  # fmt: skip
        traces, _ = load_traces(files)
        lines.append("The legacy cannot run here (WebForms needs .NET Framework on Windows): it is observed through "
                     "recorded traces" + (f" of {', '.join(t.program for t in traces)}" if traces else
                                          " (none in the inputs)") + ".")  # fmt: skip
        verdicts = ", ".join(f"{i.file}: {i.verdict}" for i in assess(files))
        lines.append(f"Uplift assessment: {verdicts}.")
        return "\n".join(lines)


def _page_of(url: str) -> str:
    """The page a URL names (~/Comprobante.aspx?n=1 -> Comprobante)."""
    if not url:
        return ""
    return url.split("?", 1)[0].rsplit("/", 1)[-1].split(".", 1)[0]


__all__ = ["AspxAdapter", "UpliftItem", "assess", "is_trace", "screen_id"]
