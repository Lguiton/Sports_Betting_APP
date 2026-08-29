from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
import traceback
import json
from sports_agent.graph import sports_agent_app
from schemas import ChatRequest

app = FastAPI(title="Sports Betting AI Agent API")

# Allow requests from the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_origin_regex=r"https?://(?:localhost|127\.0\.0\.1|172\.\d+\.\d+\.\d+):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/chat/sports")
async def chat_sports(request: ChatRequest):
    async def event_stream():
        try:
            config = {"configurable": {"thread_id": request.thread_id}}
            
            # Injecting explicit formatting rules for math and JSON constraints
            contextualized_message = (
                f"User Prompt: {request.message}\n\n"
                f"--- SYSTEM CONTEXT ---\n"
                f"Active Bankroll: ${request.bankroll}\n"
                f"Risk Profile: {request.risk_profile}\n"
                f"Formatting Rules:\n"
                f"1. For any mathematical equations, you MUST use standard Markdown delimiters: $for inline math, and$$ for block equations. NEVER use \\(\\) or \\[\\].\n"
                f"2. Ensure any structured data for widgets is output as a valid ```json block at the end of your response."
            )
            
            result = await sports_agent_app.ainvoke(
                {"messages": [HumanMessage(content=contextualized_message)]},
                config=config,
            )
            
            messages = result.get("messages", [])
            content = ""
            
            # Traverse backwards to find the last AI message that actually contains text
            # This prevents crashes when the graph ends on a tool call or empty state
            if messages:
                for msg in reversed(messages):
                    if msg.type == "ai" and getattr(msg, "content", ""):
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
                # Fallback instead of a fatal crash
                content = "The analytical agent completed its execution but returned no final text summary."

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