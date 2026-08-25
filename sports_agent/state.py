
    # sports_agent/state.py
from typing import TypedDict, Annotated, Sequence, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class SportsAgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    intent: Optional[str]  # "odds_ev", "bankroll", "quant_code", "tutor"
    math_results: Optional[dict]