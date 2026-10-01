"""Delivery of the generated project (spec 6.1 phase 13, 7.2, ADR-0023): the release (code, cutover plan, hardening
report) and its push to a new branch of the customer's repository."""

from nexti_delivery.cutover import PLAN, ROUTING, plan, route
from nexti_delivery.push import BRANCH_PREFIX, Pushed, PushError, branch_name, push_release

RELEASE_PREFIX = "modernized"

__all__ = ["BRANCH_PREFIX", "PLAN", "RELEASE_PREFIX", "ROUTING", "PushError", "Pushed", "branch_name", "plan",
           "push_release", "route"]  # fmt: skip
