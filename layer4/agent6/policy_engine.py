
"""
policy_engine.py
----------------
Maps an ExecutionRequest to an ExecutionPlan using the Strategy Pattern.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from models import (
    Action,
    ActionType,
    ExecutionPlan,
    ExecutionRequest,
    Verdict,
)
from planner import create_execution_plan


class PolicyError(Exception):
    pass


class BasePolicy(ABC):
    name = "BasePolicy"

    @abstractmethod
    def actions(self, request: ExecutionRequest) -> List[Action]:
        ...


class BlockPolicy(BasePolicy):
    name = "BlockPolicy"

    def actions(self, request: ExecutionRequest) -> List[Action]:
        return [
            Action(ActionType.LOCK_CARD, 0),
            Action(ActionType.FREEZE_TRANSACTION, 1),
            Action(ActionType.CREATE_CASE, 2),
            Action(ActionType.NOTIFY_FIU, 3),
            Action(ActionType.WRITE_AUDIT, 4),
            Action(ActionType.PUBLISH_EVENT, 5),
            Action(ActionType.UPDATE_METRICS, 6),
        ]


class FlagPolicy(BasePolicy):
    name = "FlagPolicy"

    def actions(self, request: ExecutionRequest) -> List[Action]:
        return [
            Action(ActionType.LOCK_CARD, 0),
            Action(ActionType.CREATE_CASE, 1),
            Action(ActionType.NOTIFY_CUSTOMER, 2),
            Action(ActionType.WRITE_AUDIT, 3),
            Action(ActionType.PUBLISH_EVENT, 4),
            Action(ActionType.UPDATE_METRICS, 5),
        ]


class ReviewPolicy(BasePolicy):
    name = "ReviewPolicy"

    def actions(self, request: ExecutionRequest) -> List[Action]:
        return [
            Action(ActionType.CREATE_CASE, 0),
            Action(ActionType.NOTIFY_ANALYST, 1),
            Action(ActionType.WRITE_AUDIT, 2),
            Action(ActionType.PUBLISH_EVENT, 3),
            Action(ActionType.UPDATE_METRICS, 4),
        ]


class AllowPolicy(BasePolicy):
    name = "AllowPolicy"

    def actions(self, request: ExecutionRequest) -> List[Action]:
        return [
            Action(ActionType.WRITE_AUDIT, 0),
            Action(ActionType.PUBLISH_EVENT, 1),
            Action(ActionType.UPDATE_METRICS, 2),
        ]


class PolicyRegistry:
    def __init__(self):
        self._registry: Dict[Verdict, BasePolicy] = {}

    def register(self, verdict: Verdict, policy: BasePolicy) -> None:
        self._registry[verdict] = policy

    def get(self, verdict: Verdict) -> BasePolicy:
        if verdict not in self._registry:
            raise PolicyError(f"No policy registered for {verdict}")
        return self._registry[verdict]


class PolicyEngine:
    def __init__(self, registry: PolicyRegistry):
        self.registry = registry

    def build_plan(self, request: ExecutionRequest) -> ExecutionPlan:
        policy = self.registry.get(request.verdict)
        actions = policy.actions(request)
        return create_execution_plan(
            request=request,
            actions=actions,
            policy_name=policy.name,
        )


registry = PolicyRegistry()
registry.register(Verdict.BLOCK, BlockPolicy())
registry.register(Verdict.FLAG, FlagPolicy())
registry.register(Verdict.REVIEW, ReviewPolicy())
registry.register(Verdict.ALLOW, AllowPolicy())

policy_engine = PolicyEngine(registry)
