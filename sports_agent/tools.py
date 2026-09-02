import requests
import random
import duckdb
from langchain_core.tools import tool
from config import ODDS_API_KEY

@tool
def fetch_live_odds(home_team: str, away_team: str, sport_key: str = "americanfootball_nfl") -> dict:
    """
    Fetches real-time Vegas odds (moneyline, spread, totals) from live sportsbooks for a specific matchup.
    Args:
        home_team: The name of the home team (e.g., 'Chiefs').
        away_team: The name of the away team (e.g., 'Ravens').
        sport_key: The Odds API sport key (e.g., 'americanfootball_nfl', 'baseball_mlb', 'basketball_nba', 'americanfootball_ncaaf').
    """
    if not ODDS_API_KEY:
        return {"error": "API Key Error: ODDS_API_KEY is missing from environment variables."}
        
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "american",
        "bookmakers": "draftkings"
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        games = response.json()
        
        for game in games:
            live_home = game.get("home_team", "").lower()
            live_away = game.get("away_team", "").lower()
            
            if home_team.lower() in live_home or live_away in home_team.lower() or away_team.lower() in live_away or live_away in away_team.lower():
                if not game.get("bookmakers"):
                    continue
                
                book = game["bookmakers"][0]
                return {
                    "matchup": f"{game['away_team']} @ {game['home_team']}",
                    "start_time": game["commence_time"],
                    "bookmaker": book["title"],
                    "live_markets": book.get("markets", [])
                }
                
        return {"error": f"Matchup not found on active slate: {away_team} at {home_team}."}
        
    except Exception as e:
        return {"error": f"Live Odds API request failed: {str(e)}"}

@tool
def predict_matchup_winner(home_team: str, away_team: str, sport: str = "NFL") -> dict:
    """
    Predicts game outcome and win probabilities from each team's Glicko-2
    power rating (rating + confidence + rest days + any logged situational
    notes -- see sports_agent/ratings.py). Ratings start neutral (1500,
    wide uncertainty) and only move when you log real results via
    POST /games/result -- so predictions get sharper the more games you log,
    instead of being a coin flip forever. Every call is logged for later
    backtesting -- see GET /calibration.
    """
    from sports_agent.ratings import win_probability_breakdown, normalize_sport, log_prediction

    b = win_probability_breakdown(sport, home_team, away_team)
    home_prob = b["home_win_probability"] / 100.0
    away_prob = b["away_win_probability"] / 100.0

    # Score baselines still use sport-typical ranges, but now nudged toward
    # the favored side in proportion to the real rating edge, instead of
    # being drawn completely independently of who the model favors.
    sport_upper = normalize_sport(sport)
    edge = home_prob - 0.5  # roughly -0.5 (huge underdog) .. +0.5 (huge favorite)
    # base_h/base_a start EQUAL, same reasoning as run_monte_carlo_simulation
    # above -- home-field advantage already lives in `edge` via
    # win_probability_breakdown(), so a baked-in base_h > base_a here would
    # double-count it in the displayed projected score.
    if sport_upper == "MLB":
        base_h, base_a, spread = 4.35, 4.35, 3.0
    elif sport_upper == "NBA":
        base_h, base_a, spread = 110.0, 110.0, 14.0
    elif sport_upper == "NCAAF":
        base_h, base_a, spread = 26.0, 26.0, 15.0
    else:  # NFL
        base_h, base_a, spread = 22.0, 22.0, 12.0

    home_score = round(max(0.0, base_h + edge * spread + random.uniform(-spread * 0.15, spread * 0.15)), 1)
    away_score = round(max(0.0, base_a - edge * spread + random.uniform(-spread * 0.15, spread * 0.15)), 1)

    favored = home_team if home_prob >= away_prob else away_team
    confidence = round(max(home_prob, away_prob) * 100, 1)

    try:
        log_prediction(sport, home_team, away_team, b["home_win_probability"], favored, source="prediction")
    except Exception:
        pass  # never let telemetry logging break a live prediction

    return {
        "prediction_target": f"{home_team} vs {away_team}",
        "favored_team": favored,
        "win_probability": f"{confidence}%",
        "home_win_probability": f"{round(home_prob * 100, 1)}%",
        "away_win_probability": f"{round(away_prob * 100, 1)}%",
        "projected_score": f"{home_team} {home_score} - {away_team} {away_score}",
        "home_power_rating": b["home_rating"],
        "away_power_rating": b["away_rating"],
        "home_confidence": b["home_confidence"],
        "away_confidence": b["away_confidence"],
        "home_rest_days": b["home_rest_days"],
        "away_rest_days": b["away_rest_days"],
        "situational_notes": (b["home_situational_notes"] or []) + (b["away_situational_notes"] or []),
    }

@tool
def run_monte_carlo_simulation(home_team: str, away_team: str, sport: str = "NFL", iterations: int = 10000) -> dict:
    """
    Simulates a matchup 10,000 times using each team's Glicko-2 power rating
    (see ratings.py) to bias the per-game scoring distributions, then
    projects win probabilities and a median score. Ratings start neutral
    (1500), so an unlogged matchup simulates as a true toss-up and gets
    sharper the more real results you log via POST /games/result.
    """
    from sports_agent.ratings import win_probability, normalize_sport

    home_wins = 0
    away_wins = 0
    home_scores = []
    away_scores = []

    # Glicko-2-implied win probability sets how far the scoring means get
    # pulled toward the favored side -- so this stays consistent with
    # predict_matchup_winner instead of drawing independent random noise.
    home_prob = win_probability(sport, home_team, away_team)
    edge = home_prob - 0.5  # -0.5 (big underdog) .. +0.5 (big favorite)

    # Dynamic Variance Settings (Mean, Standard Deviation). mu_h and mu_a
    # start EQUAL -- home-field advantage must come from `edge` alone
    # (win_probability() already adds a real home_adv rating bonus, plus
    # each team's actual rating gap, rest days, and situational
    # adjustments). An earlier version had mu_h hardcoded higher than
    # mu_a here too, which double-counted home-field advantage on top of
    # win_probability()'s own home_adv and, worse, ate a large fixed
    # share of `spread`'s budget before `edge` ever got applied -- so even
    # a real, well-established rating edge for the away team barely
    # moved the simulated win rate off of "home favored." Confirmed live:
    # two still-unrated MLB teams (a true 51.9% Glicko toss-up) were
    # simulating as a 58% home favorite.
    sport_upper = normalize_sport(sport)
    if sport_upper == "MLB":
        mu_h, sig_h, mu_a, sig_a, spread = 4.5, 2.5, 4.5, 2.2, 2.5
    elif sport_upper == "NBA":
        mu_h, sig_h, mu_a, sig_a, spread = 110.5, 12.0, 110.5, 11.5, 16.0
    elif sport_upper == "NCAAF":
        mu_h, sig_h, mu_a, sig_a, spread = 27.5, 10.5, 27.5, 9.5, 17.0
    else:  # Default NFL
        mu_h, sig_h, mu_a, sig_a, spread = 23.0, 6.2, 23.0, 5.8, 10.0

    mu_h += edge * spread
    mu_a -= edge * spread

    for _ in range(iterations):
        # round(), not int(): truncation systematically biased every score
        # ~0.5 points low on average (e.g. int(24.9) == 24), skewing the
        # displayed median score for both teams without affecting the win
        # probabilities themselves.
        h_score = max(0, round(random.normalvariate(mu_h, sig_h)))
        a_score = max(0, round(random.normalvariate(mu_a, sig_a)))
        
        home_scores.append(h_score)
        away_scores.append(a_score)
        
        if h_score > a_score:
            home_wins += 1
        elif a_score > h_score:
            away_wins += 1
        else:
            home_wins += 0.5
            away_wins += 0.5

    h_prob = round((home_wins / iterations) * 100, 1)
    a_prob = round((away_wins / iterations) * 100, 1)
    
    return {
        "simulation_runs": iterations,
        "matchup": f"{home_team} vs {away_team}",
        "home_win_probability": f"{h_prob}%",
        "away_win_probability": f"{a_prob}%",
        "median_projected_score": f"{home_team} {round(sum(home_scores)/iterations, 1)} - {away_team} {round(sum(away_scores)/iterations, 1)}"
    }

@tool
def calculate_clv(wager_odds: float, closing_odds: float) -> dict:
    """Tracks Closing Line Value (CLV) to evaluate whether a predictive model beats market closing prices."""
    diff = closing_odds - wager_odds
    beating_market = diff > 0 or (wager_odds < 0 and closing_odds < wager_odds)
    return {
        "wager_odds": wager_odds,
        "closing_odds": closing_odds,
        "clv_differential": diff,
        "beating_closing_line": beating_market,
        "status": "Positive CLV (Sharp Edge Verified)" if beating_market else "Negative CLV (Line Movement Against Position)"
    }    

@tool
def statsmodels_spread_regression(net_epa: float, net_success: float, pass_rush_diff: float) -> dict:
    """Runs a statsmodels OLS regression on efficiency metrics."""
    import pandas as pd
    import statsmodels.formula.api as smf

    training_data = pd.DataFrame({
        "score_differential": [3, -7, 14, 0, 10, -3, 7, 14, -10, 4],
        "net_epa_per_play": [0.12, -0.08, 0.25, 0.01, 0.15, -0.05, 0.09, 0.22, -0.15, 0.04],
        "net_success_rate": [0.05, -0.04, 0.09, 0.0, 0.06, -0.02, 0.03, 0.08, -0.07, 0.01],
        "pass_rush_win_rate_diff": [0.04, -0.05, 0.08, 0.01, 0.06, -0.03, 0.02, 0.07, -0.06, 0.0],
        "turnover_differential": [1, -2, 0, 1, 2, -1, 0, 1, -2, 0]
    })

    formula = "score_differential ~ net_epa_per_play + net_success_rate + pass_rush_win_rate_diff + turnover_differential"
    model = smf.ols(formula=formula, data=training_data).fit()

    pred_data = pd.DataFrame([{
        "net_epa_per_play": net_epa,
        "net_success_rate": net_success,
        "pass_rush_win_rate_diff": pass_rush_diff,
        "turnover_differential": 0.0
    }])

    summary_frame = model.get_prediction(pred_data).summary_frame(alpha=0.05)

    return {
        "r_squared": round(model.rsquared, 4),
        "projected_spread": round(summary_frame["mean"].iloc[0], 2),
        "confidence_interval_lower": round(summary_frame["obs_ci_lower"].iloc[0], 2),
        "confidence_interval_upper": round(summary_frame["obs_ci_upper"].iloc[0], 2),
        "p_values": {k: round(v, 4) for k, v in model.pvalues.to_dict().items()}
    }

@tool
def calculate_poisson_over_under(home_off_epa: float, away_def_epa: float, 
                                 away_off_epa: float, home_def_epa: float, 
                                 vegas_line: float, sport: str = "NFL", home_field_adv: float = 2.5) -> dict:
    """
    Fits a Poisson GLM regression on efficiency metrics and adapts baseline training data based on the sport.
    """
    import pandas as pd
    import numpy as np
    import statsmodels.formula.api as smf
    from scipy.stats import poisson

    # Dynamic Training Data Baselines
    sport_upper = sport.upper()
    if "MLB" in sport_upper or "BASEBALL" in sport_upper:
        base_home = [4, 5, 3, 6, 2, 7, 4, 3, 5, 8]
        base_away = [3, 2, 4, 3, 5, 2, 6, 4, 3, 2]
        max_points = 25
    elif "NBA" in sport_upper or "BASKETBALL" in sport_upper:
        base_home = [110, 105, 120, 115, 108, 112, 100, 125, 118, 104]
        base_away = [105, 110, 100, 112, 115, 108, 120, 102, 111, 106]
        max_points = 280
    else: # NFL
        base_home = [24, 17, 31, 14, 27, 20, 35, 10, 28, 21]
        base_away = [17, 24, 13, 21, 17, 28, 14, 27, 20, 24]
        max_points = 65

    training_data = pd.DataFrame({
        "home_points": base_home,
        "away_points": base_away,
        "home_off_epa": [0.10, -0.05, 0.20, -0.10, 0.15, 0.02, 0.25, -0.15, 0.18, 0.05],
        "away_def_epa": [-0.02, 0.08, -0.12, 0.05, -0.04, 0.03, -0.15, 0.10, -0.08, 0.01],
        "away_off_epa": [0.05, 0.12, -0.08, 0.15, -0.02, 0.10, -0.05, 0.18, 0.02, 0.08],
        "home_def_epa": [-0.05, -0.10, 0.04, -0.08, 0.02, -0.05, 0.08, -0.12, -0.01, -0.04],
        "home_field_adv": [1.0] * 10
    })

    home_model = smf.poisson("home_points ~ home_off_epa + away_def_epa", data=training_data).fit(disp=0)
    away_model = smf.poisson("away_points ~ away_off_epa + home_def_epa", data=training_data).fit(disp=0)

    upcoming = pd.DataFrame([{
        "home_off_epa": home_off_epa,
        "away_def_epa": away_def_epa,
        "away_off_epa": away_off_epa,
        "home_def_epa": home_def_epa,
        "home_field_adv": home_field_adv
    }])

    pred_home_lambda = float(home_model.predict(upcoming).iloc[0])
    pred_away_lambda = float(away_model.predict(upcoming).iloc[0])

    matrix = np.outer(
        poisson.pmf(np.arange(max_points), pred_home_lambda),
        poisson.pmf(np.arange(max_points), pred_away_lambda)
    )

    over_prob = 0.0
    under_prob = 0.0

    for h in range(max_points):
        for a in range(max_points):
            total = h + a
            if total > vegas_line:
                over_prob += matrix[h, a]
            elif total < vegas_line:
                under_prob += matrix[h, a]

    return {
        "projected_home_lambda": round(pred_home_lambda, 2),
        "projected_away_lambda": round(pred_away_lambda, 2),
        "projected_total_points": round(pred_home_lambda + pred_away_lambda, 2),
        "vegas_line": vegas_line,
        "over_probability_pct": round(over_prob * 100, 2),
        "under_probability_pct": round(under_prob * 100, 2),
        "edge_recommendation": "OVER VALUE" if over_prob > 0.524 else ("UNDER VALUE" if under_prob > 0.524 else "NO CLEAR EDGE")
    }

@tool
def log_wager_to_duckdb(sport: str, matchup: str, recommended_wager: float, kelly_percentage: float, predicted_winner: str, vegas_line: float) -> dict:
    """
    Logs the agent's final prediction and Kelly wager sizing to the local DuckDB telemetry database.
    This MUST be called after all other models have run and a final wager is calculated.
    """
    try:
        # Pointing to the new directory we just made with mkdir
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
        ''', (sport, matchup, recommended_wager, kelly_percentage, predicted_winner, vegas_line))
        conn.close()
        return {"status": "success", "message": f"Successfully logged {matchup} prediction to DuckDB."}
    except Exception as e:
        return {"error": f"Database logging failed: {str(e)}"}