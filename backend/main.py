from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage, AIMessage
import traceback
import asyncio
from sports_agent.graph import sports_agent_app
from schemas import ChatRequest

app = FastAPI(title="Eivanta Analytics Sports Betting API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/chat/sports")
async def chat_sports(request: ChatRequest):
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
            f"3. YOUR JSON MUST CONTAIN EVERY SINGLE KEY LISTED BELOW. NO EXCEPTIONS.\n"
            f"4. ALL JSON values MUST be flat numbers or strings. You are STRICTLY FORBIDDEN from using nested objects or lists (except for the 'kelly' dictionary).\n"
            f"5. If your tools did not provide data for a specific key, you MUST output 0 for numbers and 'N/A' for strings. Do not skip keys.\n\n"
            f"EXAMPLE PERFECT RESPONSE INCLUDING ALL DASHBOARD KEYS:\n"
            f"Summary: The market and simulation data suggest the following insights based on recent sharp movement and Poisson metrics.\n"
            f"```json\n"
            f"{{\n"
            f"  \"american_odds\": -110,\n"
            f"  \"units\": 2.5,\n"
            f"  \"coverage\": 55,\n"
            f"  \"edges\": 12,\n"
            f"  \"market_context\": \"Sharp money moving...\",\n"
            f"  \"projected_home_lambda\": 24.1,\n"
            f"  \"projected_away_lambda\": 21.0,\n"
            f"  \"projected_total_points\": 45.1,\n"
            f"  \"home_team\": \"Cowboys\",\n"
            f"  \"away_team\": \"Eagles\",\n"
            f"  \"win_probability\": 64.5,\n"
            f"  \"kelly\": {{\"recommended_wager\": 50, \"bankroll_pct\": 4.8}},\n"
            f"  \"prediction_target\": \"Cowboys vs Eagles\",\n"
            f"  \"favored_team\": \"Cowboys\",\n"
            f"  \"projected_score\": \"Cowboys 30.3 - Eagles 23.8\",\n"
            f"  \"market_edge\": \"+2.5% projected edge against closing line value.\"\n"
            f"}}\n"
            f"```\n\n"
            f"Now, generate your response for the user prompt using the exact format above."
        )
        
        input_data = {"messages": [HumanMessage(content=contextualized_message)]}
        
        try:
            result = await asyncio.wait_for(
                sports_agent_app.ainvoke(input_data, config=config),
                timeout=45.0
            )
        except asyncio.TimeoutError:
            print("\n🚨 ERROR: LangGraph agent execution timed out.")
            return {
                "type": "error", 
                "content": "Prediction Timeout: The analytical model took too long to respond. Ensure your OpenAI API key is valid and network connectivity is stable."
            }
        
        messages = result.get("messages", [])
        content = ""
        
        if messages:
            for msg in reversed(messages):
                if getattr(msg, "type", "") == "ai" and getattr(msg, "content", ""):
                    raw_content = msg.content
                    if isinstance(raw_content, list):
                        content = "".join(
                            block.get("text", "") for block in raw_content if isinstance(block, dict) and "text" in block
                        )
                    else:
                        content = str(raw_content)
                    
                    if content.strip():
                        break

        if not content.strip():
            content = "The analytical agent completed its execution but returned no final text summary."

        return {"type": "token", "content": content}

    except Exception as e:
        print("\n" + "=" * 50)
        print("🚨 DETAILED SERVER ERROR TRACEBACK:")
        traceback.print_exc()
        print("=" * 50 + "\n")
        return {"type": "error", "content": f"Server execution failed: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)