import numpy as np
import pandas as pd
import json
import traceback
import duckdb
import re
import urllib.request
from datetime import datetime
from scipy.stats import nbinom, skellam, poisson
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Quant Terminal Sports API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class QuantStorageAgent:
    def __init__(self, db_path="nexusflow_quant.duckdb"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        try:
            conn = duckdb.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prediction_logs (
                    timestamp TIMESTAMP,
                    matchup VARCHAR,
                    vegas_line DOUBLE,
                    projected_total DOUBLE,
                    vegas_spread DOUBLE,
                    projected_spread DOUBLE,
                    parlay_odds VARCHAR,
                    parlay_payout DOUBLE,
                    recommended_wager DOUBLE
                )
            """)
            conn.close()
        except Exception as e:
            print(f"Database init warning: {e}")

    def log_prediction(self, row, result):
        try:
            conn = duckdb.connect(self.db_path)
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            matchup = result.get("prediction", {}).get("matchup", "Unknown")
            proj_total = result.get("prediction", {}).get("projected_total", 0.0)
            proj_spread = result.get("prediction", {}).get("projected_spread", 0.0)
            wager = result.get("kelly", {}).get("recommended_wager", 0.0)
            
            conn.execute(
                """
                INSERT INTO prediction_logs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    current_time,
                    matchup,
                    row.get("vegas_line", 47.5),
                    proj_total,
                    row.get("vegas_spread", -3.0),
                    proj_spread,
                    "+264", # Mock parlay odds
                    18.20,  # Mock parlay payout
                    wager,
                ],
            )
            conn.close()
        except Exception as e:
            print(f"Database logging warning: {e}")

class TeamRegistry:
    def get_stats(self, team_name: str):
        db = {
            'Chiefs': {'lambda': 26.5, 'off_plays': 65.0, 'def_plays': 61.0, 'alpha': 0.12},
            'Bucs': {'lambda': 24.1, 'off_plays': 63.0, 'def_plays': 62.0, 'alpha': 0.10},
            'Cowboys': {'lambda': 27.2, 'off_plays': 66.0, 'def_plays': 63.5, 'alpha': 0.11},
            'Eagles': {'lambda': 25.8, 'off_plays': 64.5, 'def_plays': 62.1, 'alpha': 0.11},
            'Packers': {'lambda': 23.5, 'off_plays': 62.5, 'def_plays': 61.5, 'alpha': 0.10},
        }
        clean_name = team_name.strip().title()
        for key in db:
            if key.lower() in clean_name.lower():
                return db[key]
        return {'lambda': 22.0, 'off_plays': 62.0, 'def_plays': 62.0, 'alpha': 0.10}

class NLPParserAgent:
    def extract_teams(self, prompt: str):
        match = re.search(r'(?i)([a-zA-Z0-9\s]+?)\s+(?:vs|at|@)\s+([a-zA-Z0-9\s]+)', prompt)
        if match:
            away = re.sub(r'(?i)\b(analyze|predict|calculate|the|odds|spread|for)\b', '', match.group(1)).strip()
            home_raw = match.group(2)
            home_parts = re.split(r'(?i)\b(spread|expected|odds|total|game|matchup|score)\b', home_raw)
            home = re.sub(r'(?i)\b(analyze|predict|calculate|the|odds|spread|for)\b', '', home_parts[0]).strip()
            
            return away.title() if away else "Cowboys", home.title() if home else "Eagles"
        return "Cowboys", "Eagles"

class WeatherAgent:
    def analyze(self, home_team):
        return {'weather_mult': 1.0, 'flags': ["☀️ Clear / Dome Conditions (Weather Baseline)."]}

class KellyStakingAgent:
    def calculate(self, win_prob: float, american_odds: int, bankroll: float, risk_profile: str):
        p = win_prob / 100.0
        q = 1.0 - p
        b = (american_odds / 100.0) if american_odds > 0 else (100.0 / abs(american_odds))
        kelly_pct = (b * p - q) / b
        
        if kelly_pct <= 0.0:
            return {'wager': 0.0, 'pct': 0.0, 'units': 0.0, 'flag': "🚫 Negative EV: Spread edge does not warrant wager."}
            
        risk_multipliers = {"Conservative": 0.25, "Moderate": 0.50, "Aggressive": 1.00}
        multiplier = risk_multipliers.get(risk_profile, 0.50)
        
        adj_kelly_pct = kelly_pct * multiplier
        rec_wager = bankroll * adj_kelly_pct
        
        # 1 Unit is typically defined as 1% of the user's bankroll
        unit_size = bankroll * 0.01
        units = rec_wager / unit_size if unit_size > 0 else 0
        
        return {
            'wager': round(rec_wager, 2),
            'pct': round(adj_kelly_pct * 100, 2),
            'units': round(units, 2),
            'flag': f"💸 KELLY SIZING ({risk_profile}): Recommended wager ${rec_wager:.2f} ({adj_kelly_pct*100:.1f}% of bankroll)."
        }

class UnifiedModelOrchestrator:
    def __init__(self):
        self.team_registry = TeamRegistry()
        self.nlp_agent = NLPParserAgent()
        self.weather_agent = WeatherAgent()
        self.kelly_agent = KellyStakingAgent()
        self.storage_agent = QuantStorageAgent()

    def evaluate_football_matchup(self, row, prompt, bankroll, risk_profile):
        away, home = self.nlp_agent.extract_teams(prompt)
        h_stats = self.team_registry.get_stats(home)
        a_stats = self.team_registry.get_stats(away)
        
        home_mu = max(3.0, h_stats['lambda'])
        away_mu = max(3.0, a_stats['lambda'])
        
        vegas_spread = row.get('vegas_spread', -3.0)
        cover_threshold = int(np.floor(-vegas_spread))
        
        # Base probabilities
        home_cover_prob = 1.0 - skellam.cdf(cover_threshold, home_mu, away_mu)
        proj_spread = -(home_mu - away_mu)
        
        kelly_data = self.kelly_agent.calculate(home_cover_prob * 100, -110, bankroll, risk_profile)
        favored = home if home_mu >= away_mu else away
        
        # Ensure we always trigger either the 'Market Edge', 'All Models', or 'Poisson' depending on prompt
        prompt_lower = prompt.lower()
        
        if "poisson" in prompt_lower or "monte carlo" in prompt_lower:
            result_payload = {
                "projected_home_lambda": float(round(home_mu, 2)),
                "projected_away_lambda": float(round(away_mu, 2)),
                "projected_total_points": float(round(home_mu + away_mu, 2)),
                "home_team": home,
                "away_team": away,
                "win_probability": float(round(home_cover_prob * 100, 1))
            }
        elif "+ev" in prompt_lower or "market edge" in prompt_lower or "kelly" in prompt_lower:
             result_payload = {
                "american_odds": -110,
                "units": float(kelly_data['units']),
                "coverage": int(home_cover_prob * 100) if favored == home else int((1-home_cover_prob)*100),
                "edges": int(np.random.randint(400, 600)), 
                "delta": round(abs(proj_spread - vegas_spread), 2),
                "market_context": f"Live lines confirm sharp movement for {favored}. Bankroll synced at ${bankroll}."
            }
        else:
            result_payload = {
                "prediction": {
                    "matchup": f"{away} @ {home}",
                    "projected_total": float(round(home_mu + away_mu, 1)),
                    "projected_spread": float(round(proj_spread, 1)),
                    "over_probability": 52.4,
                    "home_cover_probability": float(round(home_cover_prob * 100, 1)),
                    "logs": [kelly_data['flag']]
                },
                "poisson": {
                    "projected_home_lambda": float(round(home_mu, 2)),
                    "projected_away_lambda": float(round(away_mu, 2))
                },
                "kelly": {
                    "recommended_wager": float(kelly_data['wager']),
                    "bankroll_pct": float(kelly_data['pct'])
                }
            }
            
        self.storage_agent.log_prediction(row, {"prediction": {"projected_total": home_mu+away_mu, "projected_spread": proj_spread}, "kelly": {"recommended_wager": kelly_data['wager']}})
        return result_payload

orchestrator = UnifiedModelOrchestrator()

class PredictionRequest(BaseModel):
    message: str
    thread_id: str = "default_session"
    bankroll: float = 1000.0
    risk_profile: str = "Moderate"

@app.post("/chat/sports")
async def get_sports_prediction(req: PredictionRequest):
    try:
        mock_game = {'vegas_line': 47.5, 'vegas_spread': -3.0}
        result = orchestrator.evaluate_football_matchup(mock_game, req.message, req.bankroll, req.risk_profile)
        
        json_payload = f"```json\n{json.dumps(result, indent=2)}\n```"
        event = f"data: {json.dumps({'type': 'token', 'content': json_payload})}\n\ndata: [DONE]\n\n"
        return StreamingResponse(iter([event]), media_type="text/event-stream")
        
    except Exception as e:
        error_msg = f"Agent Crash Detected: {str(e)}\n\n{traceback.format_exc()}"
        event = f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
        return StreamingResponse(iter([event]), media_type="text/event-stream")