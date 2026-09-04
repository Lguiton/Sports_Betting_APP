"""
REST endpoints for the personal analytics layer: bet journal, game-result
logging (feeds the Elo rating engine in sports_agent/ratings.py), real
performance stats, multi-book odds comparison, and arbitrage scanning.

This is a single-user, no-auth app meant to run locally for one person --
there is no tenant/account model here on purpose.
"""
from datetime import datetime, date, timedelta, timezone
from typing import Optional, Literal

import duckdb
import requests
import threading
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from config import ODDS_API_KEY
from sports_agent.nodes import american_to_decimal, decimal_to_implied_prob, kelly_criterion, calculate_ev
from sports_agent.ratings import (
    record_game_result, list_ratings, win_probability_breakdown, get_calibration,
    set_team_status, list_team_status, clear_team_status, normalize_sport, get_standings,
    replace_auto_team_status,
)
from sports_agent import espn_stats

router = APIRouter()
DB_PATH = "data/telemetry.duckdb"

ODDS_SPORT_KEYS = {
    "NFL": "americanfootball_nfl",
    "NBA": "basketball_nba",
    "MLB": "baseball_mlb",
    "NCAAF": "americanfootball_ncaaf",
}

# DuckDB doesn't tolerate two connections writing to the same file at the
# same instant -- confirmed live: running two of this app's background
# cycles concurrently (a scheduled poll firing at the same moment as a
# manual "run now" trigger) threw a real TransactionException/IOException
# on the database's WAL file, not just a theoretical race. This app runs
# up to four such cycles (line tracking, auto-settlement, injury sync,
# stats sync) as independent background loops in the same process, plus
# manual "run now" triggers for several of them -- so every entry point
# that runs one of these cycles goes through this single process-wide
# lock, guaranteeing only one cycle ever touches the database at a time
# regardless of whether it fired automatically or by hand.
_CYCLE_LOCK = threading.Lock()


def _run_locked(fn, *args, **kwargs):
    with _CYCLE_LOCK:
        return fn(*args, **kwargs)


def _connect():
    conn = duckdb.connect(DB_PATH)
    conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_bets_id START 1")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER DEFAULT nextval('seq_bets_id') PRIMARY KEY,
            sport VARCHAR,
            matchup VARCHAR,
            bet_type VARCHAR,
            selection VARCHAR,
            odds DOUBLE,
            stake DOUBLE,
            to_win DOUBLE,
            status VARCHAR DEFAULT 'pending',
            result_profit DOUBLE,
            closing_odds DOUBLE,
            clv_pct DOUBLE,
            placed_at TIMESTAMP DEFAULT current_timestamp,
            graded_at TIMESTAMP,
            notes VARCHAR
        )
        """
    )
    # home_team/away_team, added in place -- older rows keep their freeform
    # `matchup` text, but structured team names are what let the line
    # tracker match an open bet to a live odds board and auto-fill CLV.
    for col, ddl in [("home_team", "VARCHAR"), ("away_team", "VARCHAR"), ("graded_by", "VARCHAR")]:
        try:
            conn.execute(f"ALTER TABLE bets ADD COLUMN IF NOT EXISTS {col} {ddl}")
        except duckdb.Error:
            pass

    conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_odds_snapshots_id START 1")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            id INTEGER DEFAULT nextval('seq_odds_snapshots_id') PRIMARY KEY,
            sport VARCHAR,
            home_team VARCHAR,
            away_team VARCHAR,
            best_home_price DOUBLE,
            best_home_book VARCHAR,
            best_away_price DOUBLE,
            best_away_book VARCHAR,
            commence_time VARCHAR,
            captured_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )

    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings (key VARCHAR PRIMARY KEY, value VARCHAR)"
    )
    return conn


def _get_setting(conn, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", [key]).fetchone()
    return row[0] if row else default


def _set_setting(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        [key, value],
    )


def _fetch_sport_board(sport: str, markets: str = "h2h") -> list:
    """Shared Odds-API fetch for a sport's full current board (every game
    currently listed, not filtered to one matchup) -- used by Edge Radar and
    the line tracker. compare_odds/scan_arbitrage keep their own inline
    fetch to avoid touching already-verified code."""
    if not ODDS_API_KEY:
        raise HTTPException(status_code=400, detail="ODDS_API_KEY is not configured in .env")
    sport_key = ODDS_SPORT_KEYS.get(normalize_sport(sport), "americanfootball_nfl")
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "us", "markets": markets, "oddsFormat": "american"}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Odds API request failed: {e}")


def _best_prices(game: dict) -> dict:
    """Best home/away moneyline price across every book listed for one game."""
    best_home = None  # (price, book)
    best_away = None
    for bk in game.get("bookmakers", []):
        h2h = next((m for m in bk.get("markets", []) if m.get("key") == "h2h"), None)
        if not h2h:
            continue
        for o in h2h.get("outcomes", []):
            if o["name"] == game.get("home_team"):
                if best_home is None or o["price"] > best_home[0]:
                    best_home = (o["price"], bk["title"])
            elif o["name"] == game.get("away_team"):
                if best_away is None or o["price"] > best_away[0]:
                    best_away = (o["price"], bk["title"])
    return {"best_home": best_home, "best_away": best_away}


def _row_to_dict(cols, row):
    return {c: (str(v) if isinstance(v, (datetime, date)) else v) for c, v in zip(cols, row)}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class GameResultIn(BaseModel):
    sport: str
    home_team: str
    away_team: str
    home_score: float
    away_score: float
    game_date: Optional[str] = None


class BetIn(BaseModel):
    sport: str
    matchup: str = ""
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    bet_type: str = "moneyline"
    selection: str
    odds: float
    stake: float = Field(gt=0)
    notes: Optional[str] = None

    @model_validator(mode="after")
    def matchup_or_teams_required(self):
        # Structured home_team/away_team are what let the line tracker match
        # this bet to a live odds board and auto-fill closing line value --
        # but free-text matchup still works for anyone who doesn't care about that.
        if not self.matchup and not (self.home_team and self.away_team):
            raise ValueError("Provide either `matchup` text or both home_team and away_team")
        return self


class BetGradeIn(BaseModel):
    status: Literal["won", "lost", "push", "void"]
    closing_odds: Optional[float] = None


# ---------------------------------------------------------------------------
# Ratings / game results  (feeds predict_matchup_winner)
# ---------------------------------------------------------------------------

@router.post("/games/result")
def log_game_result(payload: GameResultIn):
    """Log a completed game's real score. Updates both teams' Elo ratings,
    which is what predict_matchup_winner reads from on every future query."""
    try:
        result = record_game_result(
            payload.sport, payload.home_team, payload.away_team,
            payload.home_score, payload.away_score, payload.game_date,
        )
        return {"status": "ok", "ratings_update": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/ratings/{sport}")
def get_ratings(sport: str):
    return {"sport": sport.upper(), "ratings": list_ratings(sport)}


# ---------------------------------------------------------------------------
# Auto-settlement: ESPN final scores -> ratings + moneyline bet grading,
# on a schedule, instead of typing every result in by hand.
# ---------------------------------------------------------------------------

AUTO_SETTLE_INTERVAL_MINUTES = 20


def _game_already_logged(conn, sport: str, home_team: str, away_team: str, game_date: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM game_results WHERE sport = ? AND lower(home_team) = lower(?) "
        "AND lower(away_team) = lower(?) AND game_date = ?",
        [sport, home_team, away_team, game_date],
    ).fetchone()
    return row is not None


def _fuzzy_team_match(a: str, b: str) -> bool:
    """Loose team-name match (normalized substring in either direction),
    e.g. so a bet logged as 'Red Sox' matches ESPN's full 'Boston Red Sox'
    display name. An exact (or lower()) comparison is too strict here --
    ESPN's scoreboard always uses full display names, but the Bet Journal's
    own home/away fields are free text the user typed (its own placeholder
    is the short form, e.g. 'Ravens')."""
    a_norm, b_norm = espn_stats._normalize_name(a or ""), espn_stats._normalize_name(b or "")
    if not a_norm or not b_norm:
        return False
    return a_norm in b_norm or b_norm in a_norm


def run_auto_settlement_cycle() -> dict:
    """Checks today's ESPN scoreboard for every supported sport, and for
    any game that's gone Final: (1) logs the result into the Glicko-2
    rating engine via record_game_result if it hasn't been logged yet
    (game_results has no unique constraint, so this dedup check is what
    stops the same final score from being applied to a team's rating on
    every poll), and (2) auto-grades any pending *moneyline* bet on that
    exact matchup by matching your free-text `selection` against the real
    winner/loser team name.

    Spread and total bets are deliberately left alone -- the app only
    stores the selection as free text (e.g. "Patriots -3.5"), not a
    structured line, so there's no safe way to auto-grade those without
    risking a wrong grade. Those still use the manual Won/Lost/Push/Void
    buttons in the Bet Journal, same as before this existed."""
    conn = _connect()
    try:
        enabled = _get_setting(conn, "auto_settle_enabled", "true") == "true"
    finally:
        conn.close()
    if not enabled:
        return {"ran": False, "reason": "auto-settlement is disabled"}

    today = date.today().isoformat()
    games_logged = 0
    bets_graded = 0

    yesterday = (date.today() - timedelta(days=1)).isoformat()

    for sport in ODDS_SPORT_KEYS:
        # Checks today's AND yesterday's ESPN scoreboard, not just
        # "today" -- a game that went Final late last night (or any day
        # this app happened not to be running) would otherwise never get
        # logged, since ESPN's scoreboard endpoint only returns the one
        # date you ask for. _game_already_logged's dedup check means
        # re-checking yesterday on every cycle is harmless.
        games = []
        seen_event_ids = set()
        for check_date in (today, yesterday):
            try:
                board = espn_stats.get_scoreboard(sport, check_date)
            except Exception:
                continue
            for g in (board.get("games") if isinstance(board, dict) else None) or []:
                event_id = g.get("espn_event_id")
                if event_id and event_id in seen_event_ids:
                    continue
                if event_id:
                    seen_event_ids.add(event_id)
                games.append(g)
        if not games:
            continue

        for g in games:
            status_text = (g.get("status") or "").lower()
            if "final" not in status_text:
                continue
            home_team, away_team = g.get("home_team"), g.get("away_team")
            home_score_raw, away_score_raw = g.get("home_score"), g.get("away_score")
            if not home_team or not away_team or home_score_raw is None or away_score_raw is None:
                continue
            try:
                home_score, away_score = float(home_score_raw), float(away_score_raw)
            except (TypeError, ValueError):
                continue
            if home_score == away_score:
                continue  # record_game_result refuses ties -- nothing to do

            game_date = (g.get("date") or today)[:10]
            sport_norm = normalize_sport(sport)

            conn = _connect()
            try:
                already_logged = _game_already_logged(conn, sport_norm, home_team, away_team, game_date)
            finally:
                conn.close()

            if not already_logged:
                try:
                    record_game_result(sport, home_team, away_team, home_score, away_score, game_date)
                    games_logged += 1
                except ValueError:
                    pass

            winner = home_team if home_score > away_score else away_team
            loser = away_team if winner == home_team else home_team

            conn = _connect()
            try:
                # Pulled by sport only, not by an exact team-name match --
                # see _fuzzy_team_match's docstring for why an exact
                # comparison against ESPN's names would silently miss
                # almost every bet logged with the app's own short-name
                # convention.
                pending = conn.execute(
                    """
                    SELECT id, selection, odds, stake, home_team, away_team FROM bets
                    WHERE status = 'pending' AND bet_type = 'moneyline'
                      AND sport = ? AND home_team IS NOT NULL AND away_team IS NOT NULL
                    """,
                    [sport_norm],
                ).fetchall()
                for bet_id, selection, odds, stake, bet_home, bet_away in pending:
                    if _fuzzy_team_match(bet_home, home_team) and _fuzzy_team_match(bet_away, away_team):
                        winner_as_typed = bet_home if winner == home_team else bet_away
                        loser_as_typed = bet_away if winner == home_team else bet_home
                    elif _fuzzy_team_match(bet_home, away_team) and _fuzzy_team_match(bet_away, home_team):
                        winner_as_typed = bet_away if winner == home_team else bet_home
                        loser_as_typed = bet_home if winner == home_team else bet_away
                    else:
                        continue  # this bet isn't for this specific game

                    # Match selection text against the bet's OWN team-name
                    # text (whatever the user actually typed), not ESPN's
                    # full display name -- the whole reason this can't just
                    # reuse `winner`/`loser` for the text match too.
                    sel_lower = (selection or "").lower()
                    if winner_as_typed.lower() in sel_lower:
                        new_status = "won"
                        profit = round(stake * (american_to_decimal(odds) - 1), 2)
                    elif loser_as_typed.lower() in sel_lower:
                        new_status = "lost"
                        profit = -stake
                    else:
                        continue  # selection text doesn't clearly name either side -- leave for manual grading

                    conn.execute(
                        "UPDATE bets SET status = ?, result_profit = ?, graded_at = current_timestamp, "
                        "graded_by = 'auto' WHERE id = ? AND status = 'pending'",
                        [new_status, profit, bet_id],
                    )
                    bets_graded += 1
            finally:
                conn.close()

    conn = _connect()
    try:
        _set_setting(conn, "auto_settle_last_run", datetime.now().isoformat())
    finally:
        conn.close()
    return {"ran": True, "games_logged": games_logged, "bets_graded": bets_graded}


class AutoSettleToggle(BaseModel):
    enabled: bool


@router.post("/auto-settle/enabled")
def set_auto_settle(payload: AutoSettleToggle):
    """Auto-settlement only reads ESPN's (free, unofficial) scoreboard and
    your own already-logged bets, so it defaults ON -- unlike line
    tracking, which hits a paid/rate-limited API. Turn it off here if you'd
    rather grade everything by hand."""
    conn = _connect()
    try:
        _set_setting(conn, "auto_settle_enabled", "true" if payload.enabled else "false")
    finally:
        conn.close()
    return {"auto_settle_enabled": payload.enabled}


@router.get("/auto-settle/status")
def get_auto_settle_status():
    conn = _connect()
    try:
        enabled = _get_setting(conn, "auto_settle_enabled", "true") == "true"
        last_run = _get_setting(conn, "auto_settle_last_run", "")
    finally:
        conn.close()
    return {"auto_settle_enabled": enabled, "last_run": last_run or None,
            "poll_interval_minutes": AUTO_SETTLE_INTERVAL_MINUTES}


@router.post("/auto-settle/run")
def trigger_auto_settle():
    """Run one auto-settlement pass right now instead of waiting for the
    next scheduled poll -- handy for testing or right after a game ends."""
    return _run_locked(run_auto_settlement_cycle)


# ---------------------------------------------------------------------------
# Bet journal
# ---------------------------------------------------------------------------

@router.post("/bets")
def create_bet(bet: BetIn):
    dec = american_to_decimal(bet.odds)
    to_win = round(bet.stake * (dec - 1), 2)
    matchup = bet.matchup or f"{bet.away_team} @ {bet.home_team}"
    conn = _connect()
    try:
        row = conn.execute(
            """
            INSERT INTO bets (sport, matchup, home_team, away_team, bet_type, selection, odds, stake, to_win, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            [bet.sport.upper(), matchup, bet.home_team, bet.away_team, bet.bet_type,
             bet.selection, bet.odds, bet.stake, to_win, bet.notes],
        ).fetchone()
        return {"id": row[0], "to_win": to_win, "status": "pending"}
    finally:
        conn.close()


@router.get("/bets")
def list_bets(status: Optional[str] = None, sport: Optional[str] = None, limit: int = 200):
    conn = _connect()
    try:
        query = (
            "SELECT id, sport, matchup, bet_type, selection, odds, stake, to_win, status, "
            "result_profit, closing_odds, clv_pct, placed_at, graded_at, notes, home_team, away_team, graded_by "
            "FROM bets WHERE 1=1"
        )
        params: list = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if sport:
            query += " AND sport = ?"
            params.append(sport.upper())
        query += " ORDER BY placed_at DESC LIMIT ?"
        params.append(limit)

        cols = ["id", "sport", "matchup", "bet_type", "selection", "odds", "stake", "to_win",
                "status", "result_profit", "closing_odds", "clv_pct", "placed_at", "graded_at", "notes",
                "home_team", "away_team", "graded_by"]
        rows = conn.execute(query, params).fetchall()
        return [_row_to_dict(cols, row) for row in rows]
    finally:
        conn.close()


@router.patch("/bets/{bet_id}")
def grade_bet(bet_id: int, grade: BetGradeIn):
    """Grade a pending bet won/lost/push/void. Computes real profit/loss and,
    if you provide the closing line, real closing-line value (CLV)."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT odds, stake, status, closing_odds FROM bets WHERE id = ?", [bet_id]
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Bet not found")
        odds, stake, current_status, auto_filled_closing_odds = row
        if current_status != "pending":
            raise HTTPException(status_code=400, detail=f"Bet already graded as '{current_status}'")

        if grade.status == "won":
            profit = round(stake * (american_to_decimal(odds) - 1), 2)
        elif grade.status == "lost":
            profit = -stake
        else:  # push / void -- stake returned, no profit or loss
            profit = 0.0

        # Prefer an explicitly-supplied closing line; otherwise use whatever
        # the line tracker already auto-captured for this bet (see
        # run_line_tracking_cycle) instead of leaving CLV blank.
        closing_odds = grade.closing_odds if grade.closing_odds is not None else auto_filled_closing_odds

        clv_pct = None
        if closing_odds is not None:
            opened_implied = decimal_to_implied_prob(american_to_decimal(odds))
            closed_implied = decimal_to_implied_prob(american_to_decimal(closing_odds))
            # Positive = the line moved toward you after you bet (you beat the closing number).
            clv_pct = round(closed_implied - opened_implied, 2)

        conn.execute(
            """
            UPDATE bets
            SET status = ?, result_profit = ?, closing_odds = ?, clv_pct = ?, graded_at = current_timestamp,
                graded_by = 'manual'
            WHERE id = ?
            """,
            [grade.status, profit, closing_odds, clv_pct, bet_id],
        )
        return {"id": bet_id, "status": grade.status, "result_profit": profit, "clv_pct": clv_pct}
    finally:
        conn.close()


@router.get("/performance")
def get_performance(sport: Optional[str] = None):
    """Real win rate, ROI, average CLV, and a bankroll curve computed from
    bets you've actually logged and graded -- not simulated."""
    conn = _connect()
    try:
        query = "SELECT status, stake, result_profit, clv_pct FROM bets WHERE status != 'pending'"
        params: list = []
        if sport:
            query += " AND sport = ?"
            params.append(sport.upper())
        rows = conn.execute(query, params).fetchall()

        decided = [r for r in rows if r[0] in ("won", "lost")]
        wins = sum(1 for r in decided if r[0] == "won")
        losses = sum(1 for r in decided if r[0] == "lost")
        total_staked = round(sum(r[1] for r in decided), 2)
        total_profit = round(sum((r[2] or 0.0) for r in rows), 2)
        clv_values = [r[3] for r in rows if r[3] is not None]

        curve_query = (
            "SELECT graded_at, result_profit FROM bets "
            "WHERE status IN ('won','lost','push') AND graded_at IS NOT NULL"
        )
        curve_params: list = []
        if sport:
            curve_query += " AND sport = ?"
            curve_params.append(sport.upper())
        curve_query += " ORDER BY graded_at ASC"

        running = 0.0
        curve = []
        for graded_at, profit in conn.execute(curve_query, curve_params).fetchall():
            running += profit or 0.0
            curve.append({"date": str(graded_at), "cumulative_profit": round(running, 2)})

        return {
            "graded_bets": len(decided),
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round((wins / len(decided)) * 100, 1) if decided else None,
            "total_staked": total_staked,
            "total_profit": total_profit,
            "roi_pct": round((total_profit / total_staked) * 100, 2) if total_staked else None,
            "avg_clv_pct": round(sum(clv_values) / len(clv_values), 2) if clv_values else None,
            "bankroll_curve": curve,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Multi-book odds comparison + arbitrage scanning
# ---------------------------------------------------------------------------

@router.get("/odds/compare")
def compare_odds(sport: str, home_team: str, away_team: str):
    """All bookmakers' moneyline prices for one matchup, not just DraftKings."""
    if not ODDS_API_KEY:
        raise HTTPException(status_code=400, detail="ODDS_API_KEY is not configured in .env")

    sport_key = ODDS_SPORT_KEYS.get(sport.upper(), "americanfootball_nfl")
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "us", "markets": "h2h", "oddsFormat": "american"}

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        games = resp.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Odds API request failed: {e}")

    for game in games:
        live_home = game.get("home_team", "").lower()
        live_away = game.get("away_team", "").lower()
        if home_team.lower() not in live_home and away_team.lower() not in live_away:
            continue

        books = []
        for bk in game.get("bookmakers", []):
            h2h = next((m for m in bk.get("markets", []) if m.get("key") == "h2h"), None)
            if not h2h:
                continue
            outcomes = {o["name"]: o["price"] for o in h2h.get("outcomes", [])}
            books.append({
                "book": bk["title"],
                "home_price": outcomes.get(game["home_team"]),
                "away_price": outcomes.get(game["away_team"]),
                "last_update": h2h.get("last_update"),
            })

        if not books:
            continue

        best_home = max((b for b in books if b["home_price"] is not None), key=lambda b: b["home_price"], default=None)
        best_away = max((b for b in books if b["away_price"] is not None), key=lambda b: b["away_price"], default=None)

        return {
            "matchup": f"{game['away_team']} @ {game['home_team']}",
            "commence_time": game.get("commence_time"),
            "books": books,
            "best_home_price": {"book": best_home["book"], "price": best_home["home_price"]} if best_home else None,
            "best_away_price": {"book": best_away["book"], "price": best_away["away_price"]} if best_away else None,
        }

    raise HTTPException(status_code=404, detail="Matchup not found on the current odds board")


@router.get("/arbitrage/scan")
def scan_arbitrage(sport: str = "NFL", min_edge_pct: float = 0.5):
    """Scan every currently-listed game in a sport for a guaranteed
    cross-book arbitrage: the best home price at one book plus the best
    away price at another book, together implying under 100% probability."""
    if not ODDS_API_KEY:
        raise HTTPException(status_code=400, detail="ODDS_API_KEY is not configured in .env")

    sport_key = ODDS_SPORT_KEYS.get(sport.upper(), "americanfootball_nfl")
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {"apiKey": ODDS_API_KEY, "regions": "us", "markets": "h2h", "oddsFormat": "american"}

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        games = resp.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Odds API request failed: {e}")

    opportunities = []
    for game in games:
        best_home = None  # (price, book)
        best_away = None
        for bk in game.get("bookmakers", []):
            h2h = next((m for m in bk.get("markets", []) if m.get("key") == "h2h"), None)
            if not h2h:
                continue
            for o in h2h.get("outcomes", []):
                if o["name"] == game.get("home_team"):
                    if best_home is None or o["price"] > best_home[0]:
                        best_home = (o["price"], bk["title"])
                elif o["name"] == game.get("away_team"):
                    if best_away is None or o["price"] > best_away[0]:
                        best_away = (o["price"], bk["title"])

        if not best_home or not best_away:
            continue

        implied_home = decimal_to_implied_prob(american_to_decimal(best_home[0])) / 100
        implied_away = decimal_to_implied_prob(american_to_decimal(best_away[0])) / 100
        edge_pct = round((1 - (implied_home + implied_away)) * 100, 2)

        if edge_pct >= min_edge_pct:
            opportunities.append({
                "matchup": f"{game.get('away_team')} @ {game.get('home_team')}",
                "commence_time": game.get("commence_time"),
                "home_leg": {"book": best_home[1], "price": best_home[0]},
                "away_leg": {"book": best_away[1], "price": best_away[0]},
                "guaranteed_edge_pct": edge_pct,
            })

    opportunities.sort(key=lambda o: o["guaranteed_edge_pct"], reverse=True)
    return {"sport": sport.upper(), "opportunities": opportunities, "scanned_games": len(games)}


# ---------------------------------------------------------------------------
# Manual situational adjustments (injuries, suspensions, weather notes...)
# ---------------------------------------------------------------------------

class TeamStatusIn(BaseModel):
    sport: str
    team: str
    adjustment: float = Field(ge=-150, le=150, description="Rating points to add (negative = penalty)")
    note: Optional[str] = None
    expires_at: Optional[str] = None  # ISO date string, e.g. "2026-09-15"


@router.post("/team-status")
def create_team_status(payload: TeamStatusIn):
    """Log a manual situational adjustment (e.g. 'starting QB out: -60') that
    win_probability() folds in until it expires. There's no injury-report
    data feed wired in, so this is how that context gets into the model."""
    return set_team_status(payload.sport, payload.team, payload.adjustment, payload.note, payload.expires_at)


@router.get("/team-status/{sport}")
def get_team_status(sport: str, active_only: bool = True):
    return {"sport": sport.upper(), "statuses": list_team_status(sport, active_only=active_only)}


@router.delete("/team-status/{status_id}")
def delete_team_status(status_id: int):
    if not clear_team_status(status_id):
        raise HTTPException(status_code=404, detail="Status entry not found")
    return {"status": "deleted", "id": status_id}


# ---------------------------------------------------------------------------
# Automatic injury sync: turns ESPN's real injury reports into the same
# situational adjustment system above, instead of requiring every entry to
# be typed in by hand via POST /team-status.
# ---------------------------------------------------------------------------

INJURY_SYNC_INTERVAL_MINUTES = 60

# A blunt heuristic, not a real depth-chart model: a fixed rating penalty
# per player by ESPN's designation, summed per team and capped. It has no
# idea whether the player out is a starting quarterback or a backup
# long-snapper -- treat the resulting adjustment as a nudge, not gospel.
# A manual team-status note you enter yourself (source='manual') is
# unaffected and always adds on top of this.
_INJURY_STATUS_WEIGHTS = {
    "out": -8.0, "injured reserve": -8.0, "ir": -8.0,
    "doubtful": -4.0, "questionable": -2.0,
}
_INJURY_ADJUSTMENT_FLOOR = -30.0  # a long injury list shouldn't be able to swamp the rating


def _injury_weight(status: str) -> float:
    s = (status or "").lower()
    for key, weight in _INJURY_STATUS_WEIGHTS.items():
        if key in s:
            return weight
    return 0.0


def run_injury_sync_cycle() -> dict:
    """Pulls today's ESPN scoreboard for every supported sport, fetches
    each of today's playing teams' current injury report, and turns it
    into an automatic situational adjustment via
    ratings.replace_auto_team_status -- so win_probability() reacts to
    real injury news without you typing it in. Re-running this clears and
    re-derives every 'espn_auto'-sourced adjustment each time, so a
    player coming off the injury report clears its penalty automatically
    too, not just additions."""
    conn = _connect()
    try:
        enabled = _get_setting(conn, "injury_sync_enabled", "true") == "true"
    finally:
        conn.close()
    if not enabled:
        return {"ran": False, "reason": "injury sync is disabled"}

    teams_synced = 0
    for sport in ODDS_SPORT_KEYS:
        try:
            board = espn_stats.get_scoreboard(sport)
        except Exception:
            continue
        games = board.get("games") if isinstance(board, dict) else None
        if not games:
            continue

        team_names = set()
        for g in games:
            if g.get("home_team"):
                team_names.add(g["home_team"])
            if g.get("away_team"):
                team_names.add(g["away_team"])

        for team in team_names:
            try:
                report = espn_stats.get_team_injuries(sport, team)
            except Exception:
                continue
            injuries = report.get("injuries") or []

            total_adj = 0.0
            notes = []
            for inj in injuries:
                w = _injury_weight(inj.get("status", ""))
                if w != 0.0:
                    total_adj += w
                    notes.append(f"{inj.get('player')} ({inj.get('status')})")
            total_adj = max(_INJURY_ADJUSTMENT_FLOOR, total_adj)
            note = ("Auto (ESPN): " + ", ".join(notes[:6])) if notes else None

            try:
                replace_auto_team_status(sport, team, total_adj, note, expires_at=None, source="espn_auto")
                teams_synced += 1
            except Exception:
                continue

    conn = _connect()
    try:
        _set_setting(conn, "injury_sync_last_run", datetime.now().isoformat())
    finally:
        conn.close()
    return {"ran": True, "teams_synced": teams_synced}


class InjurySyncToggle(BaseModel):
    enabled: bool


@router.post("/injury-sync/enabled")
def set_injury_sync(payload: InjurySyncToggle):
    conn = _connect()
    try:
        _set_setting(conn, "injury_sync_enabled", "true" if payload.enabled else "false")
    finally:
        conn.close()
    return {"injury_sync_enabled": payload.enabled}


@router.get("/injury-sync/status")
def get_injury_sync_status():
    conn = _connect()
    try:
        enabled = _get_setting(conn, "injury_sync_enabled", "true") == "true"
        last_run = _get_setting(conn, "injury_sync_last_run", "")
    finally:
        conn.close()
    return {"injury_sync_enabled": enabled, "last_run": last_run or None,
            "poll_interval_minutes": INJURY_SYNC_INTERVAL_MINUTES}


@router.post("/injury-sync/run")
def trigger_injury_sync():
    """Run one injury-sync pass right now instead of waiting for the next
    scheduled poll."""
    return _run_locked(run_injury_sync_cycle)


# ---------------------------------------------------------------------------
# Automatic stats sync: folds each team's real season point/run
# differential -- straight from ESPN's official standings, not derived
# from anything logged in this app -- into the same situational
# adjustment system as injuries above. This is what lets the model react
# to how a team is actually outscoring opponents *this season*, instead
# of relying only on the thin history this app's own Glicko ratings have
# built up from games logged here.
# ---------------------------------------------------------------------------

STATS_SYNC_INTERVAL_MINUTES = 180  # standings move slowly game-to-game -- no need to poll as often as injuries

# Converts a team's real season point/run differential-per-game into a
# rating-point nudge. Scaled per sport since "differential" means very
# different things across leagues (MLB run differential per game is
# typically single digits; NBA/NFL/NCAAF point differentials run much
# higher) -- calibrated so a genuinely dominant team's edge can rival,
# but not swamp, that sport's own home_adv in ratings.py, then hard-capped
# per sport. get_active_status_adjustment() also caps the *combined*
# total of this + injuries + any manual entry at STATUS_ADJUSTMENT_CAP, so
# nothing here can run away on its own even if these numbers are off.
# Treat this as a tuned heuristic, not a validated statistical model --
# there's no historical backtest behind these exact constants yet.
_STATS_DIFF_SCALE = {"NFL": 3.0, "NBA": 3.0, "MLB": 9.0, "NCAAF": 2.5}
_STATS_ADJUSTMENT_CAP_PER_SPORT = {"NFL": 60.0, "NBA": 60.0, "MLB": 45.0, "NCAAF": 60.0}

# Small-sample dampener: early in a season, a team's games-played count is
# tiny (Week 2 of the NFL means every team has played 1-2 games), so its
# points-differential-per-game is dominated by noise -- one blowout either
# way, and the scaled adjustment above would swing to nearly its full cap
# on a single data point. This is the exact same problem Glicko-2's RD
# already solves for the base rating (a thin history gets less
# confidence) -- this cycle just didn't inherit that safeguard, so it's
# added here explicitly: the adjustment is scaled down by
# games_played / full-confidence-games (capped at 1.0), reaching full
# strength only once a team has played roughly half a season's worth of
# games. A team 2 games into the season now gets a small nudge instead of
# a near-max one; the same real record still reaches full weight later in
# the season without anyone needing to touch this again.
_STATS_FULL_CONFIDENCE_GAMES = {"NFL": 8, "NBA": 20, "MLB": 40, "NCAAF": 6}


def _num(v):
    """Best-effort float parse of whatever ESPN handed back for a stat
    field -- can already be a real number, a numeric string, a signed
    string like '+12', or missing entirely."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        try:
            return float(str(v).replace("+", "").strip())
        except (TypeError, ValueError):
            return None


def run_stats_sync_cycle() -> dict:
    """Pulls each supported sport's real ESPN standings and converts
    every team's season point/run differential into an automatic
    situational adjustment via ratings.replace_auto_team_status (source
    'espn_stats_auto') -- separate from, and additive with, the injury
    sync's 'espn_auto' adjustments above. Re-running this clears and
    re-derives every 'espn_stats_auto' adjustment each time, same pattern
    as injury sync, so it always reflects the current standings instead
    of piling up stale entries."""
    conn = _connect()
    try:
        enabled = _get_setting(conn, "stats_sync_enabled", "true") == "true"
    finally:
        conn.close()
    if not enabled:
        return {"ran": False, "reason": "stats sync is disabled"}

    teams_synced = 0
    for sport in ODDS_SPORT_KEYS:
        try:
            board = espn_stats.get_standings(sport)
        except Exception:
            continue
        rows = board.get("standings") if isinstance(board, dict) else None
        if not rows:
            continue

        scale = _STATS_DIFF_SCALE.get(sport, 3.0)
        cap = _STATS_ADJUSTMENT_CAP_PER_SPORT.get(sport, 50.0)

        for row in rows:
            team = row.get("team")
            if not team:
                continue

            wins, losses = _num(row.get("wins")), _num(row.get("losses"))
            games_played = (wins or 0.0) + (losses or 0.0) if (wins is not None or losses is not None) else None
            if not games_played:
                continue  # no games played yet this season (or ESPN didn't report a record) -- nothing to derive

            points_for, points_against = _num(row.get("points_for")), _num(row.get("points_against"))
            if points_for is not None and points_against is not None:
                per_game_diff = (points_for - points_against) / games_played
            else:
                season_diff = _num(row.get("point_differential"))
                if season_diff is None:
                    continue
                per_game_diff = season_diff / games_played

            full_confidence_games = _STATS_FULL_CONFIDENCE_GAMES.get(sport, 10)
            confidence = min(1.0, games_played / full_confidence_games)
            adjustment = max(-cap, min(cap, per_game_diff * scale * confidence))
            wins_disp = int(wins) if wins is not None else "?"
            losses_disp = int(losses) if losses is not None else "?"
            note = (f"Auto (ESPN standings): {wins_disp}-{losses_disp} "
                    f"({int(games_played)} GP, {confidence * 100:.0f}% weight), {per_game_diff:+.1f} diff/g")

            try:
                replace_auto_team_status(sport, team, adjustment, note, expires_at=None, source="espn_stats_auto")
                teams_synced += 1
            except Exception:
                continue

    conn = _connect()
    try:
        _set_setting(conn, "stats_sync_last_run", datetime.now().isoformat())
    finally:
        conn.close()
    return {"ran": True, "teams_synced": teams_synced}


class StatsSyncToggle(BaseModel):
    enabled: bool


@router.post("/stats-sync/enabled")
def set_stats_sync(payload: StatsSyncToggle):
    conn = _connect()
    try:
        _set_setting(conn, "stats_sync_enabled", "true" if payload.enabled else "false")
    finally:
        conn.close()
    return {"stats_sync_enabled": payload.enabled}


@router.get("/stats-sync/status")
def get_stats_sync_status():
    conn = _connect()
    try:
        enabled = _get_setting(conn, "stats_sync_enabled", "true") == "true"
        last_run = _get_setting(conn, "stats_sync_last_run", "")
    finally:
        conn.close()
    return {"stats_sync_enabled": enabled, "last_run": last_run or None,
            "poll_interval_minutes": STATS_SYNC_INTERVAL_MINUTES}


@router.post("/stats-sync/run")
def trigger_stats_sync():
    """Run one stats-sync pass right now instead of waiting for the next
    scheduled poll."""
    return _run_locked(run_stats_sync_cycle)


@router.post("/espn-sync/run-all")
def trigger_espn_sync_all():
    """Manually runs all three ESPN-driven background cycles right now
    -- auto-settlement (game logging + bet grading), injury sync, and
    stats sync -- instead of waiting on their separate timers (20/60/180
    minutes). One click refreshes the whole rating picture. Each cycle
    still respects its own enabled/disabled toggle, same as triggering
    it individually via its own /run endpoint."""
    return {
        "ran_at": datetime.now().isoformat(),
        "auto_settlement": _run_locked(run_auto_settlement_cycle),
        "injury_sync": _run_locked(run_injury_sync_cycle),
        "stats_sync": _run_locked(run_stats_sync_cycle),
    }



# ---------------------------------------------------------------------------
# Explainability: why a pick was favored
# ---------------------------------------------------------------------------

@router.get("/predict/explain")
def predict_explain(sport: str, home_team: str, away_team: str, game_date: Optional[str] = None):
    """Deterministic breakdown of a matchup prediction -- rating gap,
    confidence level, rest days, and any active situational notes -- without
    going through the LLM agent."""
    return win_probability_breakdown(sport, home_team, away_team, game_date)


# ---------------------------------------------------------------------------
# Calibration / backtesting
# ---------------------------------------------------------------------------

@router.get("/calibration")
def calibration(sport: Optional[str] = None):
    """Buckets every resolved prediction by predicted probability and
    compares it to the actual win rate in that bucket -- the honesty check
    for the model. See sports_agent/ratings.py:get_calibration for the math."""
    return get_calibration(sport)


# ---------------------------------------------------------------------------
# Edge Radar: scan the whole slate instead of one matchup at a time
# ---------------------------------------------------------------------------

@router.get("/edge-radar")
def edge_radar(sport: str = "NFL", min_edge_pct: float = 1.0, bankroll: float = 1000.0,
               risk_profile: str = "Moderate"):
    """Pull every currently-listed game for a sport, run the Glicko-2 model
    against each one, and rank by predicted +EV -- so you see where the
    model actually disagrees with the market instead of checking one
    matchup at a time."""
    games = _fetch_sport_board(sport, markets="h2h")
    fraction = {"Conservative": 0.25, "Moderate": 0.5, "Aggressive": 0.75}.get(risk_profile.title(), 0.5)

    ranked = []
    for game in games:
        home_team, away_team = game.get("home_team"), game.get("away_team")
        if not home_team or not away_team:
            continue

        prices = _best_prices(game)
        best_home, best_away = prices["best_home"], prices["best_away"]

        breakdown = win_probability_breakdown(sport, home_team, away_team)
        home_prob = breakdown["home_win_probability"] / 100.0
        away_prob = breakdown["away_win_probability"] / 100.0
        home_favored = home_prob >= away_prob
        favored_team = home_team if home_favored else away_team
        favored_prob = max(home_prob, away_prob)

        favored_price = None
        favored_book = None
        if home_favored and best_home:
            favored_price, favored_book = best_home
        elif not home_favored and best_away:
            favored_price, favored_book = best_away
        if favored_price is None:
            continue  # no market price on the favored side to compare against

        ev = calculate_ev(favored_prob, favored_price, stake=100.0)
        if ev["ev_percentage"] < min_edge_pct:
            continue
        kelly = kelly_criterion(favored_prob, favored_price, fraction=fraction)

        ranked.append({
            "matchup": f"{away_team} @ {home_team}",
            "commence_time": game.get("commence_time"),
            "favored_team": favored_team,
            "favored_win_probability_pct": round(favored_prob * 100, 1),
            "favored_confidence": breakdown["home_confidence"] if home_favored else breakdown["away_confidence"],
            "best_price": favored_price,
            "best_book": favored_book,
            "edge_pct": ev["ev_percentage"],
            "expected_value": ev["expected_value"],
            "recommended_wager": round(bankroll * (kelly["fractional_kelly_pct"] / 100), 2),
            "kelly_pct": kelly["fractional_kelly_pct"],
        })

    ranked.sort(key=lambda r: r["edge_pct"], reverse=True)
    return {"sport": normalize_sport(sport), "scanned_games": len(games), "opportunities": ranked}


# ---------------------------------------------------------------------------
# Line movement tracking + automatic CLV capture
# ---------------------------------------------------------------------------

LINE_TRACKING_INTERVAL_MINUTES = 15


@router.get("/line-movement")
def line_movement(sport: str, home_team: str, away_team: str):
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT best_home_price, best_home_book, best_away_price, best_away_book, commence_time, captured_at
            FROM odds_snapshots
            WHERE sport = ? AND lower(home_team) = lower(?) AND lower(away_team) = lower(?)
            ORDER BY captured_at ASC
            """,
            [normalize_sport(sport), home_team, away_team],
        ).fetchall()
    finally:
        conn.close()

    snapshots = [
        {"best_home_price": r[0], "best_home_book": r[1], "best_away_price": r[2],
         "best_away_book": r[3], "commence_time": r[4], "captured_at": str(r[5])}
        for r in rows
    ]

    movement = None
    if len(snapshots) >= 2:
        first, last = snapshots[0], snapshots[-1]
        home_shift = None
        if first["best_home_price"] is not None and last["best_home_price"] is not None:
            home_shift = round(
                decimal_to_implied_prob(american_to_decimal(last["best_home_price"]))
                - decimal_to_implied_prob(american_to_decimal(first["best_home_price"])), 2
            )
        movement = {"home_implied_prob_shift_pct": home_shift,
                    "steam_move": home_shift is not None and abs(home_shift) >= 5.0}

    return {"sport": normalize_sport(sport), "matchup": f"{away_team} @ {home_team}",
            "snapshots": snapshots, "movement": movement}


@router.get("/line-movement/alerts")
def line_movement_alerts(min_shift_pct: float = 5.0):
    """Steam-move flags across every matchup currently being tracked (any
    matchup with a captured odds snapshot -- see run_line_tracking_cycle),
    instead of GET /line-movement's one-matchup-at-a-time lookup. Requires
    line tracking to be enabled and to have captured at least two
    snapshots for a matchup before it can detect a shift."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT sport, home_team, away_team, best_home_price, captured_at
            FROM odds_snapshots
            WHERE best_home_price IS NOT NULL
            ORDER BY sport, home_team, away_team, captured_at ASC
            """
        ).fetchall()
    finally:
        conn.close()

    by_matchup: dict = {}
    for sport, home_team, away_team, price, captured_at in rows:
        by_matchup.setdefault((sport, home_team, away_team), []).append((price, captured_at))

    alerts = []
    for (sport, home_team, away_team), points in by_matchup.items():
        if len(points) < 2:
            continue
        first_price, _ = points[0]
        last_price, last_captured = points[-1]
        shift = round(
            decimal_to_implied_prob(american_to_decimal(last_price))
            - decimal_to_implied_prob(american_to_decimal(first_price)), 2
        )
        if abs(shift) >= min_shift_pct:
            alerts.append({
                "sport": sport,
                "matchup": f"{away_team} @ {home_team}",
                "home_team": home_team,
                "away_team": away_team,
                "home_implied_prob_shift_pct": shift,
                "direction": "toward home" if shift > 0 else "toward away",
                "snapshots": len(points),
                "latest_snapshot": str(last_captured),
            })

    alerts.sort(key=lambda a: abs(a["home_implied_prob_shift_pct"]), reverse=True)
    return {"min_shift_pct": min_shift_pct, "alerts": alerts}


class LineTrackingToggle(BaseModel):
    enabled: bool


@router.post("/line-tracking/enabled")
def set_line_tracking(payload: LineTrackingToggle):
    """Line tracking hits a paid, rate-limited API on a schedule, so it
    defaults to OFF -- this is the opt-in switch. It only ever polls for
    matchups you actually have an open (pending) bet on, never the whole
    board, to keep usage bounded."""
    conn = _connect()
    try:
        _set_setting(conn, "line_tracking_enabled", "true" if payload.enabled else "false")
    finally:
        conn.close()
    return {"line_tracking_enabled": payload.enabled}


@router.get("/line-tracking/status")
def get_line_tracking_status():
    conn = _connect()
    try:
        enabled = _get_setting(conn, "line_tracking_enabled", "false") == "true"
        last_run = _get_setting(conn, "line_tracking_last_run", "")
    finally:
        conn.close()
    return {"line_tracking_enabled": enabled, "last_run": last_run or None,
            "poll_interval_minutes": LINE_TRACKING_INTERVAL_MINUTES}


def run_line_tracking_cycle() -> dict:
    """One polling pass: snapshot current best odds for every distinct
    matchup with an open bet, and once that game's commence_time has passed,
    auto-fill closing_odds (and clv_pct) on any pending bet for it that
    doesn't have one yet. A no-op unless POST /line-tracking/enabled has
    been called -- see the module docstring on that endpoint for why."""
    conn = _connect()
    try:
        enabled = _get_setting(conn, "line_tracking_enabled", "false") == "true"
        if not enabled:
            return {"ran": False, "reason": "line tracking is disabled"}

        matchups = conn.execute(
            """
            SELECT DISTINCT sport, home_team, away_team FROM bets
            WHERE status = 'pending' AND home_team IS NOT NULL AND away_team IS NOT NULL
            """
        ).fetchall()
    finally:
        conn.close()

    if not matchups:
        conn = _connect()
        try:
            _set_setting(conn, "line_tracking_last_run", datetime.now().isoformat())
        finally:
            conn.close()
        return {"ran": True, "matchups_tracked": 0}

    snapshots_written = 0
    bets_clv_filled = 0
    boards_cache: dict = {}

    for sport, home_team, away_team in matchups:
        sport_norm = normalize_sport(sport)
        try:
            if sport_norm not in boards_cache:
                boards_cache[sport_norm] = _fetch_sport_board(sport_norm, markets="h2h")
            board = boards_cache[sport_norm]
        except HTTPException:
            continue  # missing API key / request failure this cycle -- retry next poll

        game = next(
            (g for g in board
             if home_team.lower() in g.get("home_team", "").lower()
             and away_team.lower() in g.get("away_team", "").lower()),
            None,
        )
        if not game:
            continue

        prices = _best_prices(game)
        best_home, best_away = prices["best_home"], prices["best_away"]
        commence_time = game.get("commence_time")

        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO odds_snapshots (sport, home_team, away_team, best_home_price, best_home_book,
                                             best_away_price, best_away_book, commence_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [sport_norm, home_team, away_team,
                 best_home[0] if best_home else None, best_home[1] if best_home else None,
                 best_away[0] if best_away else None, best_away[1] if best_away else None,
                 commence_time],
            )
            snapshots_written += 1

            game_started = False
            if commence_time:
                try:
                    game_started = datetime.fromisoformat(
                        commence_time.replace("Z", "+00:00")
                    ) <= datetime.now(timezone.utc)
                except ValueError:
                    game_started = False

            if game_started:
                pending_bets = conn.execute(
                    """
                    SELECT id, selection, odds FROM bets
                    WHERE status = 'pending' AND closing_odds IS NULL
                      AND sport = ? AND lower(home_team) = lower(?) AND lower(away_team) = lower(?)
                    """,
                    [sport_norm, home_team, away_team],
                ).fetchall()
                for bet_id, selection, odds in pending_bets:
                    sel_lower = (selection or "").lower()
                    if best_home and home_team.lower() in sel_lower:
                        closing_price = best_home[0]
                    elif best_away and away_team.lower() in sel_lower:
                        closing_price = best_away[0]
                    else:
                        continue  # selection text doesn't clearly map to a side -- leave for manual grading

                    opened_implied = decimal_to_implied_prob(american_to_decimal(odds))
                    closed_implied = decimal_to_implied_prob(american_to_decimal(closing_price))
                    clv_pct = round(closed_implied - opened_implied, 2)

                    conn.execute(
                        "UPDATE bets SET closing_odds = ?, clv_pct = ? WHERE id = ? AND closing_odds IS NULL",
                        [closing_price, clv_pct, bet_id],
                    )
                    bets_clv_filled += 1
        finally:
            _set_setting(conn, "line_tracking_last_run", datetime.now().isoformat())
            conn.close()

    return {"ran": True, "matchups_tracked": len(matchups),
            "snapshots_written": snapshots_written, "bets_auto_clv_filled": bets_clv_filled}


# ---------------------------------------------------------------------------
# Daily schedule: every game for a sport, market favorite/underdog next to
# the model's own pick
# ---------------------------------------------------------------------------

@router.get("/schedule")
def schedule(sport: str = "NFL", date: Optional[str] = None):
    """Every currently-listed game for a sport, with the market's
    favorite/underdog (from the best price across books) shown next to the
    model's own favorite and win probability -- so you can see at a glance
    where the model agrees or disagrees with the market for the day.

    The Odds API board isn't literally scoped to "today" -- it's whatever
    games are currently listed (can span several days out depending on the
    sport/season). Pass `date` (YYYY-MM-DD, matched against each game's UTC
    commence date) to narrow to one day; omit it to see the whole board."""
    games = _fetch_sport_board(sport, markets="h2h")
    sport_norm = normalize_sport(sport)

    slate = []
    for game in games:
        home_team, away_team = game.get("home_team"), game.get("away_team")
        commence_time = game.get("commence_time")
        if not home_team or not away_team:
            continue
        if date and (not commence_time or commence_time[:10] != date):
            continue

        prices = _best_prices(game)
        best_home, best_away = prices["best_home"], prices["best_away"]

        market_favorite = None
        market_underdog = None
        if best_home and best_away:
            # Lower American odds = more favored (negative beats positive,
            # more-negative beats less-negative).
            if best_home[0] < best_away[0]:
                market_favorite = {"team": home_team, "price": best_home[0], "book": best_home[1]}
                market_underdog = {"team": away_team, "price": best_away[0], "book": best_away[1]}
            else:
                market_favorite = {"team": away_team, "price": best_away[0], "book": best_away[1]}
                market_underdog = {"team": home_team, "price": best_home[0], "book": best_home[1]}

        breakdown = win_probability_breakdown(sport, home_team, away_team)
        home_favored = breakdown["home_win_probability"] >= breakdown["away_win_probability"]
        model_favorite = home_team if home_favored else away_team
        model_win_probability_pct = breakdown["home_win_probability"] if home_favored else breakdown["away_win_probability"]
        model_confidence = breakdown["home_confidence"] if home_favored else breakdown["away_confidence"]

        slate.append({
            "matchup": f"{away_team} @ {home_team}",
            "home_team": home_team,
            "away_team": away_team,
            "commence_time": commence_time,
            "market_favorite": market_favorite,
            "market_underdog": market_underdog,
            "model_favorite": model_favorite,
            "model_win_probability_pct": model_win_probability_pct,
            "model_confidence": model_confidence,
            "model_agrees_with_market": (market_favorite is not None
                                          and market_favorite["team"] == model_favorite),
        })

    slate.sort(key=lambda g: g["commence_time"] or "")
    return {"sport": sport_norm, "date": date, "scanned_games": len(games), "games": slate}


# ---------------------------------------------------------------------------
# Your own record (derived from logged game_results -- no external source)
# ---------------------------------------------------------------------------

@router.get("/my-record/{sport}")
def my_record(sport: str):
    """Win-loss record, points-per-game and points-allowed, computed purely
    from games YOU'VE logged via POST /games/result. A team you haven't
    logged a result for won't appear -- for official league-wide standings
    see GET /espn/standings instead."""
    return {"sport": normalize_sport(sport), "standings": get_standings(sport)}


# ---------------------------------------------------------------------------
# Real stats/standings/rosters from ESPN's public (unofficial) API -- see
# sports_agent/espn_stats.py's module docstring for the caveats.
# ---------------------------------------------------------------------------

@router.get("/espn/schedule")
def espn_schedule(sport: str = "NFL", date: Optional[str] = None):
    """ESPN's own scoreboard for a sport/date -- includes probable pitchers
    for MLB when ESPN has them listed, which The Odds API never provides."""
    return espn_stats.get_scoreboard(sport, date)


@router.get("/espn/standings")
def espn_standings(sport: str = "NFL"):
    """Official current-season standings, straight from ESPN."""
    return espn_stats.get_standings(sport)


@router.get("/espn/team-stats")
def espn_team_stats(sport: str, team: str):
    """Team season stats (points per game, yards per game, etc.)."""
    return espn_stats.get_team_stats(sport, team)


@router.get("/espn/roster")
def espn_roster(sport: str, team: str):
    """A team's current roster -- for looking up a player by name before
    pulling their individual stats."""
    return espn_stats.get_team_roster(sport, team)


@router.get("/espn/injuries")
def espn_injuries(sport: str = "NFL", team: str = ""):
    """Current ESPN injury report for one team -- the same data the
    automatic injury sync (see run_injury_sync_cycle) uses to adjust
    ratings, exposed directly for the dashboard/debugging."""
    if not team:
        raise HTTPException(status_code=400, detail="team is required")
    return espn_stats.get_team_injuries(sport, team)


@router.get("/espn/player-stats")
def espn_player_stats(sport: str, team: str, player: str):
    """One player's season stats, looked up on demand by name against their
    team's roster (not preloaded for every player on every team)."""
    return espn_stats.get_player_stats(sport, team, player)


# ---------------------------------------------------------------------------
# Debug: raw ESPN response passthrough
# ---------------------------------------------------------------------------

@router.get("/espn/debug/roster-raw")
def espn_debug_roster_raw(sport: str, team: str):
    """Returns ESPN's roster response completely unparsed. The parsing in
    espn_stats.py was written blind (no live network access while building
    it -- see that module's docstring), so when a lookup like player search
    comes back empty, this is the fastest way to see exactly what ESPN
    actually sent back and fix the parsing to match it precisely instead of
    guessing again."""
    cfg = espn_stats._espn_cfg(sport)
    if not cfg:
        raise HTTPException(status_code=400, detail=f"No ESPN mapping for sport '{sport}'")
    try:
        team_id = espn_stats._resolve_team_id(sport, team)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not load ESPN team list: {e}")
    if not team_id:
        raise HTTPException(status_code=404, detail=f"Couldn't match '{team}' to an ESPN team")
    try:
        return espn_stats._get(f"{espn_stats.SITE_BASE}/{cfg['sport']}/{cfg['league']}/teams/{team_id}/roster")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ESPN roster request failed: {e}")


@router.get("/espn/debug/teams")
def espn_debug_teams(sport: str = "NFL"):
    """The resolved name->ESPN-team-id map espn_stats.py actually built for
    a sport, plus how many raw team entries ESPN returned. If a team name
    that should obviously match isn't a key here, that's the bug -- and this
    shows exactly what's in the map without guessing."""
    cfg = espn_stats._espn_cfg(sport)
    if not cfg:
        raise HTTPException(status_code=400, detail=f"No ESPN mapping for sport '{sport}'")
    try:
        raw = espn_stats._get(f"{espn_stats.SITE_BASE}/{cfg['sport']}/{cfg['league']}/teams", {"limit": 999})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ESPN teams request failed: {e}")
    try:
        id_map = espn_stats._team_id_map(sport)
    except Exception as e:
        id_map = {"error": str(e)}
    raw_team_count = len((((raw.get("sports") or [{}])[0].get("leagues") or [{}])[0].get("teams")) or [])
    return {"sport": normalize_sport(sport), "raw_team_count": raw_team_count, "resolved_name_map": id_map}

@router.get("/espn/debug/player-match")
def espn_debug_player_match(sport: str, team: str, player: str):
    """Runs the exact same roster fetch + name-match logic get_player_stats
    uses (not a re-implementation), and reports every intermediate step:
    the resolved team id, how many athletes the roster parse produced, the
    full list of names it saw, and whether/how the requested player name
    matched. If a player is "clearly on the roster" per the raw JSON but
    this still shows him missing from `roster_names`, the bug is in
    get_team_roster's parsing. If he's present in `roster_names` but
    `matched` is still false, the bug is in the name-matching logic."""
    roster = espn_stats.get_team_roster(sport, team)
    if "error" in roster:
        return {"stage": "roster_fetch", **roster}
    names = [p.get("name") for p in roster.get("roster", [])]
    needle = player.lower().strip()
    matched = [n for n in names if n and needle in n.lower()]
    return {
        "sport": normalize_sport(sport),
        "team_requested": team,
        "espn_team_id": roster.get("espn_team_id"),
        "roster_size": len(names),
        "roster_names": names,
        "player_requested": player,
        "matched": matched,
    }

@router.get("/espn/debug/player-stats-raw")
def espn_debug_player_stats_raw(sport: str, team: str, player: str):
    """For a matched player, tries every candidate stats URL and reports
    exactly what each one returned -- the raw response on success, or the
    exact error on failure. Building get_player_stats's stat-fetch step
    guessed at ESPN's shape without live access (see espn_stats.py's
    docstring); this replaces guessing a third time with ground truth."""
    cfg = espn_stats._espn_cfg(sport)
    if not cfg:
        raise HTTPException(status_code=400, detail=f"No ESPN mapping for sport '{sport}'")

    roster = espn_stats.get_team_roster(sport, team)
    if "error" in roster:
        return {"stage": "roster_fetch", **roster}

    match = espn_stats._match_player(roster["roster"], player)
    if not match:
        return {"stage": "player_match", "error": f"'{player}' not found on {team}'s roster",
                "roster_size": len(roster["roster"])}

    results = []
    for url in espn_stats._player_stat_urls(cfg, match["id"]):
        entry = {"url": url}
        try:
            entry["ok"] = True
            entry["data"] = espn_stats._get(url)
        except Exception as e:
            entry["ok"] = False
            entry["error"] = str(e)
        results.append(entry)

    return {
        "sport": normalize_sport(sport),
        "team_requested": team,
        "matched_player": match,
        "attempts": results,
    }

@router.get("/espn/debug/injuries-raw")
def espn_debug_injuries_raw(sport: str, team: str):
    """Raw, unparsed ESPN injuries payload for one team -- pull this if
    GET /espn/injuries or the auto injury sync ever comes back empty for a
    team you know has a real injury report; see get_team_injuries's
    docstring for why the shape is unverified."""
    cfg = espn_stats._espn_cfg(sport)
    if not cfg:
        raise HTTPException(status_code=400, detail=f"No ESPN mapping for sport '{sport}'")
    try:
        team_id = espn_stats._resolve_team_id(sport, team)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not load ESPN team list: {e}")
    if not team_id:
        raise HTTPException(status_code=404, detail=f"Couldn't match '{team}' to an ESPN team")
    try:
        data = espn_stats._get(
            f"{espn_stats.SITE_BASE}/{cfg['sport']}/{cfg['league']}/teams/{team_id}/injuries"
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return data


@router.get("/espn/debug/gamelog-shape")
def espn_debug_gamelog_shape(sport: str, team: str, player: str):
    """Compact structural summary of one player's real gamelog response --
    top-level keys, categories/names metadata, and for the single most
    recent event: every key it has, each one's type, and (for lists) its
    length plus a one-item preview. Built to nail down exactly where the
    per-game stat VALUES live without dumping the whole (large, easily
    truncated-in-transit) raw response again."""
    cfg = espn_stats._espn_cfg(sport)
    if not cfg:
        raise HTTPException(status_code=400, detail=f"No ESPN mapping for sport '{sport}'")
    roster = espn_stats.get_team_roster(sport, team)
    if "error" in roster:
        return {"stage": "roster_fetch", **roster}
    match = espn_stats._match_player(roster["roster"], player)
    if not match:
        return {"stage": "player_match", "error": f"'{player}' not found on {team}'s roster"}

    url = f"{espn_stats.WEB_BASE}/{cfg['sport']}/{cfg['league']}/athletes/{match['id']}/gamelog"
    try:
        data = espn_stats._get(url)
    except Exception as e:
        return {"stage": "gamelog_fetch", "url": url, "error": str(e)}

    def describe(v):
        if isinstance(v, list):
            return {"type": "list", "length": len(v), "first_item": v[0] if v else None}
        if isinstance(v, dict):
            return {"type": "dict", "keys": list(v.keys())}
        return {"type": type(v).__name__, "value": v}

    events = data.get("events") or {}
    latest_id = max(events, key=lambda k: (events.get(k) or {}).get("gameDate") or "") if events else None
    latest_event = events.get(latest_id) if latest_id else None

    def describe_deep(v, depth=2):
        if depth <= 0:
            return describe(v)
        if isinstance(v, list):
            return {"type": "list", "length": len(v),
                    "first_item": describe_deep(v[0], depth - 1) if v else None}
        if isinstance(v, dict):
            return {"type": "dict", "keys": list(v.keys()),
                    "values": {k: describe_deep(v2, depth - 1) for k, v2 in v.items()}}
        return {"type": type(v).__name__, "value": v}

    return {
        "matched_player": match,
        "top_level_keys": list(data.keys()),
        "categories": data.get("categories"),
        "names_count": len(data.get("names") or []),
        "names": data.get("names"),
        "event_count": len(events),
        "latest_event_id": latest_id,
        "latest_event_field_shapes": {k: describe(v) for k, v in (latest_event or {}).items()} if latest_event else None,
        "seasonTypes_shape": describe_deep(data.get("seasonTypes")),
        "filters_shape": describe_deep(data.get("filters")),
        "glossary_shape": describe(data.get("glossary")),
    }
