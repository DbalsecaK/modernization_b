"""Tokens of Sybase ASE Transact-SQL with their exact line numbers (the spec cites `file:line`, 4.2). Comments are
kept apart (they are evidence for the reviewer, not code) and `go` batch separators are recognised."""

import re
from dataclasses import dataclass
from typing import Literal

Kind = Literal["word", "variable", "global", "string", "number", "symbol", "temp"]

_TOKEN = re.compile(
    r"""
    (?P<ws>[ \t\r\f\v]+|\n)
  | (?P<line_comment>--[^\n]*)
  | (?P<block_comment>/\*.*?\*/)
  | (?P<string>'(?:[^']|'')*'|"(?:[^"]|"")*")
  | (?P<global>@@[A-Za-z_][A-Za-z0-9_]*)
  | (?P<variable>@[A-Za-z_][A-Za-z0-9_#$]*)
  | (?P<temp>\#{1,2}[A-Za-z_][A-Za-z0-9_#$]*)
  | (?P<bracket>\[[^\]\n]+\])
  | (?P<number>0x[0-9A-Fa-f]+|\$?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+)
  | (?P<word>[A-Za-z_][A-Za-z0-9_$#]*)
  | (?P<symbol><>|!=|!<|!>|<=|>=|\*=|=\*|\|\||[-+*/%=<>(),.;&|^~!:])
    """,
    re.VERBOSE | re.DOTALL,
)


class LexError(ValueError):
    def __init__(self, line: int, text: str) -> None:
        super().__init__(f"line {line}: unexpected {text!r}")
        self.line = line


@dataclass(frozen=True)
class Token:
    kind: Kind
    text: str
    line: int

    @property
    def upper(self) -> str:
        return self.text.upper()

    def is_word(self, *words: str) -> bool:
        return self.kind == "word" and self.upper in words

    def is_symbol(self, *symbols: str) -> bool:
        return self.kind == "symbol" and self.text in symbols


@dataclass(frozen=True)
class Comment:
    text: str
    line_start: int
    line_end: int


def tokenize(source: str) -> tuple[list[Token], list[Comment]]:
    tokens: list[Token] = []
    comments: list[Comment] = []
    line = 1
    position = 0
    while position < len(source):
        match = _TOKEN.match(source, position)
        if match is None:
            raise LexError(line, source[position : position + 20])
        kind = match.lastgroup
        text = match.group()
        if kind in ("line_comment", "block_comment"):
            comments.append(Comment(text, line, line + text.count("\n")))
        elif kind == "bracket":
            tokens.append(Token("word", text[1:-1], line))
        elif kind != "ws":
            tokens.append(Token(kind, text, line))  # type: ignore[arg-type]
        line += text.count("\n")
        position = match.end()
    return tokens, comments


def split_batches(tokens: list[Token]) -> list[list[Token]]:
    """Batches separated by `go` alone on its line (isql convention)."""
    batches: list[list[Token]] = [[]]
    for index, token in enumerate(tokens):
        alone = (index == 0 or tokens[index - 1].line < token.line) and (
            index + 1 == len(tokens) or tokens[index + 1].line > token.line
        )
        if token.is_word("GO") and alone:
            batches.append([])
        else:
            batches[-1].append(token)
    return [b for b in batches if b]
