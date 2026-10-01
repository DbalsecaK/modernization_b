# mypy: disable-error-code="index, arg-type, attr-defined, unused-ignore"
"""Delivery (ADR-0023): the cutover plan of the fictitious application, and the push of a release to a Git server
over HTTP (dulwich's own server, in the test): a new branch on top of the base branch, the legacy untouched, the
previous release replaced, and never the base branch."""

import asyncio
import threading
from collections.abc import Iterator
from pathlib import Path
from wsgiref.simple_server import make_server

import pytest
from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo
from dulwich.server import DictBackend
from dulwich.web import WSGIRequestHandlerLogger, WSGIServerLogger, make_wsgi_chain

from nexti_core.spec.design import Design
from nexti_delivery import PLAN, ROUTING, PushError, branch_name, plan, push_release

ROOT = Path(__file__).resolve().parents[2]
DESIGN = Design.model_validate_json(
    (ROOT / "packs/target/spring_boot/tests/fixtures/pago_orden/design.json").read_text(encoding="utf-8")
)


def test_the_cutover_plan_routes_each_legacy_program_to_its_endpoint() -> None:
    files = plan(DESIGN)
    assert set(files) == {PLAN, ROUTING}
    assert "| dbo.sp_pago_orden | `POST /api/payments/orders/pay` |" in files[PLAN]
    assert "    path: /api/payments/orders/pay\n    service: PayOrder\n    mode: legacy" in files[ROUTING]


@pytest.fixture
def server(tmp_path: Path) -> Iterator[tuple[str, Repo]]:
    """A bare repository with the customer's legacy on main, served over smart HTTP."""
    repo = Repo.init_bare(str(tmp_path / "customer.git"), mkdir=True)
    blob = Blob.from_string(b"PROCEDURE sp_pago_orden ...\n")
    tree = Tree()
    tree.add(b"legacy.sql", 0o100644, blob.id)
    commit = Commit()
    commit.tree, commit.parents = tree.id, []
    commit.author = commit.committer = b"Customer <dev@customer.invalid>"
    commit.author_time = commit.commit_time = 1_700_000_000
    commit.author_timezone = commit.commit_timezone = 0
    commit.message = b"legacy"
    for obj in (blob, tree, commit):
        repo.object_store.add_object(obj)
    repo.refs[b"refs/heads/main"] = commit.id
    app = make_wsgi_chain(DictBackend({"/customer.git": repo}))
    httpd = make_server("127.0.0.1", 0, app, handler_class=WSGIRequestHandlerLogger, server_class=WSGIServerLogger)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}/customer.git", repo
    httpd.shutdown()


def _tree_paths(repo: Repo, sha: bytes, prefix: str = "") -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for entry in repo.object_store[sha].items():  # type: ignore[attr-defined]
        name = prefix + entry.path.decode()
        if entry.mode & 0o040000:
            found |= _tree_paths(repo, entry.sha, name + "/")
        else:
            found[name] = repo.object_store[entry.sha].data  # type: ignore[attr-defined]
    return found


def test_a_release_goes_to_a_new_branch_on_top_of_the_base_branch(server: tuple[str, Repo]) -> None:
    url, repo = server
    base = repo.refs[b"refs/heads/main"]
    branch = branch_name("Run 7F3A")
    release = {"pom.xml": "<project/>", "docs/cutover/PLAN.md": "# plan"}
    first = asyncio.run(push_release(url, None, "main", branch, "modernized/payments", release, "Release 1"))
    assert (first.branch, first.base, first.files) == ("nexti/run-7f3a", base.decode(), 2)
    pushed = repo.refs[b"refs/heads/nexti/run-7f3a"]
    assert repo.refs[b"refs/heads/main"] == base  # the base branch is never touched
    commit = repo.object_store[pushed]
    assert commit.parents == [base]  # type: ignore[attr-defined]
    assert _tree_paths(repo, commit.tree) == {  # type: ignore[attr-defined]
        "legacy.sql": b"PROCEDURE sp_pago_orden ...\n", "modernized/payments/pom.xml": b"<project/>",
        "modernized/payments/docs/cutover/PLAN.md": b"# plan"}  # fmt: skip

    again = asyncio.run(push_release(url, None, "main", "nexti/run-7f3b", "modernized/payments",
                                     {"pom.xml": "<project version='2'/>"}, "Release 2"))  # fmt: skip
    paths = _tree_paths(repo, repo.object_store[repo.refs[b"refs/heads/nexti/run-7f3b"]].tree)  # type: ignore[attr-defined]
    assert set(paths) == {"legacy.sql", "modernized/payments/pom.xml"}
    assert again.base == base.decode()


def test_a_release_never_goes_to_the_base_branch_nor_outside_nexti(server: tuple[str, Repo]) -> None:
    url, _ = server
    for branch in ("main", "feature/x"):
        with pytest.raises(PushError):
            asyncio.run(push_release(url, None, "main", branch, "modernized", {"a.txt": "x"}, "no"))


def test_an_empty_repository_gets_a_first_commit(tmp_path: Path) -> None:
    repo = Repo.init_bare(str(tmp_path / "empty.git"), mkdir=True)
    app = make_wsgi_chain(DictBackend({"/empty.git": repo}))
    httpd = make_server("127.0.0.1", 0, app, handler_class=WSGIRequestHandlerLogger, server_class=WSGIServerLogger)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/empty.git"
        pushed = asyncio.run(push_release(url, None, "main", "nexti/first", "modernized", {"a.txt": "x"}, "First"))
        assert pushed.base is None
        assert repo.object_store[repo.refs[b"refs/heads/nexti/first"]].parents == []  # type: ignore[attr-defined]
    finally:
        httpd.shutdown()


def test_an_unreachable_repository_is_a_push_error_without_the_token() -> None:
    with pytest.raises(PushError) as caught:
        asyncio.run(push_release("http://127.0.0.1:9/none.git", "ghp_secret-token", "main", "nexti/x", "m",
                                 {"a": "b"}, "x"))  # fmt: skip
    assert "ghp_secret-token" not in str(caught.value)
