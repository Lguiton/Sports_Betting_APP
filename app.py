from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
import traceback
import json
from sports_agent.graph import sports_agent_app

app = FastAPI(title="Sports Betting AI Agent API")

# Allow requests from the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default_session"
    bankroll: float = 1000.0
    risk_profile: str = "Moderate"

@app.post("/chat/sports")
async def chat_sports(request: ChatRequest):
    async def event_stream():
        try:
            config = {"configurable": {"thread_id": request.thread_id}}
            
            contextualized_message = (
                f"[System Context - Active Bankroll: ${request.bankroll}, "
                f"Risk Profile: {request.risk_profile}]\n"
                f"User Prompt: {request.message}"
            )
            
            result = await sports_agent_app.ainvoke(
                {"messages": [HumanMessage(content=contextualized_message)]},
                config=config,
            )
            messages = result.get("messages", [])
            content = getattr(messages[-1], "content", "") if messages else ""
            if isinstance(content, list):
                content = "".join(
                    block.get("text", "") for block in content if isinstance(block, dict)
                )
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("Agent returned an empty response")
            yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"
            
            # Signal to the frontend that the stream is complete
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            print("\n" + "=" * 50)
            print("🚨 DETAILED SERVER ERROR TRACEBACK:")
            traceback.print_exc()
            print("=" * 50 + "\n")
            yield f"data: {json.dumps({'type': 'error', 'content': 'Server stream failed.'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
