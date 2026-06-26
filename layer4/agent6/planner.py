from datetime import datetime
from models import ExecutionPlan, create_execution_id

class ExecutionPlanner:
    def build_plan(self,request,actions,policy_name):
        actions=sorted(actions,key=lambda a:a.priority)
        return ExecutionPlan(
            execution_id=create_execution_id(),
            request=request,
            actions=actions,
            created_at=datetime.utcnow(),
            policy_name=policy_name,
        )

planner=ExecutionPlanner()

def create_execution_plan(request,actions,policy_name):
    return planner.build_plan(request,actions,policy_name)
