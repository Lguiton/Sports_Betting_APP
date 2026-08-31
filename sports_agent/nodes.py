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
    if american_odds == 0:
        raise ValueError("American odds cannot be zero")
    if american_odds > 0:
        return round((american_odds / 100) + 1, 4)
    else:
        abs_odds = abs(american_odds)
        if abs_odds == 0:
            raise ValueError("American odds cannot be zero")
        return round((100 / abs_odds) + 1, 4)

def decimal_to_implied_prob(decimal_odds: float) -> float:
    if decimal_odds <= 1:
        raise ValueError("Decimal odds must be greater than 1")
    return round((1 / decimal_odds) * 100, 2)

def calculate_ev(win_prob: float, american_odds: float, stake: float = 100.0) -> dict:
    if not 0 <= win_prob <= 1:
        raise ValueError("Win probability must be between 0 and 1")
    if stake <= 0:
        raise ValueError("Stake must be greater than zero")
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

def kelly_criterion(win_prob: float, american_odds: float, fraction: float = 0.5) -> dict:
    if not 0 <= win_prob <= 1:
        raise ValueError("Win probability must be between 0 and 1")
    if not 0 < fraction <= 1:
        raise ValueError("Kelly fraction must be greater than zero and at most 1")
    decimal_odds = american_to_decimal(american_odds)
    edge = (decimal_odds - 1) * win_prob - (1 - win_prob)
    full_kelly = edge / (decimal_odds - 1)
    return {
        "full_kelly_pct": round(full_kelly * 100, 2),
        "fractional_kelly_pct": round(max(0, full_kelly * fraction) * 100, 2),
        "fraction_used": "1/2",
    }

def tool_payload(tool_result):
    content = getattr(tool_result, "content", tool_result)
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"result": content}
    return content

async def all_models_node(state: SportsAgentState) -> dict:
    raw_query = state["messages"][-1].content
    query = raw_query.split("User Prompt:", 1)[-1].split("[System Context", 1)[0].strip()
    matchup = re.search(r"([A-Za-z][A-Za-z .'-]+?)\s+(?:vs\.?|versus)\s+([A-Za-z][A-Za-z .'-]+)", query, re.IGNORECASE)
    home_team = matchup.group(1).strip().title() if matchup else "Home Team"
    away_team = matchup.group(2).strip().split(".")[0].strip().title() if matchup else "Away Team"
    risk_match = re.search(r"Risk Profile:\s*(Conservative|Moderate|Aggressive)", query, re.IGNORECASE)
    risk_profile = risk_match.group(1).title() if risk_match else "Moderate"
    line_match = re.search(r"(?:line|total)\s*(?:is|=)?\s*(\d+(?:\.\d+)?)", query, re.IGNORECASE)
    vegas_line = float(line_match.group(1)) if line_match else 47.5

    odds = tool_payload(await fetch_mock_live_odds.ainvoke({"team": f"{home_team} vs {away_team}", "risk_profile": risk_profile}))
    prediction = tool_payload(await predict_matchup_winner.ainvoke({"home_team": home_team, "away_team": away_team, "sport": "NFL"}))
    monte_carlo = tool_payload(await run_monte_carlo_simulation.ainvoke({"home_team": home_team, "away_team": away_team, "iterations": 10000}))
    poisson = tool_payload(await calculate_poisson_over_under.ainvoke({
        "home_off_epa": 0.15, "away_def_epa": -0.05, "away_off_epa": 0.22,
        "home_def_epa": 0.08, "vegas_line": vegas_line,
    }))
    win_probability = float(str(prediction.get("win_probability", "50%")).rstrip("%")) / 100
    market_odds = float(odds.get("american_odds", -110))
    # Use actual odds from odds tool if present
    if market_odds == -110 and "american_odds" in prediction:
        try:
            market_odds = float(prediction["american_odds"])
        except Exception:
            pass
    kelly = kelly_criterion(win_probability, market_odds, fraction=0.5)
    result = {"odds": odds, "prediction": prediction, "kelly": kelly, "monte_carlo": monte_carlo, "poisson": poisson}
    return {"messages": [AIMessage(content=f"```json\n{json.dumps(result, default=str, indent=2)}\n```")]}

async def classify_sports_intent_node(state: SportsAgentState) -> dict:
    raw_content = state["messages"][-1].content
    # app.py injects a "[System Context - Active Bankroll: $X, Risk Profile: Y]"
    # prefix ahead of every user message. That prefix literally contains the
    # substring "bankroll", which was tricking this keyword classifier into
    # routing almost any query into the bankroll node. Classify on the user's
    # actual question only.
    user_text = raw_content.split("User Prompt:", 1)[-1] if "User Prompt:" in raw_content else raw_content
    last_msg = user_text.lower()
    
    # Enhanced deterministic keyword matching for robust routing
    if any(k in last_msg for k in ["all models", "all four", "all predictors", "complete analysis"]):
        intent = "all_models"
    elif any(k in last_msg for k in ["monte carlo", "simulation", "regression", "statsmodels", "poisson", "over/under", "epa"]):
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
        intent = res if res in ["data_science", "data_analyst", "odds_ev", "bankroll", "quant_code", "tutor"] else "odds_ev"
        
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
            tool_results.append(tool_payload(tool_result))
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
                tool_results.append(tool_payload(await fetch_mock_live_odds.ainvoke(tool_call)))
            elif name == "predict_matchup_winner":
                tool_results.append(tool_payload(await predict_matchup_winner.ainvoke(tool_call)))
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
