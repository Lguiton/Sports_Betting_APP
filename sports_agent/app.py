#import logging
import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

# Assuming these are defined in your local modules
from schemas import ChatRequest
from sports_agent.graph import sports_agent_app

# 1. Configure logging for better observability
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Sports Betting Predictor & Quantitative Analytics API", 
    description="Backend API for AI-driven sports analytics and betting predictions.",
    version="1.1.0"
)

# 2. Add CORS Middleware (Essential for Streamlit or Next.js frontends)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tip: Restrict this to your frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", tags=["Health Check"])
async def root():
    return {
        "status": "healthy",
        "message": "Sports Betting Analytics Agent API is running!"
    }

@app.post("/chat/sports", tags=["Analytics Agent"])
async def sports_chat_endpoint(request: ChatRequest):
    async def event_stream():
        try:
            logger.info("Processing chat request for thread_id=%s", request.thread_id)
            config = {"configurable": {"thread_id": request.thread_id}}
            result = await sports_agent_app.ainvoke(
                {"messages": [HumanMessage(content=request.message)]},
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
            yield "data: [DONE]\n\n"
        except Exception:
            logger.exception("Error in sports_chat_endpoint")
            yield f"data: {json.dumps({'type': 'error', 'content': 'Server stream failed.'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    # Runs the server with auto-reload enabled for development
    uvicorn.run("sports_agent.app:app", host="0.0.0.0", port=8000, reload=True)