import json
import re
import duckdb
from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sports_agent.state import SportsAgentState
from sports_agent import espn_stats
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

def _ground_home_away(args: dict) -> dict:
    """The tool-calling LLM has no real schedule data -- it decides
    home_team/away_team purely from how the user phrased the matchup, and
    gets it backwards often (confirmed live: "Braves @ Nationals," with the
    Nationals hosting, came back with the Braves -- the actual road team --
    labeled home). That's not just a display bug: ratings.py's
    win_probability() adds a real home-field rating bonus to whichever team
    is passed as home_team, so a swapped orientation can flip who the model
    actually favors. Cross-check against ESPN's real scoreboard for the day
    and correct the orientation before any tool runs the numbers; if ESPN's
    scoreboard can't confidently resolve it (no game found, ambiguous
    match, request failed), leave the LLM's guess alone rather than risk a
    wrong "correction"."""
    home_team = args.get("home_team")
    away_team = args.get("away_team")
    sport = args.get("sport", "NFL")
    if not home_team or not away_team:
        return args
    try:
        check = espn_stats.resolve_matchup_home_away(sport, home_team, away_team)
    except Exception:
        return args
    if check.get("resolved") and check.get("home") != home_team:
        corrected = dict(args)
        corrected["home_team"] = check["home"]
        corrected["away_team"] = check["away"]
        return corrected
    return args


def _grounded_tool_call(tc: dict) -> dict:
    """Returns tc with its args' home_team/away_team corrected via
    _ground_home_away, without mutating the original tool_call dict."""
    args = tc.get("args") or {}
    if "home_team" in args and "away_team" in args:
        corrected = _ground_home_away(args)
        if corrected is not args:
            tc = dict(tc)
            tc["args"] = corrected
    return tc


# Bulletproof Synthesis Layer
async def synthesize_final_response(state: SportsAgentState, tool_data: dict) -> dict:
    synthesis_prompt = SystemMessage(content=(
        f"--- RAW SIMULATION & LIVE ODDS DATA ---\n{json.dumps(tool_data, default=str)}\n\n"
        f"CRITICAL FORMATTING RULES:\n"
        f"1. You MUST write a 2-3 sentence conversational game summary FIRST.\n"
        f"2. You MUST output the ```json block LAST.\n"
        f"3. NO SYMBOLS: Strip all '%' and '$' from your JSON numbers.\n"
        f"4. FILL THE GAPS: If any tool data is missing, estimate realistic values.\n"
        f"5. Match the user's EXAMPLE PERFECT RESPONSE STRUCTURE ONLY -- its numbers (4.2, 12.50, 8.21, "
        f"99.97, 50, 5, 'DraftKings') are placeholders and MUST NOT be reused. Every number in your JSON "
        f"must be computed from the RAW SIMULATION & LIVE ODDS DATA above, not copied from the example."
    ))
    final_res = await llm.ainvoke([synthesis_prompt, state["messages"][-1]])
    
    # --- SNEAKY BACKEND TELEMETRY LOGGING ---
    try:
        json_match = re.search(r'```json\n(.*?)\n```', final_res.content, re.DOTALL)
        if json_match:
            ui_data = json.loads(json_match.group(1))
            
            # THE FIX: Safely hunt for the matchup string across tools without chained .get() traps
            matchup = "Unknown Matchup"
            for tool_name in ["prediction", "monte_carlo", "odds", "poisson"]:
                tool_result = tool_data.get(tool_name)
                if isinstance(tool_result, dict):
                    # Check for common keys the agent uses to identify the game
                    found = tool_result.get("matchup") or tool_result.get("prediction_target")
                    if found:
                        matchup = found
                        break
            
            # Extract Kelly metrics using the exact keys from the prompt
            recommended_wager = float(ui_data.get("kelly", {}).get("recommended_wager", 0.0))
            kelly_pct = float(ui_data.get("kelly", {}).get("bankroll_pct", 0.0))
            
            # Strip the '%' symbol and calculate the winner directly from raw Monte Carlo math
            home_prob_str = str(tool_data.get("monte_carlo", {}).get("home_win_probability", "50%"))
            home_prob = float(home_prob_str.replace("%", ""))
            winner = "Home" if home_prob > 50 else "Away"
            
            # Extract projected points from the raw Poisson math
            vegas_line = float(tool_data.get("poisson", {}).get("projected_total_points", 0.0))

            # Silently log to DuckDB
            conn = duckdb.connect('data/telemetry.duckdb')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS predictions_log (
                    sport VARCHAR, matchup VARCHAR, recommended_wager DOUBLE,
                    kelly_percentage DOUBLE, predicted_winner VARCHAR, vegas_line DOUBLE
                )
            ''')
            conn.execute('''
                INSERT INTO predictions_log (sport, matchup, recommended_wager, kelly_percentage, predicted_winner, vegas_line)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', ("Auto-Logged", matchup, recommended_wager, kelly_pct, winner, vegas_line))
            conn.close()
            print(f"\n[TELEMETRY SUCCESS] Automatically logged {matchup} to DuckDB!")
    except Exception as e:
        print(f"\n[TELEMETRY WARNING] Failed to parse and log data: {str(e)}")
    # ----------------------------------------

    # math_results carries the REAL tool outputs (poisson/monte_carlo/prediction/
    # odds/regression/clv) back to the API layer via graph state, so
    # backend/main.py can compute edge/EV/Kelly from real numbers instead of
    # parsing them back out of the LLM's prose (which was silently never
    # working -- see backend/main.py).
    return {"messages": [final_res], "math_results": tool_data}

async def all_models_node(state: SportsAgentState) -> dict:
    sys_prompt = (
        "You are a Lead Quant. Call your live odds, prediction, monte carlo, and poisson tools to analyze this matchup. "
        "CRITICAL RULES:\n"
        "1. IDENTIFY THE SPORT: Determine if the user is asking for MLB, NBA, or NFL.\n"
        "2. PASS THE SPORT: You MUST pass the identified sport (e.g., 'MLB') to the `sport` parameter for EVERY tool.\n"
        "3. REALISTIC DATA: Regardless of the sport, EPA parameters MUST be tiny decimals between -0.15 and 0.25 (e.g., 0.05). NEVER use whole numbers for EPA. Estimate a valid `vegas_line` (e.g., 8.5 for MLB, 225.5 for NBA, 45.5 for NFL)."
    )
    res = await llm_with_tools.ainvoke([SystemMessage(content=sys_prompt), state["messages"][-1]])
    
    combined_data = {}
    if res.tool_calls:
        for tool_call in res.tool_calls:
            name = tool_call["name"]
            try:
                if name == "fetch_live_odds": combined_data["odds"] = tool_payload(await fetch_live_odds.ainvoke(_grounded_tool_call(tool_call)))
                elif name == "predict_matchup_winner": combined_data["prediction"] = tool_payload(await predict_matchup_winner.ainvoke(_grounded_tool_call(tool_call)))
                elif name == "run_monte_carlo_simulation": combined_data["monte_carlo"] = tool_payload(await run_monte_carlo_simulation.ainvoke(_grounded_tool_call(tool_call)))
                elif name == "calculate_poisson_over_under": combined_data["poisson"] = tool_payload(await calculate_poisson_over_under.ainvoke(_grounded_tool_call(tool_call)))
            except Exception as e:
                combined_data[name + "_error"] = str(e)
                
    print(f"\n--- TOOL DEBUG DATA ---\n{json.dumps(combined_data, indent=2)}\n")
            
    return await synthesize_final_response(state, combined_data)

async def classify_sports_intent_node(state: SportsAgentState) -> dict:
    raw_content = state["messages"][-1].content
    user_text = raw_content.split("User Prompt:", 1)[-1] if "User Prompt:" in raw_content else raw_content
    # backend/main.py appends a "--- SYSTEM CONTEXT ---" block (bankroll, risk
    # profile, formatting rules, and a worked EXAMPLE full of keywords like
    # "poisson"/"kelly") after the real question. Left in, those keywords
    # were matching first and routing EVERY query -- bankroll questions,
    # tutoring questions, everything -- to data_science_node regardless of
    # what was actually asked. Strip it before classifying.
    for marker in ("--- SYSTEM CONTEXT ---", "SYSTEM CONTEXT", "CRITICAL INSTRUCTIONS"):
        if marker in user_text:
            user_text = user_text.split(marker, 1)[0]
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
            if name == "run_monte_carlo_simulation": data["monte_carlo"] = tool_payload(await run_monte_carlo_simulation.ainvoke(_grounded_tool_call(tc)))
            elif name == "statsmodels_spread_regression": data["regression"] = tool_payload(await statsmodels_spread_regression.ainvoke(_grounded_tool_call(tc)))
            elif name == "calculate_poisson_over_under": data["poisson"] = tool_payload(await calculate_poisson_over_under.ainvoke(_grounded_tool_call(tc)))
            
    print(f"\n--- TOOL DEBUG DATA (Data Science Node) ---\n{json.dumps(data, indent=2)}\n")
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
            if name == "fetch_live_odds": data["odds"] = tool_payload(await fetch_live_odds.ainvoke(_grounded_tool_call(tc)))
            elif name == "predict_matchup_winner":
                grounded_tc = _grounded_tool_call(tc)
                data["prediction"] = tool_payload(await predict_matchup_winner.ainvoke(grounded_tc))
                # Deterministically run the Monte Carlo engine on the same
                # matchup too, instead of relying on the LLM to separately
                # decide to call it. This is what feeds the Simulation tab --
                # without it, a plain "Team A vs Team B" query (which routes
                # here) never populates home/away_win_probability or
                # median_projected_score, and the Simulation tab sits on its
                # "Awaiting simulation parameters" empty state forever.
                # Reuses grounded_tc's already-corrected home/away so the
                # prediction and simulation panels can never disagree about
                # who's actually hosting.
                mc_args = grounded_tc.get("args", {}) or {}
                mc_call = {
                    "name": "run_monte_carlo_simulation",
                    "args": {
                        "home_team": mc_args.get("home_team", ""),
                        "away_team": mc_args.get("away_team", ""),
                        "sport": mc_args.get("sport", "NFL"),
                    },
                    "id": f"{tc.get('id', 'auto')}_monte_carlo",
                    "type": "tool_call",
                }
                data["monte_carlo"] = tool_payload(await run_monte_carlo_simulation.ainvoke(mc_call))
            elif name == "run_monte_carlo_simulation" and "monte_carlo" not in data:
                data["monte_carlo"] = tool_payload(await run_monte_carlo_simulation.ainvoke(_grounded_tool_call(tc)))
            
    print(f"\n--- TOOL DEBUG DATA (Odds Node) ---\n{json.dumps(data, indent=2)}\n")
    return await synthesize_final_response(state, data)

async def bankroll_node(state: SportsAgentState) -> dict:
    res = await llm.ainvoke([SystemMessage(content="You are a Risk Manager."), state["messages"][-1]])
    return {"messages": [res], "math_results": {}}

async def quant_code_node(state: SportsAgentState) -> dict:
    res = await llm.ainvoke([SystemMessage(content="You are a Quant Developer."), state["messages"][-1]])
    return {"messages": [res], "math_results": {}}

async def sports_tutor_node(state: SportsAgentState) -> dict:
    res = await llm.ainvoke([SystemMessage(content="You are a Sports Betting Instructor."), state["messages"][-1]])
    return {"messages": [res], "math_results": {}}