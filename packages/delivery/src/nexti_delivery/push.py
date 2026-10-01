"""The push of a release to the customer's repository (ADR-0023): a new branch `nexti/<run>` whose commit adds the
release under `modernized/<context>/` on top of the customer's base branch, so the rest of the repository is
untouched and the branch can be reviewed as a pull request. Git in Python (dulwich): no git binary, the token only in
memory. Never the base branch."""

import re
import stat
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from dulwich.client import HttpGitClient
from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import MemoryRepo

AUTHOR = b"NexTI Platform <delivery@nexti.invalid>"
BRANCH_PREFIX = "nexti/"


class PushError(RuntimeError):
    """The repository refused the push or could not be reached; the message carries no credential."""


@dataclass(frozen=True)
class Pushed:
    branch: str
    commit: str
    base: str | None
    files: int


def branch_name(run: str) -> str:
    return BRANCH_PREFIX + re.sub(r"[^a-z0-9-]+", "-", run.lower()).strip("-")[:40]


def _client(url: str, token: str | None) -> tuple[HttpGitClient, str]:
    match = re.match(r"^(https?://[^/]+)(/.*)$", url.rstrip("/"))
    if not match:
        raise PushError("only http(s) repository URLs are supported")
    base, path = match.groups()
    client = HttpGitClient(base, username="x-access-token" if token else None, password=token)
    return client, path


def _insert(repo: MemoryRepo, tree: Tree | None, parts: list[str], blob: Blob) -> Tree:
    """A copy of `tree` with the blob at `parts` (subtrees created or replaced as needed)."""
    new = Tree()
    if tree is not None:
        for entry in tree.items():
            new.add(entry.path, entry.mode, entry.sha)
    head, *rest = parts
    name = head.encode("utf-8")
    if not rest:
        new.add(name, stat.S_IFREG | 0o644, blob.id)
    else:
        current = None
        if tree is not None and name in tree:
            mode, sha = tree[name]
            if stat.S_ISDIR(mode):
                current = repo.object_store[sha]
        sub = _insert(repo, current, rest, blob)  # type: ignore[arg-type]
        repo.object_store.add_object(sub)
        new.add(name, stat.S_IFDIR, sub.id)
    return new


def _without(repo: MemoryRepo, tree: Tree | None, parts: list[str]) -> Tree | None:
    """A copy of `tree` without the subtree at `parts` (the previous release is replaced, not merged)."""
    if tree is None:
        return None
    new = Tree()
    head, *rest = parts
    for entry in tree.items():
        if entry.path == head.encode("utf-8"):
            if not rest:
                continue
            sub = _without(repo, repo.object_store[entry.sha], rest)  # type: ignore[arg-type]
            if sub is not None:
                repo.object_store.add_object(sub)
                new.add(entry.path, entry.mode, sub.id)
            continue
        new.add(entry.path, entry.mode, entry.sha)
    return new


async def push_release(
    url: str, token: str | None, base_branch: str, branch: str, prefix: str, files: Mapping[str, str], message: str,
    ensure_host: Callable[[str], Awaitable[None]] | None = None,
) -> Pushed:  # fmt: skip
    """Pushes `files` under `prefix` to a new commit on `branch`, parented on `base_branch` when it exists."""
    if not branch.startswith(BRANCH_PREFIX) or branch == base_branch:
        raise PushError("a release goes to its own nexti/ branch, never to the base branch")
    if ensure_host is not None:
        await ensure_host(url)
    client, path = _client(url, token)
    repo = MemoryRepo()
    store = cast(Any, repo.object_store)  # dulwich types refs and ids as NewTypes of bytes
    base_ref = f"refs/heads/{base_branch}".encode()
    try:
        remote: Any = client.get_refs(path)
        refs: dict[bytes, bytes] = remote.refs if hasattr(remote, "refs") else remote
        base_sha = refs.get(base_ref)
        if base_sha is not None:
            cast(Any, client).fetch(path, repo, determine_wants=lambda _refs, depth=None: [base_sha], depth=1)
    except Exception as exc:  # dulwich raises several kinds; none may leak the token
        raise PushError(f"the repository could not be read ({type(exc).__name__})") from None
    tree: Tree | None = None
    if base_sha is not None:
        tree = store[store[base_sha].tree]
    parts = [p for p in prefix.strip("/").split("/") if p]
    tree = _without(repo, tree, parts) if parts else tree
    for relative, content in sorted(files.items()):
        blob = Blob.from_string(content.encode("utf-8"))
        repo.object_store.add_object(blob)
        tree = _insert(repo, tree, [*parts, *relative.strip("/").split("/")], blob)
    assert tree is not None  # noqa: S101 - there is at least one file
    repo.object_store.add_object(tree)
    commit = Commit()
    commit.tree = tree.id
    cast(Any, commit).parents = [base_sha] if base_sha is not None else []
    commit.author = commit.committer = AUTHOR
    commit.author_time = commit.commit_time = int(time.time())
    commit.author_timezone = commit.commit_timezone = 0
    commit.encoding = b"UTF-8"
    commit.message = message.encode("utf-8")
    repo.object_store.add_object(commit)
    target = f"refs/heads/{branch}".encode()
    try:
        send = cast(Any, client).send_pack
        result = send(path, lambda current: {**current, target: commit.id}, generate_pack_data=repo.generate_pack_data)
    except Exception as exc:
        raise PushError(f"the repository refused the push ({type(exc).__name__})") from None
    statuses = getattr(result, "ref_status", None) or {}
    if statuses.get(target):
        raise PushError(f"the repository refused the branch: {statuses[target]}"[:300])
    return Pushed(branch, commit.id.decode(), base_sha.decode() if base_sha else None, len(files))
