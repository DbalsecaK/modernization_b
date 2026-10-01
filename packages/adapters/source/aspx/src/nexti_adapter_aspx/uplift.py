"""The uplift assessment (spec 8.3, ADR-0020): for every file of a .NET Framework WebForms application, what blocks
carrying it to .NET 10 as it is and what only needs a mechanical change. Pages and their code-behind are rewritten
(WebForms does not exist in .NET 10); classes without System.Web can be uplifted. Deterministic: it reads API usage,
it never compiles or runs anything."""

import re
from dataclasses import dataclass, field
from typing import Literal

from nexti_core.adapters import SourceFile

BLOCKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("WebForms page directive", re.compile(r"<%@\s*(Page|Control|Master)\b", re.IGNORECASE)),
    ("server controls (asp:)", re.compile(r"<asp:\w+", re.IGNORECASE)),
    ("System.Web.UI (WebForms)", re.compile(r"\bSystem\.Web\.UI\b")),
    ("derives from Page / UserControl", re.compile(r":\s*(System\.Web\.UI\.)?(Page|UserControl|MasterPage)\b")),
    ("ViewState", re.compile(r"\bViewState\b")),
    ("Session state", re.compile(r"\bSession\s*\[")),
    ("Response / Request of System.Web", re.compile(r"\b(Response|Request)\.(Redirect|QueryString|Form|Write)\b")),
    ("WebForms configuration (system.web)", re.compile(r"<system\.web>", re.IGNORECASE)),
)
CHANGES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("System.Data.SqlClient -> Microsoft.Data.SqlClient", re.compile(r"\bSystem\.Data\.SqlClient\b")),
    ("ConfigurationManager -> IConfiguration", re.compile(r"\bConfigurationManager\b")),
    ("connection strings move to appsettings.json", re.compile(r"<connectionStrings>", re.IGNORECASE)),
)


@dataclass(frozen=True)
class UpliftItem:
    file: str
    verdict: Literal["rewrite", "uplift", "replace"]
    blockers: tuple[str, ...] = field(default=())
    changes: tuple[str, ...] = field(default=())

    @property
    def reason(self) -> str:
        if self.blockers:
            return "rewrite: " + "; ".join(self.blockers)
        return "uplift" + (": " + "; ".join(self.changes) if self.changes else " as it is")


def assess(files: list[SourceFile]) -> list[UpliftItem]:
    """One item per .aspx, .cs and .config file, in path order."""
    items = []
    for f in sorted(files, key=lambda x: x.path):
        lower = f.path.lower()
        if not lower.endswith((".aspx", ".ascx", ".master", ".cs", ".config")):
            continue
        blockers = tuple(name for name, pattern in BLOCKERS if pattern.search(f.text))
        changes = tuple(name for name, pattern in CHANGES if pattern.search(f.text))
        if lower.endswith(".config"):
            verdict: Literal["rewrite", "uplift", "replace"] = "replace"  # becomes appsettings.json and Program.cs
        else:
            verdict = "rewrite" if blockers else "uplift"
        items.append(UpliftItem(f.path, verdict, blockers, changes))
    return items
