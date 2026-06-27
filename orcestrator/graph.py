from langgraph.graph import StateGraph,END
from langgraph.graph.message import add_messages
from state import OrchetratorState
from orcestrator.nodes import (watchdog_node,parallel_scoring_model,action_gateway_node,fallback_node)

def building_flow_graph()->StateGraph:
    graph=StateGraph(OrchetratorState)
    graph.add_node("watchdog",watchdog_node)
    graph.add_node("parallel_scoring",parallel_scoring_model)
    graph.add_node("action_gateway",action_gateway_node)
    graph.add_edge("fallback",fallback_node)

    graph.set_entry_point("watchdog")

    graph.add_conditional_edges(
        "watchdog",
        route_after_watchdog,
        {
            "continue":"parallel_scoring",
            "kill":"fallback"
        }
    )
    graph.add_edge("parallel_scoring","action_gateway")
    graph.add_edge("action_gateway",END)
    graph.add_edge("fallback",END)

    return graph.compile()

def route_after_watchdog(state:OrchetratorState)->str:
    if state["killes"]:
        return "kill"
    return "continue"