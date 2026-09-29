"""Fresh inputs (spec 11.3 check 4): cases no one wrote and no one tuned the code to, run on the legacy and on the
target. They are derived by code from the golden master, deterministically (the same suite gives the same fresh
cases, so they can be recorded): every decimal amount of a base case, in its inputs and in its starting rows, is
scaled by a factor of a fixed list. Whole numbers are left alone because they are usually keys that join the
inputs with the rows."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from nexti_core.spec.characterization import Case, Scalar, Suite

FACTORS = ("0.5", "1.5", "0.99", "1.01", "2", "0.1", "3.3", "0.75", "1.25", "10", "0.01", "1.7")
MINIMUM = 10


def _scaled(value: Scalar, factor: Decimal) -> Scalar:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return float((Decimal(str(value)) * factor).quantize(Decimal("0.01"), ROUND_HALF_UP))
    if isinstance(value, str) and "." in value:
        try:
            return str((Decimal(value) * factor).quantize(Decimal("0.01"), ROUND_HALF_UP))
        except InvalidOperation:
            return value
    return value


def _fresh(base: Case, index: int) -> Case:
    factor = Decimal(FACTORS[index % len(FACTORS)])
    inputs = {k: _scaled(v, factor) for k, v in base.inputs.items()}
    setup = {t: [{c: _scaled(v, factor) for c, v in row.items()} for row in rows] for t, rows in base.setup.items()}
    return Case(name=f"fresh_{index + 1:02d}_{base.name}"[:80], rules=base.rules, inputs=inputs, setup=setup,
                stubs=base.stubs, description=f"{base.name} with its amounts scaled by {factor}")  # fmt: skip


def fresh_suite(suite: Suite, count: int = len(FACTORS)) -> Suite:
    """At least `MINIMUM` new cases, cycling over the base cases."""
    count = max(count, MINIMUM)
    cases = [_fresh(suite.cases[i % len(suite.cases)], i) for i in range(count)]
    return Suite(program=suite.program, schema_=suite.schema_, cases=cases)
