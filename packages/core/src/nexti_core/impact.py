"""Impact analysis over the target application (ADR-0055, point 11): what a change to some files of the generated
(or third-party) code reaches, in cascade, by the names the files declare and use. It defines the scope of the golden
master in flow 3 (add to an existing application) and what a third party should have tested in flow 4. It works on
the source text of Java, C# and Go without compiling it: a file is affected when it names a type (or a Go file) that
an affected file declares; the tables and the transaction boundaries the affected files touch come with it."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

SOURCE_SUFFIXES = (".java", ".cs", ".go")
_TABLE = re.compile(r"\b(?:from|into|update|join)\s+([A-Za-z_][A-Za-z0-9_.]*)", re.I)
_TRANSACTION = re.compile(
    r"TransactionTemplate|@Transactional|\bInTx\(|TransactionFilter|BeginTransaction\(|\.Begin\(\)"
)
_SQL_WORDS = {"select", "where", "set", "values", "and", "or", "on", "as", "order", "group", "by", "dual"}


@dataclass(frozen=True)
class Impact:
    changed: tuple[str, ...]
    affected: tuple[str, ...] = ()  # files reached from the changed ones, in cascade, the changed ones included
    tables: tuple[str, ...] = ()  # tables the affected files read or write (from their SQL)
    transactions: tuple[str, ...] = ()  # affected files that open or hold a transaction boundary
    by_file: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # affected file -> the files that led there

    def names(self) -> str:
        return (f"{len(self.affected)} file(s) affected, {len(self.tables)} table(s), "
                f"{len(self.transactions)} transaction boundary(ies)")  # fmt: skip


def declared_name(path: str) -> str:
    """The type a source file declares: Java and C# name the file after it; a Go file is reached by its stem."""
    stem = path.rsplit("/", 1)[-1]
    return stem.rsplit(".", 1)[0]


def target_impact(files: Mapping[str, str], changed: Sequence[str]) -> Impact:
    """Everything the changed files reach. A file depends on another when its text mentions the name that other
    file declares (a whole word); the dependency closure from the changed files is the affected set."""
    sources = {path: text for path, text in files.items() if path.endswith(SOURCE_SUFFIXES)}
    names = {path: declared_name(path) for path in sources}
    patterns = {path: re.compile(r"\b" + re.escape(name) + r"\b") for path, name in names.items() if name}
    affected: dict[str, tuple[str, ...]] = {}
    queue = [path for path in changed if path in sources]
    for path in queue:
        affected.setdefault(path, ())
    while queue:
        current = queue.pop(0)
        pattern = patterns.get(current)
        if pattern is None:
            continue
        for path, text in sources.items():
            if path == current or path in affected:
                continue
            if pattern.search(text):
                affected[path] = (*affected.get(current, ()), current)
                queue.append(path)
    tables = sorted(
        {
            match.group(1).strip(".").lower()
            for path in affected
            for match in _TABLE.finditer(sources[path])
            if match.group(1).lower() not in _SQL_WORDS and not match.group(1)[0].isupper()
        }
    )
    transactions = sorted(path for path in affected if _TRANSACTION.search(sources[path]))
    return Impact(tuple(changed), tuple(sorted(affected)), tuple(tables), tuple(transactions),
                  dict(sorted(affected.items())))  # fmt: skip
