#import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage

# Assuming these are defined in your local modules
from schemas import ChatRequest, ChatResponse
from sports_agent.graph import sports_agent_app

# 1. Configure logging for better observability
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

@app.post("/chat/sports", response_model=ChatResponse, tags=["Analytics Agent"])
async def sports_chat_endpoint(request: ChatRequest):
    try:
        logger.info(f"Processing chat request for thread_id: {request.thread_id}")
        
        config = {"configurable": {"thread_id": request.thread_id}}
        inputs = {"messages": [HumanMessage(content=request.message)]}
        
        # 3. Upgrade to 'ainvoke' for non-blocking asynchronous execution
        result = await sports_agent_app.ainvoke(inputs, config=config)
        
        # 4. Safely extract the last message and intent
        last_message = result["messages"][-1].content
        intent = result.get("intent", "concept_explanation")
        
        return ChatResponse(
            response=last_message,
            intent=intent,
            thread_id=request.thread_id
        )
        
    except Exception as e:
        logger.error(f"Error in sports_chat_endpoint: {str(e)}", exc_info=True)
        # 5. Mask raw exceptions from the client while logging the full trace
        raise HTTPException(
            status_code=500, 
            detail="An internal error occurred while processing the sports analytics request."
        )

if __name__ == "__main__":
    import uvicorn
    # Runs the server with auto-reload enabled for development
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)