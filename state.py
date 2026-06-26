from typing import TypedDict,Optional,List

class OrchestratorState(TypedDict):
##writes the agent input in this class
    txn_id: str
    cust_token : str
    amount: float
    timestamp : int
    priority : int
    bitmask: int 
    features : dict

    fraud_agent: Optional[float]
    fraud_reason: Optional[float]

    sanctions_hit= Optional[bool]
    sanctions_conf=Optional[float]

    ring_detedted:Optional[bool]
    ring_size:Optional[int]
    ring_node:Optional[str]

    ## final fraud score

    final_tier:Optional[int]
    final_action:Optional[str]
    final_score:Optional[float]

    loop_count:int
    killed:bool
    error:Optional[str]