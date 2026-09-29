"""The agents' questions (decision cards, spec 10.4): answer with the recommended option, an alternative or a text;
accept the recommendation of every low-impact question at once. When a run has no open question left, the worker is
enqueued to continue it."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import RowMapping, func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from nexti_api.admin.common import audit, not_found, transaction
from nexti_api.authz.require import Authorized, require_project
from nexti_api.errors import ProblemError
from nexti_api.runs.router import question_query
from nexti_api.runs.schemas import AcceptRecommendedIn, AcceptRecommendedOut, AnswerIn, QuestionOut
from nexti_core.db.models import Question, Run
from nexti_core.jobs import defer_run

router = APIRouter(prefix="/api/v1/projects/{project_id}/questions", tags=["questions"])
ViewProject = Annotated[Authorized, Depends(require_project("project.view"))]
AnswerQuestions = Annotated[Authorized, Depends(require_project("question.answer"))]
MAX_LISTED = 200


def option_keys(question: RowMapping) -> list[str]:
    return [str(question["recommended"].get("key")), *(str(a.get("key")) for a in question["alternatives"])]


async def resume_if_answered(conn: AsyncConnection, run_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Enqueue the worker once the run waits for no other question."""
    open_left = (
        await conn.execute(select(func.count()).where(Question.run_id == run_id, Question.status == "open"))
    ).scalar_one()
    status = (await conn.execute(select(Run.status).where(Run.id == run_id))).scalar_one()
    if open_left == 0 and status == "waiting":
        await defer_run(conn, run_id, tenant_id)


@router.get("", response_model=list[QuestionOut])
async def list_questions(
    request: Request,
    project_id: uuid.UUID,
    auth: ViewProject,
    status: Annotated[Literal["open", "answered", "cancelled"] | None, Query()] = None,
) -> list[QuestionOut]:
    query = question_query().where(Question.project_id == project_id)
    if status is not None:
        query = query.where(Question.status == status)
    async with transaction(request, auth) as conn:
        rows = (await conn.execute(query.order_by(Question.created_at.desc()).limit(MAX_LISTED))).mappings()
        return [QuestionOut.model_validate(dict(r)) for r in rows]


@router.post("/{question_id}:answer", response_model=QuestionOut)
async def answer_question(
    request: Request, project_id: uuid.UUID, question_id: uuid.UUID, body: AnswerIn, auth: AnswerQuestions
) -> QuestionOut:
    assert auth.tenant_id is not None  # noqa: S101 - require_project guarantees it
    async with transaction(request, auth) as conn:
        question = (
            (
                await conn.execute(
                    select(Question)
                    .where(Question.id == question_id, Question.project_id == project_id)
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        if question is None:
            raise not_found("question")
        if question["status"] != "open":
            raise ProblemError(409, "question_closed", "The question is no longer open.")
        keys = option_keys(question)
        if body.option is not None and body.option not in keys:
            raise ProblemError(422, "unknown_option", "Choose one of the question's options.")
        # A written answer that matches an option's key is that option (the worker reads the key).
        answer = body.option if body.option is not None else str(body.text).strip()
        recommended = answer == question["recommended"].get("key")
        await conn.execute(
            update(Question)
            .where(Question.id == question_id)
            .values(
                status="answered", answer=answer, was_recommended=recommended, answered_by=auth.user_id,
                answered_at=func.now(), comment=body.comment,
            )
        )  # fmt: skip
        await resume_if_answered(conn, question["run_id"], auth.tenant_id)
        await audit(
            conn, auth, "question.answer", f"project:{project_id}",
            {"question_id": str(question_id), "run_id": str(question["run_id"]), "recommended": recommended,
             "option": body.option},
        )  # fmt: skip
        row = (await conn.execute(question_query().where(Question.id == question_id))).mappings().one()
        return QuestionOut.model_validate(dict(row))


@router.post(":accept-recommended", response_model=AcceptRecommendedOut)
async def accept_recommended(
    request: Request, project_id: uuid.UUID, body: AcceptRecommendedIn, auth: AnswerQuestions
) -> AcceptRecommendedOut:
    """Accept the recommendation of the open low-impact questions (all of the project, or the ones given)."""
    assert auth.tenant_id is not None  # noqa: S101 - require_project guarantees it
    async with transaction(request, auth) as conn:
        query = select(Question).where(
            Question.project_id == project_id, Question.status == "open", Question.impact == "low"
        )
        if body.question_ids is not None:
            query = query.where(Question.id.in_(body.question_ids))
        questions = (await conn.execute(query.with_for_update())).mappings().all()
        for question in questions:
            await conn.execute(
                update(Question)
                .where(Question.id == question["id"])
                .values(
                    status="answered", answer=str(question["recommended"].get("key")), was_recommended=True,
                    answered_by=auth.user_id, answered_at=func.now(),
                )
            )  # fmt: skip
        for run_id in {q["run_id"] for q in questions}:
            await resume_if_answered(conn, run_id, auth.tenant_id)
        await audit(
            conn, auth, "question.accept_recommended", f"project:{project_id}",
            {"question_ids": [str(q["id"]) for q in questions]},
        )  # fmt: skip
    return AcceptRecommendedOut(answered=len(questions))
