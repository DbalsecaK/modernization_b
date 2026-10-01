"""The customer's backlog in Jira or Azure DevOps (spec 7.6, ADR-0019): what the specification asks for, what is already
linked, and the actions that close the gap. The planner is pure code: a re-sync with nothing new does nothing, and an
item that exists is updated, never created twice (its link lives in `work_item_link`; its label recovers it after a
crash between the external write and the link)."""

import hashlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

ItemKind = Literal["feature", "story", "task", "bug"]
State = Literal["open", "review", "done", "discarded"]
KINDS: tuple[ItemKind, ...] = ("feature", "story", "task", "bug")  # parents before children


@dataclass(frozen=True)
class Desired:
    """An item the platform wants in the external backlog. `element` is its stable id in the platform:
    feature:<name>, story:US-001, task:US-001:RULE-001, bug:<module>:<check>."""

    element: str
    kind: ItemKind
    title: str
    description: str
    parent: str | None = None
    labels: tuple[str, ...] = ()
    state: State = "open"
    comment: str = ""  # said once when the item reaches this state (the evidence of a done item, a bug's result)

    @property
    def label(self) -> str:
        """The label that recovers the item after a crash: nexti-<element>, made safe for both systems."""
        return "nexti-" + "".join(c if c.isalnum() or c in "-_" else "-" for c in self.element)[:200]

    def digest(self) -> str:
        content = "\x1f".join([self.title, self.description, *sorted(self.labels)])
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Linked:
    """An item already in the external backlog, as `work_item_link` remembers it."""

    element: str
    external_id: str
    external_key: str
    url: str
    digest: str
    state: State


@dataclass(frozen=True)
class Action:
    op: Literal["create", "update", "transition"]
    desired: Desired
    linked: Linked | None = None


def plan(desired: Sequence[Desired], linked: dict[str, Linked]) -> list[Action]:
    """The actions that make the external backlog match the specification, parents first."""
    actions: list[Action] = []
    for kind in KINDS:
        for item in (d for d in desired if d.kind == kind):
            current = linked.get(item.element)
            if current is None:
                actions.append(Action("create", item))
                if item.state != "open":
                    actions.append(Action("transition", item))
                continue
            if current.digest != item.digest():
                actions.append(Action("update", item, current))
            if current.state != item.state:
                actions.append(Action("transition", item, current))
    return actions


@dataclass(frozen=True)
class Created:
    external_id: str
    external_key: str
    url: str


class BacklogTracker(Protocol):
    """Jira or Azure DevOps, through its public REST API."""

    @property
    def system(self) -> str:
        """jira or azure_devops."""
        ...

    async def whoami(self) -> str: ...

    async def find(self, label: str) -> Created | None: ...

    async def create(self, kind: ItemKind, title: str, description: str, parent: Created | None,
                     labels: Sequence[str]) -> Created: ...  # fmt: skip

    async def update(self, item: Created, title: str, description: str, labels: Sequence[str]) -> None: ...

    async def transition(self, item: Created, state: State) -> None: ...

    async def comment(self, item: Created, text: str) -> None: ...


@dataclass
class Outcome:
    created: int = 0
    updated: int = 0
    transitioned: int = 0
    recovered: int = 0
    links: dict[str, Linked] = field(default_factory=dict)


Record = Callable[[str, Desired, Linked], Awaitable[None]]  # (operation, item, its link) -> audit + persist


async def apply(
    tracker: BacklogTracker, actions: Sequence[Action], linked: dict[str, Linked], record: Record
) -> Outcome:
    """Runs the actions; each external write is recorded (link and audit) before the next one. A create first looks
    the item up by its label, so a crash after the write and before the link never duplicates it."""
    outcome = Outcome(links=dict(linked))
    for action in actions:
        item = action.desired
        current = outcome.links.get(item.element)
        if action.op == "create" and current is None:
            parent = outcome.links.get(item.parent) if item.parent else None
            labels = (*item.labels, item.label)
            found = await tracker.find(item.label)
            if found is not None:
                outcome.recovered += 1
                created = found
                await tracker.update(found, item.title, item.description, labels)
            else:
                created = await tracker.create(item.kind, item.title, item.description,
                                               _created(parent), labels)  # fmt: skip
                outcome.created += 1
            current = Linked(item.element, created.external_id, created.external_key, created.url, item.digest(),
                             "open")  # fmt: skip
            outcome.links[item.element] = current
            await record("create", item, current)
        elif action.op == "update" and current is not None:
            await tracker.update(_item(current), item.title, item.description, (*item.labels, item.label))
            current = Linked(current.element, current.external_id, current.external_key, current.url, item.digest(),
                             current.state)  # fmt: skip
            outcome.links[item.element] = current
            outcome.updated += 1
            await record("update", item, current)
        elif action.op == "transition" and current is not None and current.state != item.state:
            await tracker.transition(_item(current), item.state)
            if item.comment:
                await tracker.comment(_item(current), item.comment)
            current = Linked(current.element, current.external_id, current.external_key, current.url,
                             current.digest, item.state)  # fmt: skip
            outcome.links[item.element] = current
            outcome.transitioned += 1
            await record("transition", item, current)
    return outcome


def _created(link: Linked | None) -> Created | None:
    return _item(link) if link is not None else None


def _item(link: Linked) -> Created:
    return Created(link.external_id, link.external_key, link.url)
