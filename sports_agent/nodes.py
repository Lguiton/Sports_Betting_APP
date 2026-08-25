import json
import re
from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sports_agent.state import SportsAgentState
from sports_agent.tools import (
    fetch_mock_live_odds, 
    predict_matchup_winner, 
    run_monte_carlo_simulation, 
    calculate_clv,
    statsmodels_spread_regression,
    calculate_poisson_over_under
)
from config import OPENAI_API_KEY, MODEL_NAME

# Initialize LLM
llm = ChatOpenAI(
    api_key=OPENAI_API_KEY,
    model=MODEL_NAME,
    temperature=0.1
)

# Bind all tools to the LLM
llm_with_tools = llm.bind_tools([
    fetch_mock_live_odds, 
    predict_matchup_winner, 
    run_monte_carlo_simulation, 
    calculate_clv,
    statsmodels_spread_regression,
    calculate_poisson_over_under
])

def american_to_decimal(american_odds: float) -> float:
    if american_odds > 0:
        return round((american_odds / 100) + 1, 4)
    else:
        return round((100 / abs(american_odds)) + 1, 4)

def decimal_to_implied_prob(decimal_odds: float) -> float:
    return round((1 / decimal_odds) * 100, 2)

def calculate_ev(win_prob: float, american_odds: float, stake: float = 100.0) -> dict:
    dec_odds = american_to_decimal(american_odds)
    profit = stake * (dec_odds - 1)
    ev = (win_prob * profit) - ((1 - win_prob) * stake)
    ev_pct = (ev / stake) * 100
    return {
        "decimal_odds": dec_odds,
        "implied_prob": decimal_to_implied_prob(dec_odds),
        "potential_profit": round(profit, 2),
        "expected_value": round(ev, 2),
        "ev_percentage": round(ev_pct, 2)
    }

async def classify_sports_intent_node(state: SportsAgentState) -> dict:
    last_msg = state["messages"][-1].content.lower()
    
    # Enhanced deterministic keyword matching for robust routing
    if any(k in last_msg for k in ["monte carlo", "simulation", "regression", "statsmodels", "poisson", "over/under", "epa"]):
        intent = "data_science"
    elif any(k in last_msg for k in ["clv", "efficiency", "dvoa", "havoc"]):
        intent = "data_analyst"
    elif any(k in last_msg for k in ["vs", "v.", "predict", "odds", "ev", "+ev", "winner", "spread", "chiefs", "bucs"]):
        intent = "odds_ev"
    elif any(k in last_msg for k in ["bankroll", "kelly", "units", "stake"]):
        intent = "bankroll"
    elif any(k in last_msg for k in ["code", "python", "script"]):
        intent = "quant_code"
    else:
        # Fallback to LLM classification if no keywords hit
        prompt = f"""
        Categorize the user's sports analytics query into EXACTLY ONE: 'data_science', 'data_analyst', 'odds_ev', 'bankroll', 'quant_code', 'tutor'.
        Query: "{last_msg}"
        Return ONLY the category string.
        """
        response = await llm.ainvoke([SystemMessage(content=prompt)])
        res = response.content.strip().lower()
        intent = res if res in ["data_science", "data_analyst", "odds_ev", "bankroll", "quant_code"] else "odds_ev"
        
    return {"intent": intent}

async def data_analyst_node(state: SportsAgentState) -> dict:
    sys_prompt = "You are an Expert Sports Data Analyst specializing in efficiency metrics and CLV tracking."
    res = await llm_with_tools.ainvoke([SystemMessage(content=sys_prompt), state["messages"][-1]])
    final_messages = [res]
    if res.tool_calls:
        for tool_call in res.tool_calls:
            if tool_call["name"] == "calculate_clv":
                final_messages.append(await calculate_clv.ainvoke(tool_call))
        msgs = [SystemMessage(content=sys_prompt), state["messages"][-1]]
        msgs.extend(final_messages)
        final_messages.append(await llm.ainvoke(msgs))
    return {"messages": final_messages}

async def data_science_node(state: SportsAgentState) -> dict:
    sys_prompt = """
    You are a Lead Quantitative Data Scientist running simulations, OLS regressions, and Poisson GLMs.
    Explain the result clearly, then preserve the exact quantitative tool result at the end as a fenced
    JSON object. Do not change, round, or rename any tool result fields.
    """
    res = await llm_with_tools.ainvoke([SystemMessage(content=sys_prompt), state["messages"][-1]])
    if res.tool_calls:
        tool_results = []
        for tool_call in res.tool_calls:
            name = tool_call["name"]
            if name == "run_monte_carlo_simulation":
                tool_result = await run_monte_carlo_simulation.ainvoke(tool_call)
            elif name == "statsmodels_spread_regression":
                tool_result = await statsmodels_spread_regression.ainvoke(tool_call)
            elif name == "calculate_poisson_over_under":
                tool_result = await calculate_poisson_over_under.ainvoke(tool_call)
            else:
                continue
            tool_results.append(tool_result)
        serialized_results = "\n\n".join(
            f"```json\n{json.dumps(result, default=str, indent=2)}\n```"
            for result in tool_results
        )
        return {"messages": [AIMessage(content=serialized_results)]}

    return {"messages": [res]}

async def odds_ev_node(state: SportsAgentState) -> dict:
    sys_prompt = "You are a Senior Quantitative Sports Handicapper. Use the prediction tools for matchup queries."
    res = await llm_with_tools.ainvoke([SystemMessage(content=sys_prompt), state["messages"][-1]])
    if res.tool_calls:
        tool_results = []
        for tool_call in res.tool_calls:
            name = tool_call["name"]
            if name == "fetch_mock_live_odds":
                tool_results.append(await fetch_mock_live_odds.ainvoke(tool_call))
            elif name == "predict_matchup_winner":
                tool_results.append(await predict_matchup_winner.ainvoke(tool_call))
        combined_result = {}
        for tool_result in tool_results:
            combined_result.update(tool_result)
        return {"messages": [AIMessage(content=f"```json\n{json.dumps(combined_result, default=str, indent=2)}\n```")]}
    return {"messages": [res]}

async def bankroll_node(state: SportsAgentState) -> dict:
    res = await llm.ainvoke([SystemMessage(content="You are a Risk Manager."), state["messages"][-1]])
    return {"messages": [res]}

async def quant_code_node(state: SportsAgentState) -> dict:
    res = await llm.ainvoke([SystemMessage(content="You are a Quant Developer."), state["messages"][-1]])
    return {"messages": [res]}

async def sports_tutor_node(state: SportsAgentState) -> dict:
    res = await llm.ainvoke([SystemMessage(content="You are a Sports Betting Instructor."), state["messages"][-1]])
    return {"messages": [res]}
