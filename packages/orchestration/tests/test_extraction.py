"""Rule extraction and review with a scripted model (spec 11.1, 11.2): the structure and the citation are checked by
code first; an invalid answer goes back with the concrete error; duplicates from overlapping slices are merged."""

import json
from pathlib import Path

import pytest

from nexti_adapter_sybase import SybaseAdapter
from nexti_core.adapters import SliceView, SourceFile
from nexti_core.spec.model import Rule
from nexti_orchestration.extraction import (
    ModelReply,
    ReplyError,
    check_citations,
    consolidate,
    extract,
    numbered,
    parse_json,
    review,
)
from nexti_orchestration.store import Usage

ROOT = Path(__file__).resolve().parents[3]
SOURCE = (ROOT / "packages/adapters/source/sybase/tests/fixtures/pago_orden/sp_pago_orden.sp").read_text(
    encoding="utf-8"
)
VIEW = SliceView("dbo.sp_pago_orden#web", "sp_pago_orden.sp", ((61, 92),), ("@i_canal",), ("db_admin..ad_servicio",))


class ScriptedModel:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, list[dict[str, str]], int, int]] = []

    async def complete(
        self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1, judge: int = 0
    ) -> ModelReply:
        self.calls.append((agent, [dict(m) for m in messages], iteration, judge))
        return ModelReply(self.replies.pop(0), Usage(model="scripted", input_tokens=100, output_tokens=40))


def rule_json(line_start: int, line_end: int, **extra: object) -> dict[str, object]:
    return {
        "name": "Web orders pay half the tariff",
        "category": "calculation",
        "priority": "P0",
        "statement": "For channel WEB the commission is half the tariff rounded to 2 decimals.",
        "condition": "channel = 'WEB'",
        "action": "commission = round(tariff / 2, 2)",
        "inputs": [{"name": "i_canal", "type": "text(fixed,3,iso8859-1)"}],
        "scenarios": [
            "Scenario: Half\n  Given a tariff of 1.25\n  When a WEB order is paid\n  Then the commission is 0.63"
        ],
        "confidence": "high",
        "sources": [{"file": "sp_pago_orden.sp", "line_start": line_start, "line_end": line_end}],
        **extra,
    }


def test_json_is_found_inside_fences_and_prose() -> None:
    assert parse_json('Here it is:\n```json\n{"rules": []}\n```') == {"rules": []}
    assert parse_json('Sure! {"supported": true, "problems": []} Hope it helps') == {"supported": True, "problems": []}
    with pytest.raises(ReplyError, match="no JSON"):
        parse_json("I cannot help with that")


def test_the_slice_is_shown_with_its_line_numbers_only() -> None:
    text = numbered(SOURCE, VIEW)
    assert text.splitlines()[0].startswith("   61  /* RF-03")
    assert "   34  " not in text


def test_a_citation_outside_the_slice_is_caught_by_code() -> None:
    rule = Rule.model_validate({**rule_json(34, 39), "id": "RULE-001"})
    (problem,) = check_citations(rule, VIEW, SOURCE)
    assert "outside the slice" in problem
    assert check_citations(Rule.model_validate({**rule_json(80, 83), "id": "RULE-001"}), VIEW, SOURCE) == []


async def test_an_invalid_answer_is_corrected_with_the_concrete_error() -> None:
    model = ScriptedModel(
        json.dumps({"rules": [rule_json(34, 39, inputs=[{"name": "x", "type": "money"}])]}),
        json.dumps({"rules": [rule_json(80, 83)]}),
    )
    types = SybaseAdapter().types([SourceFile("sp_pago_orden.sp", SOURCE)])
    result = await extract(model, VIEW, SOURCE, types)
    assert [r.name for r in result.rules] == ["Web orders pay half the tariff"]
    assert len(result.usage) == 2
    feedback = model.calls[1][1][-1]["content"]
    assert "outside the slice" in feedback or "neutral" in feedback or "type" in feedback
    assert "decimal(19,4,signed)" in model.calls[0][1][1]["content"]  # the declared types reach the agent


async def test_extraction_gives_up_after_the_maximum_of_iterations() -> None:
    model = ScriptedModel("no json", "still no json")
    with pytest.raises(ReplyError, match="after 2 attempts"):
        await extract(model, VIEW, SOURCE, {}, max_iterations=2)


async def test_the_verifier_reads_only_the_cited_lines() -> None:
    model = ScriptedModel('{"supported": false, "problems": ["the code rounds, the rule says truncates"], '
                          '"corrected_statement": "Half the tariff, rounded."}')  # fmt: skip
    rule = Rule.model_validate({**rule_json(80, 83), "id": "RULE-001"})
    verdict = await review(model, rule, SOURCE, judge=1)
    assert not verdict.supported
    assert verdict.corrected_statement == "Half the tariff, rounded."
    agent, messages, _, judge = model.calls[0]
    assert (agent, judge) == ("rules-verifier", 1)
    assert "if @i_canal = 'WEB'" in messages[1]["content"]
    assert "@i_tipo_cuenta not in" not in messages[1]["content"]


def test_duplicates_from_overlapping_slices_are_merged_and_numbered_by_position() -> None:
    web = Rule.model_validate({**rule_json(80, 83), "id": "RULE-009"})
    web_again = Rule.model_validate(
        {
            **rule_json(
                80, 84, statement="For the WEB channel the commission is half of the tariff, rounded to two decimals."
            ),
            "id": "RULE-002",
        }
    )
    payroll = Rule.model_validate(
        {
            **rule_json(
                85, 86, name="Payroll never pays commission", statement="Service NOMINA pays no commission at all."
            ),
            "id": "RULE-003",
        }
    )
    account = Rule.model_validate({
        **rule_json(34, 39, name="Only some account types may be debited",
                    statement="Only CTE, AHO and VIR accounts are debited."),
        "id": "RULE-004",
    })  # fmt: skip
    merged = consolidate([web, payroll, web_again, account])
    assert [(r.id, r.sources[0].line_start) for r in merged] == [("RULE-001", 34), ("RULE-002", 80), ("RULE-003", 85)]
    assert merged[1].statement.startswith("For the WEB channel")  # the more complete wording wins


async def test_an_answer_cut_at_the_output_limit_is_not_asked_again_and_is_reported_when_halves_are_cut_too() -> None:
    """A reply that reached the profile's output limit ends mid-JSON; asking again would be cut the same way. The
    slice (61-92) is halved; its halves (16 lines) are too small to halve again, so the error says which limit to
    raise after two calls."""

    class CutModel(ScriptedModel):
        async def complete(
            self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1, judge: int = 0
        ) -> ModelReply:
            self.calls.append((agent, [dict(m) for m in messages], iteration, judge))
            return ModelReply('{"rules": [{"name": "Web or', Usage(model="scripted", output_tokens=4096), cut_at=4096)

    model = CutModel()
    with pytest.raises(ReplyError, match=r"cut at the output limit of its profile \(4096 tokens\)"):
        await extract(model, VIEW, SOURCE, {}, max_iterations=3)
    assert len(model.calls) == 2


async def test_a_cut_slice_is_halved_and_each_half_extracted() -> None:
    class HalvingModel(ScriptedModel):
        async def complete(
            self, agent: str, phase: str, messages: list[dict[str, str]], *, iteration: int = 1, judge: int = 0
        ) -> ModelReply:
            self.calls.append((agent, [dict(m) for m in messages], iteration, judge))
            if len(self.calls) == 1:
                return ModelReply('{"rules": [', Usage(model="scripted", output_tokens=4096), cut_at=4096)
            line = 70 if len(self.calls) == 2 else 85  # each half cites a line of its own
            return ModelReply(json.dumps({"rules": [rule_json(line, line + 2)]}), Usage(model="scripted"))

    model = HalvingModel()
    result = await extract(model, VIEW, SOURCE, {}, max_iterations=3)
    assert len(model.calls) == 3
    assert [r.sources[0].line_start for r in result.rules] == [70, 85]
    assert "77" in model.calls[2][1][1]["content"]  # the second half starts after the middle of 61-92
