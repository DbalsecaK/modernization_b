"""Adding up the model usage of several calls (one invocation can make several: corrections, judges)."""

from collections.abc import Sequence
from decimal import Decimal

from nexti_orchestration.store import Usage


def total(usages: Sequence[Usage]) -> Usage:
    return Usage(
        model=next((u.model for u in usages if u.model), None),
        input_tokens=sum(u.input_tokens for u in usages),
        output_tokens=sum(u.output_tokens for u in usages),
        cost_usd=sum((u.cost_usd for u in usages), Decimal(0)),
    )
