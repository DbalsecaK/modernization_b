"""Which executor runs each phase in this version (plan M3 decision 3). Real pipelines have the preflight; the other
phases arrive with the verticals (M4+) and, until then, the run waits in them. Demo runs have deterministic executors
for every phase."""

from collections.abc import Mapping

from nexti_orchestration.demo import demo_executors
from nexti_orchestration.graph import Executor
from nexti_orchestration.model import RunContext
from nexti_orchestration.preflight import Preflight, PreflightProbe


def executors_for(run: RunContext, probe: PreflightProbe) -> Mapping[str, Executor]:
    if run.kind == "demo":
        return demo_executors(run)
    return {"preflight": Preflight(probe)}
