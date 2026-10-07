"""What a person sees when the attempts of a step run out (ADR-0045): the files of the last attempt and the version
before them, the diagnostic, and an analysis by a model with proposed answers, each with its confidence. The
analysis is help, never the decision: the person chooses, and a failure to analyse leaves the question with the
files and the diagnostic alone."""

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol

from nexti_agents import prompt
from nexti_orchestration.context import Memo
from nexti_orchestration.extraction import ModelCaller, ReplyError, parse_json
from nexti_orchestration.model import Evidence, Explanation, Option

ANALYST = "code-reviewer"  # the catalog role that reads code and explains it (no new agent, no new assignment)
PROMPT = "escalation-analyst"
EXCERPT_AT_MOST = 60_000  # characters of a file kept as evidence
SHOWN_AT_MOST = 24_000  # characters of a file shown to the analyst
KNOWN_KEYS = ("retry", "retryWithInstruction", "stop")
LABELS = {"retry": "Try again", "retryWithInstruction": "Try again with an instruction", "stop": "Stop the run"}


class FilePort(Protocol):
    async def load_file(self, reference: str) -> str: ...


FilesOf = Callable[[Memo], Mapping[str, str]]  # the file references an attempt's artifact holds, by path


async def explain_attempts(
    port: FilePort,
    models: ModelCaller | None,
    what: str,
    memos: Sequence[Memo],
    feedback: str | None,
    files_of: FilesOf,
    base: Mapping[str, str] | None = None,
) -> Explanation:
    """The evidence of a round (last attempt, the version before, the diagnostic) and, with `models`, the analysis.
    `base` is the version the attempts started from when the step keeps one (the convergence); otherwise the
    version before is the previous attempt's."""
    attempts = [m for m in memos if files_of(m)]
    last = attempts[-1] if attempts else None
    previous = attempts[-2] if len(attempts) > 1 else None
    after: dict[str, str] = {}
    before: dict[str, str] = {}
    if last is not None:
        for path, reference in files_of(last).items():
            after[path] = await port.load_file(reference)
            if base is not None and path in base:
                before[path] = base[path]
            elif previous is not None and path in files_of(previous):
                before[path] = await port.load_file(files_of(previous)[path])
    evidence: list[Evidence] = [Evidence("log", "diagnostic", (feedback or "")[:EXCERPT_AT_MOST])]
    attempt_number = len(memos)
    for path, code in after.items():
        evidence.append(Evidence("code", f"{path}#attempt-{attempt_number}", code[:EXCERPT_AT_MOST]))
        if path in before and before[path] != code:
            evidence.append(Evidence("code", f"{path}#before", before[path][:EXCERPT_AT_MOST]))
    if models is None:
        return Explanation(evidence=tuple(evidence))
    analysis = await analyse(models, what, memos, feedback, after, before)
    proposed = [_option(o) for o in analysis.get("options", []) if isinstance(o, dict)]
    options: list[Option] = [o for o in proposed if o is not None]
    if options:
        evidence.append(Evidence("analysis", "model", json.dumps(analysis, ensure_ascii=False)[:EXCERPT_AT_MOST]))
    recommended: Option | None = max(options, key=lambda o: o.confidence or 0.0) if options else None
    alternatives = tuple(o for o in options if o is not recommended)
    return Explanation(
        evidence=tuple(evidence),
        recommended=recommended,
        alternatives=alternatives,
        confidence=recommended.confidence if recommended else None,
        summary=str(analysis.get("cause") or ""),
    )


async def analyse(
    models: ModelCaller,
    what: str,
    memos: Sequence[Memo],
    feedback: str | None,
    after: Mapping[str, str],
    before: Mapping[str, str],
) -> dict[str, Any]:
    """One call to the analyst: the cause, what changed between attempts, and the proposed answers."""
    history = "\n".join(
        f"- attempt {i}: {m.get('summary', '')}; verification: {str(m.get('diagnostic', ''))[:400].strip()}"
        for i, m in enumerate(memos, start=1)
    )
    shown = "\n\n".join(f"### {path} (last attempt)\n```\n{code[:SHOWN_AT_MOST]}\n```" for path, code in after.items())
    shown += "".join(
        f"\n\n### {path} (version before)\n```\n{code[:SHOWN_AT_MOST]}\n```" for path, code in before.items()
    )
    request = (
        f'The step "{what}" did not pass its verification after these attempts:\n{history}\n\n'
        f"Last diagnostic:\n{(feedback or '')[:6000]}\n\nThe files:\n{shown or '(no file)'}\n\n"
        'Answer with one JSON object and nothing else: {"cause": "<the cause in plain words, two sentences at '
        'most>", "change": "<what the attempts changed and why it did not help>", "options": [{"key": '
        '"retry" | "retryWithInstruction" | "stop", "label": "<short label>", "rationale": "<why>", '
        '"instruction": "<for retryWithInstruction: the concrete instruction for the next attempt>", '
        '"confidence": <0.0-1.0>}]}. Propose two or three options; the instruction must name the file and the '
        "exact change when you know it. Never claim the code is correct when the verification says otherwise."
    )
    messages = [{"role": "system", "content": prompt(PROMPT)}, {"role": "user", "content": request}]
    reply = await models.complete(ANALYST, "generation", messages)
    try:
        data = parse_json(reply.content)
    except ReplyError:  # an answer without JSON: the person decides with the files and the diagnostic
        return {}
    return data if isinstance(data, dict) else {}


def _option(data: dict[str, Any]) -> Option | None:
    key = str(data.get("key") or "")
    if key not in KNOWN_KEYS:
        return None
    try:
        confidence = min(1.0, max(0.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    instruction = str(data.get("instruction") or "") if key == "retryWithInstruction" else ""
    if key == "retryWithInstruction" and not instruction:
        return None
    return Option(key, str(data.get("label") or LABELS[key]), str(data.get("rationale") or ""), confidence,
                  instruction)  # fmt: skip


def explainer(
    port: FilePort,
    models: ModelCaller | None,
    what: str,
    files_of: FilesOf,
    base: Callable[[], Mapping[str, str]] | None = None,
) -> Callable[[Sequence[Memo], str | None], Awaitable[Explanation]]:
    """The `explain` callback of `do_verify_correct` for a step whose artifacts hold file references."""

    async def explain(memos: Sequence[Memo], feedback: str | None) -> Explanation:
        return await explain_attempts(port, models, what, memos, feedback, files_of, base() if base else None)

    return explain


def single_file(path: str) -> FilesOf:
    """The artifacts of the service, tests and adapter steps hold {"file": reference} for one known path."""

    def files_of(memo: Memo) -> Mapping[str, str]:
        artifact = memo.get("artifact") or {}
        return {path: str(artifact["file"])} if artifact.get("file") else {}

    return files_of


def many_files(memo: Memo) -> Mapping[str, str]:
    """The artifact of the convergence: {"files": {path: reference}}."""
    artifact = memo.get("artifact") or {}
    files = artifact.get("files") or {}
    return dict(files) if isinstance(files, dict) else {}
