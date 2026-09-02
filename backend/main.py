from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage
import traceback
import asyncio
import json
import re
from sports_agent.graph import sports_agent_app
from sports_agent.nodes import kelly_criterion, calculate_ev
from schemas import ChatRequest
from backend.analytics import (
    router as analytics_router,
    run_line_tracking_cycle, LINE_TRACKING_INTERVAL_MINUTES,
    run_auto_settlement_cycle, AUTO_SETTLE_INTERVAL_MINUTES,
    run_injury_sync_cycle, INJURY_SYNC_INTERVAL_MINUTES,
)


async def _line_tracking_loop():
    """Background poller for the line tracker. run_line_tracking_cycle()
    itself is a no-op until POST /line-tracking/enabled has been called, so
    this task idles harmlessly (one cheap DB read per interval) for anyone
    who never opts in -- see backend/analytics.py for why it defaults off."""
    while True:
        try:
            await asyncio.to_thread(run_line_tracking_cycle)
        except Exception:
            traceback.print_exc()
        await asyncio.sleep(LINE_TRACKING_INTERVAL_MINUTES * 60)


async def _auto_settle_loop():
    """Background poller that logs ESPN final scores into the rating
    engine and auto-grades pending moneyline bets. Defaults ON -- see
    POST /auto-settle/enabled in backend/analytics.py to turn it off."""
    while True:
        try:
            await asyncio.to_thread(run_auto_settlement_cycle)
        except Exception:
            traceback.print_exc()
        await asyncio.sleep(AUTO_SETTLE_INTERVAL_MINUTES * 60)


async def _injury_sync_loop():
    """Background poller that turns ESPN's real injury reports into
    automatic situational rating adjustments. Defaults ON -- see
    POST /injury-sync/enabled in backend/analytics.py to turn it off."""
    while True:
        try:
            await asyncio.to_thread(run_injury_sync_cycle)
        except Exception:
            traceback.print_exc()
        await asyncio.sleep(INJURY_SYNC_INTERVAL_MINUTES * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [
        asyncio.create_task(_line_tracking_loop()),
        asyncio.create_task(_auto_settle_loop()),
        asyncio.create_task(_injury_sync_loop()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()


app = FastAPI(title="Eivanta Analytics Sports Betting API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bet journal, game-result logging (feeds the Elo ratings), performance
# stats, multi-book odds comparison, and arbitrage scanning.
app.include_router(analytics_router)

@app.post("/chat/sports")
async def chat_sports(request: ChatRequest):
    async def stream_generator():
        try:
            config = {"configurable": {"thread_id": request.thread_id}}

            contextualized_message = (
                f"User Prompt: {request.message}\n\n"
                f"--- SYSTEM CONTEXT ---\n"
                f"Available Funds: ${request.bankroll}\n"
                f"Risk Tolerance: {request.risk_profile}\n\n"
                f"CRITICAL INSTRUCTIONS:\n"
                f"1. You MUST write a 2-3 sentence conversational text analysis summarizing your findings FIRST.\n"
                f"2. You MUST output a valid ```json block at the very end of your response.\n"
                f"3. YOUR JSON MUST CONTAIN EVERY SINGLE KEY LISTED IN THE EXAMPLE BELOW. NO EXCEPTIONS.\n"
                f"4. ALL JSON values MUST be flat numbers or strings.\n"
                f"5. If your tools did not provide data for a specific key, you MUST output 0 for numbers and 'N/A' for strings. Do not skip keys.\n\n"
                f"EXAMPLE PERFECT RESPONSE INCLUDING ALL DASHBOARD KEYS:\n"
                f"Summary: The Yankees are heavily favored based on recent sharp movement and Poisson metrics, showing significant edge on the over.\n"
                f"```json\n"
                f"{{\n"
                f"  \"edge_pct\": 4.2,\n"
                f"  \"best_book\": \"DraftKings\",\n"
                f"  \"expected_value\": \"+$12.50\",\n"
                f"  \"projected_total_points\": 8.21,\n"
                f"  \"over_probability_pct\": 99.97,\n"
                f"  \"edge_recommendation\": \"OVER VALUE\",\n"
                f"  \"kelly\": {{\"recommended_wager\": 50, \"bankroll_pct\": 5}}\n"
                f"}}\n"
                f"```\n\n"
                f"Now, generate your response for the user prompt using the exact KEY STRUCTURE above.\n"
                f"THE NUMBERS IN THAT EXAMPLE (4.2, 12.50, 8.21, 99.97, 50, 5, 'DraftKings') ARE PLACEHOLDERS ONLY -- "
                f"do not reuse a single one of them. Every number you output must come from your own tool calls for THIS matchup."
            )
            
            input_data = {"messages": [HumanMessage(content=contextualized_message)]}
            
            try:
                result = await asyncio.wait_for(
                    sports_agent_app.ainvoke(input_data, config=config),
                    timeout=45.0
                )
            except asyncio.TimeoutError:
                yield f"data: [ERROR]: Prediction Timeout. The analytical model took too long to respond.\n\n"
                return
            
            messages = result.get("messages", [])
            content = ""
            
            # 1. Extract the AI's text response
            if messages:
                for msg in reversed(messages):
                    msg_type = msg.get("type", "") if isinstance(msg, dict) else getattr(msg, "type", "")
                    raw_content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
                    
                    if msg_type == "ai" and raw_content:
                        content = "".join(b.get("text", "") for b in raw_content if isinstance(b, dict)) if isinstance(raw_content, list) else str(raw_content)
                        if content.strip():
                            break

            if not content.strip():
                content = "The analytical agent completed its execution but returned no final text summary."

            # 2. Extract the LLM's JSON attempt
            json_str = "{}"
            json_match = re.search(r"```json\n(.*?)\n```", content, re.DOTALL)
            
            if json_match:
                json_str = json_match.group(1)
                content = content.replace(json_match.group(0), "").strip()
            else:
                json_match_fallback = re.search(r"\{[\s\S]*\}", content)
                if json_match_fallback:
                    json_str = json_match_fallback.group(0)
                    content = content.replace(json_match_fallback.group(0), "").strip()

            # 3. Pull the REAL tool outputs for this run out of graph state.
            # Nodes hand their tool results to synthesize_final_response(),
            # which stores them in state["math_results"] -- that's the
            # actual source of truth. (An earlier version of this tried to
            # recover tool results by scanning `messages` for a "tool"-typed
            # entry; the agent graph never actually appends ToolMessages to
            # state, so that scan silently matched nothing, ever -- every
            # number the dashboard showed was the LLM's own guess.)
            tool_data = result.get("math_results") or {}

            final_json_obj = {}
            try:
                final_json_obj = json.loads(json_str)
            except Exception:
                pass

            if isinstance(tool_data.get("poisson"), dict):
                final_json_obj.update(tool_data["poisson"])
            if isinstance(tool_data.get("monte_carlo"), dict):
                final_json_obj.update(tool_data["monte_carlo"])
            if isinstance(tool_data.get("regression"), dict):
                final_json_obj.update(tool_data["regression"])
            if isinstance(tool_data.get("clv"), dict):
                final_json_obj.update(tool_data["clv"])

            # 3b. Deterministically compute win probability, expected value /
            # edge, and Kelly stake sizing from the real tool numbers above,
            # instead of trusting the LLM to do this math itself.
            # calculate_ev() and kelly_criterion() already existed in
            # sports_agent/nodes.py but nothing ever actually called them --
            # every "edge %", "expected value" and "recommended wager" the
            # dashboard showed was the model's own guess (or a copy of the
            # prompt's placeholder example numbers).
            try:
                prediction = tool_data.get("prediction") if isinstance(tool_data.get("prediction"), dict) else {}
                monte_carlo = tool_data.get("monte_carlo") if isinstance(tool_data.get("monte_carlo"), dict) else {}
                odds_data = tool_data.get("odds") if isinstance(tool_data.get("odds"), dict) else {}

                win_prob = None
                if prediction.get("win_probability"):
                    win_prob = float(str(prediction["win_probability"]).replace("%", "")) / 100
                elif monte_carlo.get("home_win_probability"):
                    win_prob = float(str(monte_carlo["home_win_probability"]).replace("%", "")) / 100

                favored_team = prediction.get("favored_team")
                american_odds = -110.0  # fallback vig when no live market price was returned
                best_book = odds_data.get("bookmaker")

                if favored_team and odds_data.get("live_markets"):
                    for market in odds_data["live_markets"]:
                        if market.get("key") != "h2h":
                            continue
                        for outcome in market.get("outcomes", []):
                            name = str(outcome.get("name", ""))
                            if name and (name.lower() in favored_team.lower() or favored_team.lower() in name.lower()):
                                try:
                                    american_odds = float(outcome["price"])
                                except (TypeError, ValueError):
                                    pass

                if win_prob is not None:
                    fraction = {"Conservative": 0.25, "Moderate": 0.5, "Aggressive": 0.75}.get(request.risk_profile, 0.5)
                    kelly = kelly_criterion(win_prob, american_odds, fraction=fraction)
                    ev = calculate_ev(win_prob, american_odds, stake=100.0)

                    final_json_obj["kelly"] = {
                        "recommended_wager": round(request.bankroll * (kelly["fractional_kelly_pct"] / 100), 2),
                        "bankroll_pct": kelly["fractional_kelly_pct"],
                    }
                    final_json_obj["edge_pct"] = ev["ev_percentage"]
                    final_json_obj["expected_value"] = f"{'+' if ev['expected_value'] >= 0 else ''}${ev['expected_value']}"
                    final_json_obj["edge_recommendation"] = "BET VALUE" if ev["ev_percentage"] > 0 else "NO EDGE"
                if best_book:
                    final_json_obj["best_book"] = best_book
            except Exception:
                pass

            # 4. Stream the text narrative cleanly
            for line in content.split("\n"):
                if line.strip():
                    yield f"data: {line} \n\n"
                    await asyncio.sleep(0.05)
            
            # 5. Stream the final, guaranteed JSON object
            clean_json = json.dumps(final_json_obj)
            yield f"data: [JSON_PAYLOAD]{clean_json}\n\n"

        except Exception as e:
            traceback.print_exc()
            yield f"data: [ERROR]: Server execution failed - {str(e)}\n\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")

# NOTE: the old /chat/odds endpoint here was a hardcoded mock (always
# returned "Yankees vs Angels" with fake prices) -- it's been replaced by the
# real GET /odds/compare and GET /arbitrage/scan endpoints in
# backend/analytics.py, which hit the actual Odds API.

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)