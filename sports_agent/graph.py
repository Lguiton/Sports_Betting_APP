# sports_agent/graph.py
import re
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from sports_agent.state import SportsAgentState
from sports_agent.nodes import (
    classify_sports_intent_node,
    odds_ev_node,
    bankroll_node,
    quant_code_node,
    sports_tutor_node,
    data_science_node,
    data_analyst_node,
    all_models_node
)

def route_by_intent(state: SportsAgentState) -> str:
    intent = state.get("intent", "tutor")
    last_message = str(state.get("messages", [])[-1].content).lower() if state.get("messages") else ""

    # A matchup must reach the quantitative prediction node even if the
    # classifier returns a generic tutor label.
    matchup_query = bool(re.search(r"\b(?:vs\.?|versus)\b", last_message))
    if matchup_query and intent == "tutor":
        return "odds_ev"

    if intent in ["odds_ev", "bankroll", "quant_code", "tutor", "data_science", "data_analyst", "all_models"]:
        return intent
    return "tutor"

# Initialize State Graph
workflow = StateGraph(SportsAgentState)

# Add Nodes
workflow.add_node("classifier", classify_sports_intent_node)
workflow.add_node("odds_ev", odds_ev_node)
workflow.add_node("bankroll", bankroll_node)
workflow.add_node("quant_code", quant_code_node)
workflow.add_node("tutor", sports_tutor_node)
workflow.add_node("data_science", data_science_node)
workflow.add_node("data_analyst", data_analyst_node)
workflow.add_node("all_models", all_models_node)

# Entry Point
workflow.set_entry_point("classifier")

# Conditional Edges for Expanded Intent Pathways
workflow.add_conditional_edges(
    "classifier",
    route_by_intent,
    {
        "odds_ev": "odds_ev",
        "bankroll": "bankroll",
        "quant_code": "quant_code",
        "tutor": "tutor",
        "data_science": "data_science",
        "data_analyst": "data_analyst",
        "all_models": "all_models"
    }
)

# Terminations
workflow.add_edge("odds_ev", END)
workflow.add_edge("bankroll", END)
workflow.add_edge("quant_code", END)
workflow.add_edge("tutor", END)
workflow.add_edge("data_science", END)
workflow.add_edge("data_analyst", END)
workflow.add_edge("all_models", END)

# Memory Checkpointer & Compilation
memory = MemorySaver()
sports_agent_app = workflow.compile(checkpointer=memory)