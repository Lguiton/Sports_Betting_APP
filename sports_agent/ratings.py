"""
Self-updating power-rating system -- Glicko-2 (rating + rating deviation +
volatility), not plain Elo.

There is no historical dataset baked into this app -- every team starts
neutral at 1500 with maximum uncertainty (RD 350). Ratings only move when you
log a real completed game's score via POST /games/result
(backend/analytics.py). The more results you log, the sharper and more
*confident* predict_matchup_winner's win probabilities get.

Why Glicko-2 instead of plain Elo:
  - Elo treats a team that's played 50 games and a team that's played 1 game
    identically once they land on the same rating number. Glicko-2 tracks a
    Rating Deviation (RD) alongside the rating -- a brand new team's RD
    starts wide (350) and narrows as it plays, so the model can express "I
    don't know yet" instead of pretending false precision.
  - RD also widens again the longer a team goes unplayed (see
    _apply_inactivity_decay), so a rating from last spring doesn't get used
    with the same confidence as one from last week.
  - win_probability() folds both teams' RD into the matchup: two teams with
    wide, uncertain ratings produce a probability pulled closer to a
    toss-up than the same rating gap would with two well-established teams.

On top of the rating engine itself, two situational adjustments feed into
win_probability() using data this app already owns:
  - Rest days, computed from each team's own logged game_results history
    (no external schedule feed needed).
  - Manual situational adjustments (team_status table) -- e.g. "starting QB
    out" -- that you log yourself with an optional expiry, since there's no
    injury-report data source wired in.
"""
import math
from datetime import date, datetime, timedelta
from typing import Optional

import duckdb

DB_PATH = "data/telemetry.duckdb"

# --- Glicko-2 constants -----------------------------------------------
GLICKO_SCALE = 173.7178
DEFAULT_RATING = 1500.0
DEFAULT_RD = 350.0
DEFAULT_VOLATILITY = 0.06
TAU = 0.5          # system constant -- controls how much volatility can change per update
RD_FLOOR = 30.0     # never let the model claim more confidence than this
RD_MAX = 350.0      # matches the "brand new team" starting uncertainty
# Calibrated so an RD sitting at the floor drifts back up to RD_MAX after
# roughly a year (365 days) of not logging a game for that team.
_INACTIVITY_C = math.sqrt((RD_MAX ** 2 - RD_FLOOR ** 2) / 365.0)

# Home-field advantage (rating points) and situational tuning per sport.
# MLB plays far more games than NFL/NCAAF, so its ratings should move more
# slowly per game or a couple of good/bad weeks would swing a team wildly.
SPORT_PARAMS = {
    "NFL":   {"home_adv": 55.0, "margin_cap": 35.0, "rest_pts_per_day": 4.0, "rest_cap": 20.0},
    "NBA":   {"home_adv": 100.0, "margin_cap": 30.0, "rest_pts_per_day": 6.0, "rest_cap": 25.0},
    "MLB":   {"home_adv": 24.0, "margin_cap": 10.0, "rest_pts_per_day": 2.0, "rest_cap": 10.0},
    "NCAAF": {"home_adv": 65.0, "margin_cap": 40.0, "rest_pts_per_day": 4.0, "rest_cap": 20.0},
}
DEFAULT_PARAMS = {"home_adv": 50.0, "margin_cap": 30.0, "rest_pts_per_day": 3.0, "rest_cap": 15.0}

# Manual situational adjustments (team_status) are clamped to this range so
# a fat-fingered entry can't send a matchup prediction to 0% or 100%.
STATUS_ADJUSTMENT_CAP = 150.0


def normalize_sport(sport: str) -> str:
    s = (sport or "").upper()
    # Check NCAAF before the generic NFL/"FOOTBALL" match below, or "COLLEGE
    # FOOTBALL" / "CFB" would get misclassified as NFL.
    if "NCAA" in s or "CFB" in s or "COLLEGE FOOTBALL" in s:
        return "NCAAF"
    if "NBA" in s or "BASKETBALL" in s:
        return "NBA"
    if "MLB" in s or "BASEBALL" in s:
        return "MLB"
    if "NFL" in s or "FOOTBALL" in s:
        return "NFL"
    return s or "NFL"


def _sport_params(sport: str) -> dict:
    return SPORT_PARAMS.get(normalize_sport(sport), DEFAULT_PARAMS)


def _connect():
    conn = duckdb.connect(DB_PATH)
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS team_ratings (
            sport VARCHAR,
            team VARCHAR,
            rating DOUBLE,
            games_played INTEGER,
            last_updated TIMESTAMP,
            PRIMARY KEY (sport, team)
        )
        """
    )
    # Glicko-2 columns, added in place so ratings logged before this upgrade
    # keep their rating/games_played history instead of being reset.
    for col, ddl in [
        ("rd", "DOUBLE DEFAULT 350.0"),
        ("volatility", "DOUBLE DEFAULT 0.06"),
        ("last_game_date", "DATE"),
    ]:
        try:
            conn.execute(f"ALTER TABLE team_ratings ADD COLUMN IF NOT EXISTS {col} {ddl}")
        except duckdb.Error:
            pass  # older DuckDB without IF NOT EXISTS support; column likely already exists

    conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_game_results_id START 1")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS game_results (
            id INTEGER DEFAULT nextval('seq_game_results_id') PRIMARY KEY,
            sport VARCHAR,
            home_team VARCHAR,
            away_team VARCHAR,
            home_score DOUBLE,
            away_score DOUBLE,
            home_rating_before DOUBLE,
            away_rating_before DOUBLE,
            home_rating_after DOUBLE,
            away_rating_after DOUBLE,
            game_date DATE,
            logged_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )

    conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_team_status_id START 1")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS team_status (
            id INTEGER DEFAULT nextval('seq_team_status_id') PRIMARY KEY,
            sport VARCHAR,
            team VARCHAR,
            adjustment DOUBLE,
            note VARCHAR,
            expires_at DATE,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )
    # 'source' distinguishes entries you typed yourself ('manual', the
    # default) from ones written automatically by the ESPN injury sync
    # ('espn_auto') -- see ratings.replace_auto_team_status -- so the
    # automatic sync can safely delete-and-replace only its own rows on
    # every run without ever touching something you entered by hand.
    try:
        conn.execute("ALTER TABLE team_status ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'manual'")
    except duckdb.Error:
        pass

    conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_model_predictions_id START 1")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS model_predictions (
            id INTEGER DEFAULT nextval('seq_model_predictions_id') PRIMARY KEY,
            sport VARCHAR,
            home_team VARCHAR,
            away_team VARCHAR,
            home_win_probability DOUBLE,
            favored_team VARCHAR,
            source VARCHAR,
            created_at TIMESTAMP DEFAULT current_timestamp,
            resolved BOOLEAN DEFAULT FALSE,
            actual_winner VARCHAR,
            correct BOOLEAN,
            resolved_at TIMESTAMP
        )
        """
    )


# --- Glicko-2 core math --------------------------------------------------

def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi ** 2 / math.pi ** 2)


def _expectation(mu: float, mu_j: float, phi_j: float) -> float:
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def _to_glicko2_scale(rating: float, rd: float) -> tuple[float, float]:
    return (rating - DEFAULT_RATING) / GLICKO_SCALE, rd / GLICKO_SCALE


def _from_glicko2_scale(mu: float, phi: float) -> tuple[float, float]:
    return GLICKO_SCALE * mu + DEFAULT_RATING, GLICKO_SCALE * phi


def _new_volatility(phi: float, delta: float, v: float, sigma: float, tau: float = TAU) -> float:
    """Illinois algorithm for solving the Glicko-2 volatility update (the
    step every reference implementation cites as the fiddly part)."""
    a = math.log(sigma ** 2)

    def f(x: float) -> float:
        ex = math.exp(x)
        num = ex * (delta ** 2 - phi ** 2 - v - ex)
        den = 2.0 * (phi ** 2 + v + ex) ** 2
        return (num / den) - ((x - a) / (tau ** 2))

    A = a
    if delta ** 2 > phi ** 2 + v:
        B = math.log(delta ** 2 - phi ** 2 - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
            if k > 100:  # safety valve -- should never trigger in practice
                break
        B = a - k * tau

    fA, fB = f(A), f(B)
    for _ in range(100):
        if abs(B - A) <= 1e-6:
            break
        C = A + (A - B) * fA / (fB - fA)
        fC = f(C)
        if fC * fB < 0:
            A, fA = B, fB
        else:
            fA = fA / 2.0
        B, fB = C, fC

    return math.exp(A / 2.0)


def _update_one_side(rating: float, rd: float, volatility: float,
                      opp_rating: float, opp_rd: float, score: float) -> tuple[float, float, float]:
    """One side of a single-game Glicko-2 update. `score` is in [0, 1] --
    normally 1/0 for win/loss, but this app feeds in a margin-shaded value
    (see record_game_result) so a blowout still moves ratings more than a
    nail-biter, the same intent the old Elo margin-of-victory multiplier had."""
    mu, phi = _to_glicko2_scale(rating, rd)
    mu_j, phi_j = _to_glicko2_scale(opp_rating, opp_rd)

    g_j = _g(phi_j)
    E_val = _expectation(mu, mu_j, phi_j)
    E_val = min(max(E_val, 1e-6), 1 - 1e-6)  # keep v finite at the extremes

    v = 1.0 / (g_j ** 2 * E_val * (1 - E_val))
    delta = v * g_j * (score - E_val)

    new_vol = _new_volatility(phi, delta, v, volatility)
    phi_star = math.sqrt(phi ** 2 + new_vol ** 2)
    new_phi = 1.0 / math.sqrt(1.0 / phi_star ** 2 + 1.0 / v)
    new_mu = mu + new_phi ** 2 * g_j * (score - E_val)

    new_rating, new_rd = _from_glicko2_scale(new_mu, new_phi)
    new_rd = max(RD_FLOOR, min(RD_MAX, new_rd))
    return new_rating, new_rd, new_vol


def _apply_inactivity_decay(rd: float, last_updated) -> float:
    """RD widens the longer a team goes without a logged game -- an old
    rating shouldn't be trusted as much as a fresh one."""
    if last_updated is None:
        return rd
    if isinstance(last_updated, str):
        try:
            last_updated = datetime.fromisoformat(last_updated)
        except ValueError:
            return rd
    if isinstance(last_updated, date) and not isinstance(last_updated, datetime):
        last_updated = datetime.combine(last_updated, datetime.min.time())
    days_elapsed = max(0.0, (datetime.now() - last_updated).total_seconds() / 86400.0)
    if days_elapsed <= 0:
        return rd
    widened = math.sqrt(rd ** 2 + (_INACTIVITY_C ** 2) * days_elapsed)
    return max(RD_FLOOR, min(RD_MAX, widened))


def get_rating(sport: str, team: str, conn=None) -> float:
    """Backward-compatible scalar accessor -- just the rating number."""
    return get_rating_full(sport, team, conn=conn)["rating"]


def get_rating_full(sport: str, team: str, conn=None) -> dict:
    sport = normalize_sport(sport)
    team = _canonicalize(sport, team)
    owns_conn = conn is None
    conn = conn or _connect()
    try:
        row = conn.execute(
            "SELECT rating, rd, volatility, games_played, last_updated, last_game_date "
            "FROM team_ratings WHERE sport = ? AND team = ?",
            [sport, team],
        ).fetchone()
        if not row:
            return {
                "rating": DEFAULT_RATING, "rd": DEFAULT_RD, "volatility": DEFAULT_VOLATILITY,
                "games_played": 0, "last_updated": None, "last_game_date": None,
            }
        rating, rd, volatility, games_played, last_updated, last_game_date = row
        rd = _apply_inactivity_decay(rd if rd is not None else DEFAULT_RD, last_updated)
        return {
            "rating": rating,
            "rd": rd,
            "volatility": volatility if volatility is not None else DEFAULT_VOLATILITY,
            "games_played": games_played,
            "last_updated": str(last_updated) if last_updated else None,
            "last_game_date": str(last_game_date) if last_game_date else None,
        }
    finally:
        if owns_conn:
            conn.close()


def confidence_label(rd: float) -> str:
    if rd <= 80:
        return "High"
    if rd <= 180:
        return "Medium"
    return "Low"


def get_active_status_adjustment(sport: str, team: str, conn=None) -> dict:
    """Sum of active (non-expired) manual situational adjustments for a
    team, clamped to a sane range, plus the notes behind them."""
    sport = normalize_sport(sport)
    team = _canonicalize(sport, team)
    owns_conn = conn is None
    conn = conn or _connect()
    try:
        today = date.today().isoformat()
        rows = conn.execute(
            """
            SELECT adjustment, note FROM team_status
            WHERE sport = ? AND team = ? AND (expires_at IS NULL OR expires_at >= ?)
            """,
            [sport, team, today],
        ).fetchall()
        total = sum(r[0] for r in rows)
        total = max(-STATUS_ADJUSTMENT_CAP, min(STATUS_ADJUSTMENT_CAP, total))
        return {"adjustment": total, "notes": [r[1] for r in rows if r[1]]}
    finally:
        if owns_conn:
            conn.close()


def set_team_status(sport: str, team: str, adjustment: float, note: Optional[str] = None,
                     expires_at: Optional[str] = None, source: str = "manual") -> dict:
    sport = normalize_sport(sport)
    team = _canonicalize(sport, team)
    adjustment = max(-STATUS_ADJUSTMENT_CAP, min(STATUS_ADJUSTMENT_CAP, adjustment))
    conn = _connect()
    try:
        row = conn.execute(
            "INSERT INTO team_status (sport, team, adjustment, note, expires_at, source) "
            "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            [sport, team, adjustment, note, expires_at, source],
        ).fetchone()
        return {"id": row[0], "sport": sport, "team": team, "adjustment": adjustment,
                "note": note, "expires_at": expires_at, "source": source}
    finally:
        conn.close()


def replace_auto_team_status(sport: str, team: str, adjustment: float, note: Optional[str],
                              expires_at: Optional[str] = None, source: str = "espn_auto") -> dict:
    """Deletes any existing team_status rows for this team+sport+source and
    inserts a fresh one (or inserts nothing if adjustment is 0 with no
    note) -- so an automatic sync job (e.g. sports_agent's ESPN injury
    sync) can re-run on every poll and stay current without piling up
    duplicate adjustments each cycle. Rows with a different `source`
    (manual entries you typed in yourself default to 'manual') are never
    touched."""
    sport = normalize_sport(sport)
    team = _canonicalize(sport, team)
    adjustment = max(-STATUS_ADJUSTMENT_CAP, min(STATUS_ADJUSTMENT_CAP, adjustment))
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM team_status WHERE sport = ? AND team = ? AND source = ?",
            [sport, team, source],
        )
        if adjustment == 0 and not note:
            return {"sport": sport, "team": team, "adjustment": 0.0, "note": None, "cleared": True}
        row = conn.execute(
            "INSERT INTO team_status (sport, team, adjustment, note, expires_at, source) "
            "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            [sport, team, adjustment, note, expires_at, source],
        ).fetchone()
        return {"id": row[0], "sport": sport, "team": team, "adjustment": adjustment,
                "note": note, "expires_at": expires_at, "source": source}
    finally:
        conn.close()


def list_team_status(sport: str, active_only: bool = True) -> list[dict]:
    sport = normalize_sport(sport)
    conn = _connect()
    try:
        query = "SELECT id, team, adjustment, note, expires_at, created_at, source FROM team_status WHERE sport = ?"
        params: list = [sport]
        if active_only:
            query += " AND (expires_at IS NULL OR expires_at >= ?)"
            params.append(date.today().isoformat())
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [
            {"id": r[0], "team": r[1], "adjustment": r[2], "note": r[3],
             "expires_at": str(r[4]) if r[4] else None, "created_at": str(r[5]),
             "source": r[6] or "manual"}
            for r in rows
        ]
    finally:
        conn.close()


def clear_team_status(status_id: int) -> bool:
    conn = _connect()
    try:
        row = conn.execute("SELECT id FROM team_status WHERE id = ?", [status_id]).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM team_status WHERE id = ?", [status_id])
        return True
    finally:
        conn.close()


def _rest_days(sport: str, team: str, as_of: Optional[str], conn) -> Optional[int]:
    sport = normalize_sport(sport)
    team = _canonicalize(sport, team)
    row = conn.execute(
        "SELECT last_game_date FROM team_ratings WHERE sport = ? AND team = ?",
        [sport, team],
    ).fetchone()
    if not row or not row[0]:
        return None
    last_game = row[0]
    if isinstance(last_game, str):
        last_game = date.fromisoformat(last_game)
    target = date.fromisoformat(as_of) if as_of else date.today()
    return max(0, (target - last_game).days)


def _canonicalize(sport: str, team: str) -> str:
    """Best-effort resolve to ESPN's canonical team display name, so every
    part of the app converges on the same team_ratings/team_status key
    regardless of which string form was used to call in (a chat query's
    'Braves', auto-settlement's ESPN scoreboard 'Atlanta Braves', a
    manually-logged result typed a third way). Without this, those would
    each land on a different team_ratings row starting at the default
    rating, silently disconnecting predictions from logged results.

    Falls back to the original string (never raises) if ESPN can't
    resolve it -- offline, or a name this sport's ESPN mapping doesn't
    have -- so a lookup failure here degrades to the pre-fix behavior
    instead of breaking the caller."""
    if not team:
        return team
    try:
        from sports_agent import espn_stats  # lazy: espn_stats imports normalize_sport from this module
        return espn_stats.canonical_team_name(sport, team) or team
    except Exception:
        return team


def win_probability(sport: str, home_team: str, away_team: str, game_date: Optional[str] = None) -> float:
    """Glicko-2-implied probability the HOME team wins, in [0, 1] -- folds
    in home-field advantage, each team's rating uncertainty, logged rest
    days, and any active manual situational adjustments."""
    home_team = _canonicalize(sport, home_team)
    away_team = _canonicalize(sport, away_team)
    params = _sport_params(sport)
    conn = _connect()
    try:
        home = get_rating_full(sport, home_team, conn=conn)
        away = get_rating_full(sport, away_team, conn=conn)

        home_rest = _rest_days(sport, home_team, game_date, conn)
        away_rest = _rest_days(sport, away_team, game_date, conn)
        rest_adj = 0.0
        if home_rest is not None and away_rest is not None:
            rest_adj = max(-params["rest_cap"], min(params["rest_cap"],
                            (home_rest - away_rest) * params["rest_pts_per_day"]))

        home_status = get_active_status_adjustment(sport, home_team, conn=conn)
        away_status = get_active_status_adjustment(sport, away_team, conn=conn)

        eff_home_mu = home["rating"] + params["home_adv"] + rest_adj + home_status["adjustment"]
        eff_away_mu = away["rating"] + away_status["adjustment"]

        combined_phi_real = math.sqrt(home["rd"] ** 2 + away["rd"] ** 2)
        mu_diff_internal = (eff_home_mu - eff_away_mu) / GLICKO_SCALE
        phi_internal = combined_phi_real / GLICKO_SCALE
        g_combined = _g(phi_internal)
        return 1.0 / (1.0 + math.exp(-g_combined * mu_diff_internal))
    finally:
        conn.close()


def win_probability_breakdown(sport: str, home_team: str, away_team: str,
                               game_date: Optional[str] = None) -> dict:
    """Same math as win_probability(), but returns every ingredient so the
    UI can show *why* a pick was favored instead of a black-box number."""
    home_team = _canonicalize(sport, home_team)
    away_team = _canonicalize(sport, away_team)
    params = _sport_params(sport)
    conn = _connect()
    try:
        home = get_rating_full(sport, home_team, conn=conn)
        away = get_rating_full(sport, away_team, conn=conn)
        home_rest = _rest_days(sport, home_team, game_date, conn)
        away_rest = _rest_days(sport, away_team, game_date, conn)
        rest_adj = 0.0
        if home_rest is not None and away_rest is not None:
            rest_adj = max(-params["rest_cap"], min(params["rest_cap"],
                            (home_rest - away_rest) * params["rest_pts_per_day"]))
        home_status = get_active_status_adjustment(sport, home_team, conn=conn)
        away_status = get_active_status_adjustment(sport, away_team, conn=conn)
    finally:
        conn.close()

    prob = win_probability(sport, home_team, away_team, game_date)
    return {
        "home_win_probability": round(prob * 100, 1),
        "away_win_probability": round((1 - prob) * 100, 1),
        "home_rating": round(home["rating"], 1),
        "away_rating": round(away["rating"], 1),
        "home_rd": round(home["rd"], 1),
        "away_rd": round(away["rd"], 1),
        "home_confidence": confidence_label(home["rd"]),
        "away_confidence": confidence_label(away["rd"]),
        "home_advantage_pts": params["home_adv"],
        "home_rest_days": home_rest,
        "away_rest_days": away_rest,
        "rest_adjustment_pts": round(rest_adj, 1),
        "home_situational_adjustment_pts": home_status["adjustment"],
        "home_situational_notes": home_status["notes"],
        "away_situational_adjustment_pts": away_status["adjustment"],
        "away_situational_notes": away_status["notes"],
    }


def _upsert_rating(conn, sport: str, team: str, new_rating: float, new_rd: float,
                    new_volatility: float, games_played: int, game_date: str) -> None:
    conn.execute(
        """
        INSERT INTO team_ratings (sport, team, rating, rd, volatility, games_played, last_updated, last_game_date)
        VALUES (?, ?, ?, ?, ?, ?, current_timestamp, ?)
        ON CONFLICT (sport, team) DO UPDATE SET
            rating = excluded.rating,
            rd = excluded.rd,
            volatility = excluded.volatility,
            games_played = excluded.games_played,
            last_updated = excluded.last_updated,
            last_game_date = excluded.last_game_date
        """,
        [sport, team, new_rating, new_rd, new_volatility, games_played, game_date],
    )


def record_game_result(
    sport: str,
    home_team: str,
    away_team: str,
    home_score: float,
    away_score: float,
    game_date: Optional[str] = None,
) -> dict:
    """Log a completed game's real result and update both teams' Glicko-2
    ratings. Also auto-resolves any pending model_predictions for this
    matchup so the calibration report can score itself."""
    if home_score == away_score:
        raise ValueError("Rating update needs a decisive result -- no ties supported.")

    sport = normalize_sport(sport)
    home_team = _canonicalize(sport, home_team)
    away_team = _canonicalize(sport, away_team)
    params = _sport_params(sport)
    game_date = game_date or date.today().isoformat()
    conn = _connect()
    try:
        home_before = get_rating_full(sport, home_team, conn=conn)
        away_before = get_rating_full(sport, away_team, conn=conn)

        margin = abs(home_score - away_score)
        # Blowouts move ratings more than nail-biters: shade the [0,1] score
        # toward the extreme in proportion to margin instead of a flat 1/0.
        normalized_margin = min(1.0, margin / params["margin_cap"])
        home_won = home_score > away_score
        winner_score = 0.5 + 0.5 * normalized_margin
        home_score_input = winner_score if home_won else 1.0 - winner_score
        away_score_input = 1.0 - home_score_input

        home_rating, home_rd, home_vol = _update_one_side(
            home_before["rating"], home_before["rd"], home_before["volatility"],
            away_before["rating"], away_before["rd"], home_score_input,
        )
        away_rating, away_rd, away_vol = _update_one_side(
            away_before["rating"], away_before["rd"], away_before["volatility"],
            home_before["rating"], home_before["rd"], away_score_input,
        )

        _upsert_rating(conn, sport, home_team, home_rating, home_rd, home_vol,
                        home_before["games_played"] + 1, game_date)
        _upsert_rating(conn, sport, away_team, away_rating, away_rd, away_vol,
                        away_before["games_played"] + 1, game_date)

        conn.execute(
            """
            INSERT INTO game_results
                (sport, home_team, away_team, home_score, away_score,
                 home_rating_before, away_rating_before, home_rating_after, away_rating_after, game_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                sport, home_team, away_team, home_score, away_score,
                home_before["rating"], away_before["rating"], home_rating, away_rating,
                game_date,
            ],
        )

        actual_winner = home_team if home_won else away_team
        resolved_count = conn.execute(
            """
            UPDATE model_predictions
            SET resolved = TRUE, actual_winner = ?, correct = (favored_team = ?), resolved_at = current_timestamp
            WHERE resolved = FALSE AND sport = ?
              AND lower(home_team) = lower(?) AND lower(away_team) = lower(?)
            """,
            [actual_winner, actual_winner, sport, home_team, away_team],
        )

        return {
            "sport": sport,
            "home_team": home_team,
            "away_team": away_team,
            "home_rating_before": round(home_before["rating"], 1),
            "away_rating_before": round(away_before["rating"], 1),
            "home_rating_after": round(home_rating, 1),
            "away_rating_after": round(away_rating, 1),
            "home_rd_after": round(home_rd, 1),
            "away_rd_after": round(away_rd, 1),
        }
    finally:
        conn.close()


def list_ratings(sport: str) -> list[dict]:
    sport = normalize_sport(sport)
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT team, rating, rd, games_played, last_updated FROM team_ratings "
            "WHERE sport = ? ORDER BY rating DESC",
            [sport],
        ).fetchall()
        result = []
        for team, rating, rd, games_played, last_updated in rows:
            decayed_rd = _apply_inactivity_decay(rd if rd is not None else DEFAULT_RD, last_updated)
            result.append({
                "team": team,
                "rating": round(rating, 1),
                "rd": round(decayed_rd, 1),
                "confidence": confidence_label(decayed_rd),
                "games_played": games_played,
                "last_updated": str(last_updated),
            })
        return result
    finally:
        conn.close()


# --- Prediction logging, for calibration/backtesting ----------------------

def log_prediction(sport: str, home_team: str, away_team: str,
                    home_win_probability: float, favored_team: str, source: str = "prediction") -> int:
    sport = normalize_sport(sport)
    conn = _connect()
    try:
        row = conn.execute(
            """
            INSERT INTO model_predictions (sport, home_team, away_team, home_win_probability, favored_team, source)
            VALUES (?, ?, ?, ?, ?, ?) RETURNING id
            """,
            [sport, home_team, away_team, home_win_probability, favored_team, source],
        ).fetchone()
        return row[0]
    finally:
        conn.close()


def get_calibration(sport: Optional[str] = None) -> dict:
    """Buckets resolved predictions by predicted probability and compares
    against the actual win rate in each bucket -- the honesty check for the
    model. Also reports the Brier score (lower is better; 0 is perfect,
    0.25 is what a coinflip model scores against a 50/50 world)."""
    conn = _connect()
    try:
        query = (
            "SELECT home_win_probability, correct, favored_team, home_team "
            "FROM model_predictions WHERE resolved = TRUE"
        )
        params: list = []
        if sport:
            query += " AND sport = ?"
            params.append(normalize_sport(sport))
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"total_resolved": 0, "buckets": [], "brier_score": None, "overall_accuracy_pct": None}

    buckets_def = [(0, 55), (55, 65), (65, 75), (75, 85), (85, 95), (95, 101)]
    buckets = []
    brier_sum = 0.0
    correct_count = 0

    for lo, hi in buckets_def:
        in_bucket = []
        for home_prob, correct, favored_team, home_team in rows:
            # Normalize every prediction to "probability of the favored side",
            # so a 30% home-win prediction (i.e. a 70% away favorite) still
            # lands in the 65-75 bucket rather than skewing everything low.
            favored_prob = home_prob if favored_team == home_team else (100.0 - home_prob)
            if lo <= favored_prob < hi or (hi == 101 and favored_prob == 100):
                in_bucket.append((favored_prob, correct))
        if not in_bucket:
            continue
        n = len(in_bucket)
        actual_hits = sum(1 for _, c in in_bucket if c)
        buckets.append({
            "range": f"{lo}-{min(hi, 100)}%",
            "n": n,
            "predicted_avg_pct": round(sum(p for p, _ in in_bucket) / n, 1),
            "actual_win_rate_pct": round((actual_hits / n) * 100, 1),
        })

    for home_prob, correct, favored_team, home_team in rows:
        favored_prob_frac = (home_prob if favored_team == home_team else (100.0 - home_prob)) / 100.0
        outcome = 1.0 if correct else 0.0
        brier_sum += (favored_prob_frac - outcome) ** 2
        if correct:
            correct_count += 1

    return {
        "total_resolved": len(rows),
        "buckets": buckets,
        "brier_score": round(brier_sum / len(rows), 4),
        "overall_accuracy_pct": round((correct_count / len(rows)) * 100, 1),
    }


# --- Standings, derived from your own logged game_results ------------------

def get_standings(sport: str) -> list[dict]:
    """Real win-loss record and points-for/against, computed entirely from
    games YOU'VE logged via POST /games/result -- not an official league
    standings feed (there isn't one connected). A team that hasn't had a
    result logged for it won't appear here at all."""
    sport = normalize_sport(sport)
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT home_team, away_team, home_score, away_score FROM game_results WHERE sport = ?",
            [sport],
        ).fetchall()
        ratings_rows = conn.execute(
            "SELECT team, rating, rd, last_updated FROM team_ratings WHERE sport = ?",
            [sport],
        ).fetchall()
    finally:
        conn.close()

    teams: dict = {}

    def _team(name):
        return teams.setdefault(name, {"team": name, "wins": 0, "losses": 0, "points_for": 0.0, "points_against": 0.0})

    for home_team, away_team, home_score, away_score in rows:
        h, a = _team(home_team), _team(away_team)
        h["points_for"] += home_score
        h["points_against"] += away_score
        a["points_for"] += away_score
        a["points_against"] += home_score
        if home_score > away_score:
            h["wins"] += 1
            a["losses"] += 1
        else:
            a["wins"] += 1
            h["losses"] += 1

    rating_by_team = {r[0]: {"rating": r[1], "rd": _apply_inactivity_decay(r[2] if r[2] is not None else DEFAULT_RD, r[3])}
                       for r in ratings_rows}

    standings = []
    for name, t in teams.items():
        games_played = t["wins"] + t["losses"]
        rt = rating_by_team.get(name, {"rating": DEFAULT_RATING, "rd": DEFAULT_RD})
        standings.append({
            "team": name,
            "wins": t["wins"],
            "losses": t["losses"],
            "win_pct": round(t["wins"] / games_played, 3) if games_played else None,
            "points_per_game": round(t["points_for"] / games_played, 1) if games_played else None,
            "points_allowed_per_game": round(t["points_against"] / games_played, 1) if games_played else None,
            "point_differential": round((t["points_for"] - t["points_against"]) / games_played, 1) if games_played else None,
            "rating": round(rt["rating"], 1),
            "confidence": confidence_label(rt["rd"]),
        })

    standings.sort(key=lambda s: (-(s["win_pct"] or 0), -(s["point_differential"] or -999)))
    return standings
