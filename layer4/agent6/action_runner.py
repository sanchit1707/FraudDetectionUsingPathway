from models import ActionResult,ActionStatus
from retry import retry_manager
from circuit_breaker import circuit_registry

class ActionRunner:
    def __init__(self):
        self._handlers={}
    def register(self,t,h):
        self._handlers[t]=h
    def execute(self,action):
        h=self._handlers.get(action.action_type,lambda a:"OK")
        r=retry_manager.run(lambda:circuit_registry.get(action.action_type.value).call(lambda:h(action)))
        return ActionResult(
            action_type=action.action_type,
            status=ActionStatus.SUCCESS,
            latency_ms=0,
            message="Success",
            retries=r.attempts-1,
            response=r.value,
        )

action_runner=ActionRunner()
