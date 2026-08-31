import json
import re
from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sports_agent.state import SportsAgentState
from sports_agent.tools import (
    fetch_live_odds, 
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
    fetch_live_odds, predict_matchup_winner, run_monte_carlo_simulation, 
    calculate_clv, statsmodels_spread_regression, calculate_poisson_over_under
])

# Helper Functions
def american_to_decimal(american_odds: float) -> float:
    if american_odds == 0: return 1.0
    if american_odds > 0: return round((american_odds / 100) + 1, 4)
    return round((100 / abs(american_odds)) + 1, 4)

def decimal_to_implied_prob(decimal_odds: float) -> float:
    if decimal_odds <= 1: return 0.0
    return round((1 / decimal_odds) * 100, 2)

def calculate_ev(win_prob: float, american_odds: float, stake: float = 100.0) -> dict:
    dec_odds = american_to_decimal(american_odds)
    profit = stake * (dec_odds - 1)
    ev = (win_prob * profit) - ((1 - win_prob) * stake)
    return {
        "decimal_odds": dec_odds,
        "implied_prob": decimal_to_implied_prob(dec_odds),
        "potential_profit": round(profit, 2),
        "expected_value": round(ev, 2),
        "ev_percentage": round((ev / stake) * 100, 2)
    }

def kelly_criterion(win_prob: float, american_odds: float, fraction: float = 0.5) -> dict:
    decimal_odds = american_to_decimal(american_odds)
    edge = (decimal_odds - 1) * win_prob - (1 - win_prob)
    full_kelly = edge / (decimal_odds - 1) if (decimal_odds - 1) != 0 else 0
    return {
        "full_kelly_pct": round(full_kelly * 100, 2),
        "fractional_kelly_pct": round(max(0, full_kelly * fraction) * 100, 2),
        "fraction_used": "1/2",
    }

def tool_payload(tool_result):
    content = getattr(tool_result, "content", tool_result)
    if isinstance(content, str):
        try: return json.loads(content)
        except json.JSONDecodeError: return {"result": content}
    return content


# Bulletproof Synthesis Layer
async def synthesize_final_response(state: SportsAgentState, tool_data: dict) -> dict:
    synthesis_prompt = SystemMessage(content=(
        f"--- RAW SIMULATION & LIVE ODDS DATA ---\n{json.dumps(tool_data, default=str)}\n\n"
        f"CRITICAL FORMATTING RULES:\n"
        f"1. You MUST write a 2-3 sentence conversational game summary FIRST.\n"
        f"2. You MUST output the ```json block LAST.\n"
        f"3. NO SYMBOLS: Strip all '%' and '$' from your JSON numbers (e.g., use 63.9, not '63.9%').\n"
        f"4. FILL THE GAPS: If any tool data is missing, use your expert sports knowledge to estimate realistic values so NO keys are left at 0 unless mathematically necessary.\n"
        f"Format it exactly like the user's EXAMPLE PERFECT RESPONSE."
    ))
    final_res = await llm.ainvoke([synthesis_prompt, state["messages"][-1]])
    return {"messages": [final_res]}


# THE FIX: Instruct the AI to dynamically pass the sport to ALL tools
async def all_models_node(state: SportsAgentState) -> dict:
    sys_prompt = (
        "You are a Lead Quant. Call your live odds, prediction, monte carlo, and poisson tools to analyze this matchup. "
        "CRITICAL RULES:\n"
        "1. IDENTIFY THE SPORT: Determine if the user is asking for MLB, NBA, or NFL.\n"
        "2. PASS THE SPORT: You MUST pass the identified sport (e.g., 'MLB', 'NBA', 'NFL') to the `sport` parameter for EVERY tool.\n"
        "3. REALISTIC DATA: Estimate realistic EPA values for the specific sport, and a valid `vegas_line` (e.g., 8.5 for MLB, 225.5 for NBA, 45.5 for NFL) so the tools run successfully."
    )
    res = await llm_with_tools.ainvoke([SystemMessage(content=sys_prompt), state["messages"][-1]])
    
    combined_data = {}
    if res.tool_calls:
        for tool_call in res.tool_calls:
            name = tool_call["name"]
            try:
                if name == "fetch_live_odds": combined_data["odds"] = tool_payload(await fetch_live_odds.ainvoke(tool_call))
                elif name == "predict_matchup_winner": combined_data["prediction"] = tool_payload(await predict_matchup_winner.ainvoke(tool_call))
                elif name == "run_monte_carlo_simulation": combined_data["monte_carlo"] = tool_payload(await run_monte_carlo_simulation.ainvoke(tool_call))
                elif name == "calculate_poisson_over_under": combined_data["poisson"] = tool_payload(await calculate_poisson_over_under.ainvoke(tool_call))
            except Exception as e:
                combined_data[name + "_error"] = str(e)

            print(f"\n--- TOOL DEBUG DATA ---\n{json.dumps(combined_data, indent=2)}\n")
            
    return await synthesize_final_response(state, combined_data)


async def classify_sports_intent_node(state: SportsAgentState) -> dict:
    raw_content = state["messages"][-1].content
    user_text = raw_content.split("User Prompt:", 1)[-1] if "User Prompt:" in raw_content else raw_content
    last_msg = user_text.lower()
    
    if any(k in last_msg for k in ["all models", "all four", "complete analysis"]): intent = "all_models"
    elif any(k in last_msg for k in ["monte carlo", "simulation", "regression", "statsmodels", "poisson"]): intent = "data_science"
    elif any(k in last_msg for k in ["clv", "efficiency", "dvoa"]): intent = "data_analyst"
    elif any(k in last_msg for k in ["vs", "v.", "predict", "odds", "ev", "winner", "spread"]): intent = "odds_ev"
    elif any(k in last_msg for k in ["bankroll", "kelly", "units"]): intent = "bankroll"
    elif any(k in last_msg for k in ["code", "python"]): intent = "quant_code"
    else: intent = "odds_ev"
        
    return {"intent": intent}


async def data_analyst_node(state: SportsAgentState) -> dict:
    sys_prompt = "You are an Expert Sports Data Analyst specializing in efficiency metrics."
    res = await llm_with_tools.ainvoke([SystemMessage(content=sys_prompt), state["messages"][-1]])
    data = {}
    if res.tool_calls:
        for tc in res.tool_calls:
            if tc["name"] == "calculate_clv": data["clv"] = tool_payload(await calculate_clv.ainvoke(tc))
    return await synthesize_final_response(state, data)


async def data_science_node(state: SportsAgentState) -> dict:
    sys_prompt = (
        "You are a Lead Quantitative Data Scientist running simulations. "
        "IDENTIFY THE SPORT (MLB, NBA, NFL) and pass it to EVERY tool's `sport` parameter. "
        "Estimate realistic EPA metrics and vegas_line based on the sport."
    )
    res = await llm_with_tools.ainvoke([SystemMessage(content=sys_prompt), state["messages"][-1]])
    data = {}
    if res.tool_calls:
        for tc in res.tool_calls:
            name = tc["name"]
            if name == "run_monte_carlo_simulation": data["monte_carlo"] = tool_payload(await run_monte_carlo_simulation.ainvoke(tc))
            elif name == "statsmodels_spread_regression": data["regression"] = tool_payload(await statsmodels_spread_regression.ainvoke(tc))
            elif name == "calculate_poisson_over_under": data["poisson"] = tool_payload(await calculate_poisson_over_under.ainvoke(tc))
    return await synthesize_final_response(state, data)


async def odds_ev_node(state: SportsAgentState) -> dict:
    sys_prompt = (
        "You are a Senior Quantitative Sports Handicapper. "
        "IDENTIFY THE SPORT (MLB, NBA, NFL) and pass it to EVERY tool's `sport` parameter."
    )
    res = await llm_with_tools.ainvoke([SystemMessage(content=sys_prompt), state["messages"][-1]])
    data = {}
    if res.tool_calls:
        for tc in res.tool_calls:
            name = tc["name"]
            if name == "fetch_live_odds": data["odds"] = tool_payload(await fetch_live_odds.ainvoke(tc))
            elif name == "predict_matchup_winner": data["prediction"] = tool_payload(await predict_matchup_winner.ainvoke(tc))
    return await synthesize_final_response(state, data)


async def bankroll_node(state: SportsAgentState) -> dict:
    return {"messages": [await llm.ainvoke([SystemMessage(content="You are a Risk Manager."), state["messages"][-1]])]}

async def quant_code_node(state: SportsAgentState) -> dict:
    return {"messages": [await llm.ainvoke([SystemMessage(content="You are a Quant Developer."), state["messages"][-1]])]}

async def sports_tutor_node(state: SportsAgentState) -> dict:
    return {"messages": [await llm.ainvoke([SystemMessage(content="You are a Sports Betting Instructor."), state["messages"][-1]])]}