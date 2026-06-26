## node 1(watch_dog)

import redis,time
from config import Config
from state import OrchestratorState
import asyncio
from layer4.fraud_scorer import run_fraud_scorer
from layer4.sanctions import run_sanction_screen
from layer4.ring import run_ring_detection

cache=redis.Redis(connection_pool=Config.redis_pool)

async def watchdog_node(state:OrchestratorState)->dict:

    txn_id=state["txn_id"]
    loop_key=f"orchestrator_loops:{txn_id}"

    loop_count=cache.incr(loop_key)
    cache.expire(loop_key,300) ##the cache will expire within 300 seconds

    if loop_count>3:
        print(f"[watchdog] kill -txn {txn_id} looped {loop_count}X")
        cache.incr("watchdog kills total")
        return {
            "loop_count":loop_count,
            "killes":True,
            "error":f"Loop detected after {loop_count} iterations"
        }
    
    return {
        "loop_count": loop_count,
        "killed":     False
    }

## node 2

async def parallel_scoring_model(
        state:OrchestratorState
)->dict:
    features=state["features"]
    cust_token=state["cust_token"]
    bitmask=state["bitmask"]

    ring_run = bool ( bitmask & (1<<1)) ## velocity bit

    if(ring_run):
        a2_result,a3_result,a4_result=await asyncio.gather(run_fraud_scorer(features),run_sanction_screen(state),run_ring_detection(state),
                                                           return_exceptions=True)
    else:
        a2_result,a3_result=await asyncio.gather(
            run_fraud_scorer(features),run_sanction_screen(state),return_exceptions=True
        )

        a4_result= {"ring_detection":False,"ring_size":0,"ring_node":None}

    return {
    "fraud_score":    a2_result["fraud_score"],
    "fraud_reasons":  a2_result["fraud_reasons"],
    "sanctions_hit":  a3_result["sanctions_hit"],
    "sanctions_conf": a3_result.get("sanctions_conf", 0.0),
    "matched_entity": a3_result.get("matched_entity", None),
    "ring_detected":  a4_result["ring_detected"],
    "ring_size":      a4_result.get("ring_size", 0),
    "ring_node":      a4_result.get("ring_node", None),
}

##node 3

async def action_gateway_node(
        state:OrchestratorState
)->dict:
    score=state["final_score"] or 0.0
    sanctions_hit=state["sanctions_hit"] or False
    ring_detection=state["ring_detedcted"] or False
    ring_size =state["ring_size"] or 0

    if sanctions_hit:
        return {
            "final_score":1,
            "final_tier":1,
            "final_action":"decline"
        }
    
    if ring_detection and ring_size>=5 and score>0.5:
        score=min(score+0.3,1.0)

    if ring_detection and score>0.6:
        return {
            "final_score":score,
            "final_tier":1,
            "final_action":"decline"
        }
    if score>0.85:
        tier,action=1,"decline"
    elif score>0.6:
        tier,action=2,"hold"
    else:
        tier,action=3,"approve"

    return {
        "final_score":round(score,4),
        "final_tier":tier,
        "final_action":action
    }

async def fallback_node(state:OrchestratorState)->dict:
    amount=state.get("amount".0):
    bitmask=state.get("bitmask",0)

    if amount>5000 or bitmask>0:
        tier,action=2,"hold"
    else:
        tier,action=3,"approve"

    return{
        "final_score":0.5,
        "final_tier":tier,
        "final_action":action,
        "error":"watchdog_fallback",
    }


