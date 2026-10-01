"""What the external backlog should hold, derived by code from the approved specification and the verdicts (spec 7.6,
7.7; ADR-0019): a feature per feature of the approved stories, the stories with their Gherkin criteria and links,
ordered by wave, a task per element each story links, and a bug per failed check of the newest verdict."""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from nexti_integrations.backlog import Desired, State

ACTIVE = ("draft", "review", "question", "approved")


@dataclass(frozen=True)
class StoryItem:
    key: str
    title: str
    feature: str
    narrative: str
    criteria: tuple[str, ...]
    links: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class VerdictItem:
    """The newest verdict of a module: its checks and, per rule, whether golden cases or criterion tests verified it."""

    module: str
    verdict: str
    checks: tuple[tuple[str, str, str, str], ...]  # key, title, status, detail
    proof_pack: str
    verified_rules: frozenset[str] = frozenset()
    rules_of_check: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def frontend(self) -> bool:
        return self.module.startswith("frontend-")


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:60] or "general"


def _story_description(story: StoryItem, names: Mapping[str, str]) -> str:
    links = "\n".join(f"- {link}: {names.get(link, '')}".rstrip(": ") for link in story.links)
    criteria = "\n\n".join(story.criteria)
    return (f"{story.narrative}\n\nAcceptance criteria (Gherkin):\n\n{criteria}\n\nLinked elements of the "
            f"specification:\n{links}\n\nCreated by the NexTI platform from the stories approved at C1.")  # fmt: skip


def desired_items(
    stories: Sequence[StoryItem], waves: Sequence[Sequence[str]], names: Mapping[str, str],
    verdicts: Sequence[VerdictItem] = (), linked: frozenset[str] = frozenset(),
) -> list[Desired]:  # fmt: skip
    """The backlog the specification asks for. Only approved stories enter; a linked story that people discarded or
    merged later is marked discarded, never deleted. A story is done when every rule it links is verified and, if it
    links screens, the frontend verdict passed."""
    wave_of = {key: n for n, wave in enumerate(waves, start=1) for key in wave}
    backend = [v for v in verdicts if not v.frontend]
    verified = frozenset().union(*(v.verified_rules for v in backend)) if backend else frozenset()
    screens_ok = any(v.frontend and v.verdict == "PROVEN" for v in verdicts)
    evidence = "; ".join(
        f"{v.module}: {v.verdict} ({sum(1 for c in v.checks if c[2] == 'passed')}/{len(v.checks)} checks, "
        f"proof pack {v.proof_pack})" for v in verdicts
    )  # fmt: skip
    items: list[Desired] = []
    features: dict[str, str] = {}
    for story in stories:
        approved = story.status == "approved"
        gone = story.status in ("discarded", "merged")
        element = f"story:{story.key}"
        if not approved and not (gone and element in linked):
            continue
        feature = f"feature:{slug(story.feature or 'General')}"
        if approved and feature not in features:
            features[feature] = story.feature or "General"
            name = story.feature or "General"
            items.append(Desired(feature, "feature", name, f"Feature of the specification: {name}.", labels=("nexti",)))
        wave = f"wave-{wave_of.get(story.key, len(waves) + 1)}"
        rules = [link for link in story.links if link.startswith("RULE-")]
        screens = [link for link in story.links if link.startswith("SCR-")]
        done = bool(story.links) and all(r in verified for r in rules) and (not screens or screens_ok) and (
            bool(rules) or screens_ok)  # fmt: skip
        state: State = "discarded" if gone else ("done" if done else "open")
        note = f"Verified by the platform. {evidence}" if state == "done" else (
            "Discarded in the platform after C1." if gone else "")  # fmt: skip
        items.append(Desired(element, "story", f"{story.key} {story.title}", _story_description(story, names),
                             feature if approved else None, ("nexti", wave), state, note))  # fmt: skip
        if gone:
            continue
        for link in story.links:
            task_done = link in verified if link.startswith("RULE-") else screens_ok
            items.append(Desired(
                f"task:{story.key}:{link}", "task", f"{link} {names.get(link, '')}".strip(),
                f"Build and verify {link} of {story.key}.", element, ("nexti", wave),
                "done" if task_done else "open", f"Verified by the platform. {evidence}" if task_done else "",
            ))  # fmt: skip
    return items


def bug_items(verdicts: Sequence[VerdictItem], states: Mapping[str, State] | None = None) -> list[Desired]:
    """A bug per failed check of the newest verdicts, written by code from the evidence: steps, expected and
    obtained, the rules and the trace. Its state follows the bug cycle (open, review once a fix is proposed)."""
    states = states or {}
    found: list[Desired] = []
    for verdict in verdicts:
        for key, title, status, detail in verdict.checks:
            if status != "failed":
                continue
            element = f"bug:{verdict.module}:{key}"
            rules = ", ".join(verdict.rules_of_check.get(key, ())) or "—"
            description = (
                f"Steps: rebuild the generated project of {verdict.module} from its stored files in the sandbox and "
                f"run the check '{title}'.\n\nExpected: the check passes.\n\nObtained: {detail}\n\nRules: {rules}\n\n"
                f"Trace: verdict {verdict.verdict}, proof pack {verdict.proof_pack}.\n\nOpened by the tester agent of "
                "the NexTI platform from the verdict, which code computed (closing this bug does not change it)."
            )
            found.append(Desired(element, "bug", f"[{verdict.module}] {title} failed", description,
                                 labels=("nexti", "bug"), state=states.get(element, "open")))  # fmt: skip
    return found
