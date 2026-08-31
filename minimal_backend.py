from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/chat/sports")
async def mock_chat_sports():
    response = {
        "metrics": {
            "american_odds": -110,
            "units": 3.5,
            "coverage": 70,
            "edges": 20,
            "market_context": "Sharp action detected for the home team.",
            "projected_home_lambda": 27.0,
            "projected_away_lambda": 24.5,
            "projected_total_points": 51.5,
            "home_team": "Cowboys",
            "away_team": "Eagles",
            "win_probability": 67.2,
            "kelly": {
                "recommended_wager": 48,
                "bankroll_pct": 4.8
            }
        },
        "narrative": "The Cowboys are favored due to strong offense and solid defense. The Eagles lack key players impacting their performance."
    }
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
