"""
Real team/player stats and standings, pulled from ESPN's public site API.

The Odds API (the app's other external dependency) only ever returns betting
lines -- it has no standings, box scores, rosters, or player stats. ESPN's
site API (site.api.espn.com) does, and needs no signup or API key, but it is
NOT an official/documented API -- it's the same JSON ESPN's own website and
apps consume, widely used by hobby projects, but Disney/ESPN could change or
remove it without notice and there's no SLA. Every function here is written
defensively (try/except, .get() everywhere) and returns {"error": ...}
instead of raising, so one broken field never takes the whole endpoint down --
but if ESPN changes their response shape, individual fields can come back
empty until this file is updated to match.

NOTE: outbound network from the sandbox this was written in is restricted to
an allowlist that doesn't include espn.com, so these calls could not be
tested against a live response while writing them. They're built from
ESPN's well-documented (by the hobbyist community) and years-stable URL
patterns, but the very first real call on your machine is this code's real
test -- if a field looks wrong or empty, that's the signal something in
ESPN's JSON shape has drifted from what's assumed here.
"""
import json
import os
import re
import time
import unicodedata

try:
    # curl_cffi impersonates a real browser's TLS/HTTP2 fingerprint (cipher
    # suite order, extensions, ALPN, header order -- not just the User-Agent
    # string). ESPN's site API sits behind bot-mitigation that keys off
    # exactly that fingerprint: a plain `requests` call gets a 403 even with
    # browser-shaped headers, while an actual browser hitting the same URL
    # works fine -- confirmed live against this app's real traffic. If
    # curl_cffi isn't installed yet (pip install -r requirements.txt), fall
    # back to plain `requests`, which will very likely keep 403ing.
    from curl_cffi import requests as _http
    _IMPERSONATE = "chrome"
except ImportError:
    import requests as _http
    _IMPERSONATE = None

from sports_agent.ratings import normalize_sport

SITE_BASE = "https://site.api.espn.com/apis/site/v2/sports"
V2_BASE = "https://site.api.espn.com/apis/v2/sports"
# Two more ESPN hosts, used only for per-player stats/gamelog -- the site API
# above doesn't have a clean single endpoint for that. Community-documented,
# still unverified against a live response (see module docstring).
WEB_BASE = "https://site.web.api.espn.com/apis/common/v3/sports"
CORE_BASE = "https://sports.core.api.espn.com/v2/sports"

SPORT_ESPN = {
    "NFL":   {"sport": "football", "league": "nfl"},
    "NBA":   {"sport": "basketball", "league": "nba"},
    "MLB":   {"sport": "baseball", "league": "mlb"},
    "NCAAF": {"sport": "football", "league": "college-football"},
}

_team_id_cache: dict = {}  # sport -> {lowercased name/alias: espn team id}

_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_TEAM_CACHE_FILE = os.path.join(_CACHE_DIR, "espn_team_cache.json")
_TEAM_CACHE_TTL_SECONDS = 24 * 60 * 60  # team rosters/ids barely change; a day is safe


def _espn_cfg(sport: str):
    return SPORT_ESPN.get(normalize_sport(sport))


_HEADERS = {
    # ESPN's site API is unofficial and unauthenticated, and sits behind
    # standard bot-mitigation (Akamai/Cloudflare-style). A browser-shaped
    # header set (including a plausible Referer/Origin) makes requests look
    # like they came from espn.com itself rather than a bare script -- some
    # of these checks key on exactly that. This reduces but does not
    # eliminate the chance of being challenged/blocked.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.espn.com/",
    "Origin": "https://www.espn.com",
}

# Simple politeness throttle: never fire ESPN requests faster than this
# apart, process-wide. Bursts of rapid requests (e.g. building the team-id
# map for several sports back to back, or repeated debug calls) are the
# most likely thing to trip bot-mitigation and get the whole IP blocked --
# spacing calls out costs a few hundred ms and meaningfully lowers that risk.
_MIN_REQUEST_INTERVAL = 0.35
_last_request_at = 0.0


def _get(url: str, params: dict | None = None) -> dict:
    global _last_request_at
    last_exc = None
    for attempt in range(2):
        wait = _MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        try:
            kwargs = {"params": params or {}, "headers": _HEADERS, "timeout": 12}
            if _IMPERSONATE:
                kwargs["impersonate"] = _IMPERSONATE
            resp = _http.get(url, **kwargs)
            _last_request_at = time.monotonic()
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            _last_request_at = time.monotonic()
            last_exc = e
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 403:
                raise Exception(
                    "403 Forbidden -- ESPN's bot-mitigation is currently blocking requests from this "
                    "network. This is almost always temporary (it clears on its own, typically within "
                    "minutes to a day) and is usually triggered by a burst of requests in a short window. "
                    f"Original error: {e}"
                ) from e
            if status and status not in (429, 500, 502, 503, 504):
                break  # not a transient failure (e.g. 404) -- don't retry
    raise last_exc


def _load_team_cache() -> dict:
    try:
        with open(_TEAM_CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_team_cache(all_sports: dict) -> None:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_TEAM_CACHE_FILE, "w") as f:
            json.dump(all_sports, f)
    except OSError:
        pass  # caching is an optimization, not a requirement -- never let it break a lookup


def get_scoreboard(sport: str, date: str | None = None) -> dict:
    """Today's (or a given date's) games from ESPN, including probable
    pitchers for MLB when ESPN has them listed -- something The Odds API
    never provides."""
    cfg = _espn_cfg(sport)
    if not cfg:
        return {"error": f"No ESPN mapping for sport '{sport}'"}
    params = {}
    if date:
        params["dates"] = date.replace("-", "")
    try:
        data = _get(f"{SITE_BASE}/{cfg['sport']}/{cfg['league']}/scoreboard", params)
    except Exception as e:
        return {"error": f"ESPN scoreboard request failed: {e}"}

    games = []
    for event in data.get("events", []):
        comp = (event.get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})

        game = {
            "espn_event_id": event.get("id"),
            "name": event.get("name"),
            "date": event.get("date"),
            "status": ((event.get("status") or {}).get("type") or {}).get("description"),
            "home_team": (home.get("team") or {}).get("displayName"),
            "away_team": (away.get("team") or {}).get("displayName"),
            "home_score": home.get("score"),
            "away_score": away.get("score"),
        }

        probables = {}
        for c in competitors:
            probs = c.get("probables")
            if not probs:
                continue
            p0 = probs[0] if isinstance(probs, list) and probs else probs
            athlete = (p0.get("athlete") or {}) if isinstance(p0, dict) else {}
            name = athlete.get("displayName") or athlete.get("shortName")
            if name:
                probables[c.get("homeAway", "unknown")] = name
        if probables:
            game["probable_pitchers"] = probables

        games.append(game)

    return {"sport": normalize_sport(sport), "date": date, "games": games}


def _flatten_stats(stat_list) -> dict:
    out = {}
    for s in stat_list or []:
        if not isinstance(s, dict):
            continue
        key = s.get("name") or s.get("abbreviation") or s.get("displayName")
        if key:
            out[key] = s.get("value", s.get("displayValue"))
    return out


def get_standings(sport: str) -> dict:
    """Official current-season standings, straight from ESPN -- not derived
    from anything you've logged."""
    cfg = _espn_cfg(sport)
    if not cfg:
        return {"error": f"No ESPN mapping for sport '{sport}'"}
    try:
        data = _get(f"{V2_BASE}/{cfg['sport']}/{cfg['league']}/standings")
    except Exception as e:
        return {"error": f"ESPN standings request failed: {e}"}

    rows = []

    def walk(node: dict, group_name: str | None):
        standings = node.get("standings")
        if standings and standings.get("entries"):
            for entry in standings["entries"]:
                stats = _flatten_stats(entry.get("stats"))
                rows.append({
                    "team": (entry.get("team") or {}).get("displayName"),
                    "group": group_name or node.get("name"),
                    "wins": stats.get("wins"),
                    "losses": stats.get("losses"),
                    "win_pct": stats.get("winPercent"),
                    "points_for": stats.get("pointsFor"),
                    "points_against": stats.get("pointsAgainst"),
                    "point_differential": stats.get("differential") or stats.get("pointDifferential"),
                    "streak": stats.get("streak"),
                })
        for child in node.get("children", []) or []:
            walk(child, node.get("name"))

    walk(data, None)
    if not rows:
        # Some leagues return a flat (non-conference) shape at the top level.
        walk({"standings": data.get("standings", {}), "children": []}, None)

    return {"sport": normalize_sport(sport), "standings": rows}


def _team_id_map(sport: str) -> dict:
    sport_norm = normalize_sport(sport)
    if sport_norm in _team_id_cache:
        return _team_id_cache[sport_norm]

    on_disk = _load_team_cache()
    entry = on_disk.get(sport_norm)
    if entry and (time.time() - entry.get("fetched_at", 0)) < _TEAM_CACHE_TTL_SECONDS:
        _team_id_cache[sport_norm] = entry["mapping"]
        return entry["mapping"]

    cfg = _espn_cfg(sport_norm)
    try:
        data = _get(f"{SITE_BASE}/{cfg['sport']}/{cfg['league']}/teams", {"limit": 999})
    except Exception:
        # Live fetch failed (e.g. ESPN is blocking us right now) -- fall back
        # to a stale on-disk copy rather than failing every lookup outright.
        # Team ids essentially never change, so even a week-old map is fine.
        if entry:
            _team_id_cache[sport_norm] = entry["mapping"]
            return entry["mapping"]
        raise

    teams = (((data.get("sports") or [{}])[0].get("leagues") or [{}])[0].get("teams")) or []
    mapping: dict = {}
    for t in teams:
        team = t.get("team", {})
        team_id = team.get("id")
        if not team_id:
            continue
        for key in ["displayName", "shortDisplayName", "name", "location", "abbreviation"]:
            val = team.get(key)
            if val:
                mapping.setdefault(val.lower(), team_id)
    _team_id_cache[sport_norm] = mapping

    on_disk[sport_norm] = {"mapping": mapping, "fetched_at": time.time()}
    _save_team_cache(on_disk)
    return mapping


def _resolve_team_id(sport: str, team_name: str):
    id_map = _team_id_map(sport)
    exact = id_map.get(team_name.lower())
    if exact:
        return exact
    return next((v for k, v in id_map.items() if team_name.lower() in k or k in team_name.lower()), None)


def get_team_stats(sport: str, team_name: str) -> dict:
    """Team-level season stats (points per game, yards per game, etc. --
    whatever categories ESPN reports for that sport)."""
    cfg = _espn_cfg(sport)
    if not cfg:
        return {"error": f"No ESPN mapping for sport '{sport}'"}
    try:
        team_id = _resolve_team_id(sport, team_name)
    except Exception as e:
        return {"error": f"Could not load ESPN team list: {e}"}
    if not team_id:
        return {"error": f"Couldn't match '{team_name}' to an ESPN team"}

    try:
        data = _get(f"{SITE_BASE}/{cfg['sport']}/{cfg['league']}/teams/{team_id}/statistics")
    except Exception as e:
        return {"error": f"ESPN team stats request failed: {e}"}

    stats_out: dict = {}
    try:
        results = data.get("results") or data.get("team") or {}
        categories = (results.get("stats") or {}).get("categories") or data.get("splits", {}).get("categories") or []
        for cat in categories:
            cat_name = cat.get("displayName") or cat.get("name") or "general"
            for s in cat.get("stats", []) or []:
                label = s.get("displayName") or s.get("name")
                if label:
                    stats_out[f"{cat_name}: {label}"] = s.get("displayValue", s.get("value"))
    except Exception:
        pass  # leave stats_out as whatever was parsed before the failure

    return {"sport": normalize_sport(sport), "team": team_name, "espn_team_id": team_id, "stats": stats_out}


def get_team_roster(sport: str, team_name: str) -> dict:
    cfg = _espn_cfg(sport)
    if not cfg:
        return {"error": f"No ESPN mapping for sport '{sport}'"}
    try:
        team_id = _resolve_team_id(sport, team_name)
    except Exception as e:
        return {"error": f"Could not load ESPN team list: {e}"}
    if not team_id:
        return {"error": f"Couldn't match '{team_name}' to an ESPN team"}

    try:
        data = _get(f"{SITE_BASE}/{cfg['sport']}/{cfg['league']}/teams/{team_id}/roster")
    except Exception as e:
        return {"error": f"ESPN roster request failed: {e}"}

    athletes = []
    for group in data.get("athletes", []) or []:
        items = group.get("items") if isinstance(group, dict) and "items" in group else [group]
        for a in items or []:
            if not isinstance(a, dict) or not a.get("id"):
                continue
            athletes.append({
                "id": a.get("id"),
                "name": a.get("fullName") or a.get("displayName"),
                "position": ((a.get("position") or {}).get("abbreviation")),
                "jersey": a.get("jersey"),
            })

    return {"sport": normalize_sport(sport), "team": team_name, "espn_team_id": team_id, "roster": athletes}



_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _normalize_name(name: str) -> str:
    """Lowercases, strips accents/punctuation, and drops generational
    suffixes so "Baker Mayfield", "baker mayfield.", and "Mayfield, Baker
    Jr." all reduce to a comparable token set. Used for player-name
    matching against ESPN roster data, which is inconsistent about
    periods/apostrophes across players."""
    if not name:
        return ""
    normalized = unicodedata.normalize("NFKD", name)
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized.lower())
    tokens = [t for t in normalized.split() if t not in _SUFFIXES]
    return " ".join(tokens)



def _match_player(roster_list: list, player_name: str):
    """Fuzzy-matches player_name against a roster list (as returned by
    get_team_roster), reused by get_player_stats and the debug endpoint so
    they can never disagree about who matched."""
    needle = _normalize_name(player_name)
    needle_tokens = set(needle.split())

    def _score(candidate_name: str) -> int:
        norm = _normalize_name(candidate_name)
        if not norm:
            return 0
        if norm == needle:
            return 3  # exact (post-normalization) match
        if needle and (needle in norm or norm in needle):
            return 2  # substring either direction (handles nicknames, initials)
        cand_tokens = set(norm.split())
        if needle_tokens and needle_tokens.issubset(cand_tokens):
            return 2  # every word the user typed appears in the candidate
        if needle_tokens & cand_tokens:
            return 1  # partial word overlap (e.g. last name only)
        return 0

    scored = sorted(
        ((p, _score(p.get("name", ""))) for p in roster_list if p.get("name")),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return scored[0][0] if scored and scored[0][1] > 0 else None


def _player_stat_urls(cfg: dict, player_id) -> list:
    """Candidate URLs for one player's stats, most-likely-correct first.
    ESPN's site API (SITE_BASE) has no single documented endpoint for this;
    these are community-documented shapes across three different ESPN
    hosts, still unverified against a live response (see module docstring).
    Kept as a list (rather than picking one) precisely because which of
    these actually works has not been confirmed yet."""
    import datetime
    year = datetime.date.today().year
    return [
        f"{WEB_BASE}/{cfg['sport']}/{cfg['league']}/athletes/{player_id}/gamelog",
        f"{CORE_BASE}/{cfg['sport']}/leagues/{cfg['league']}/seasons/{year}/types/2/athletes/{player_id}/statistics",
        f"{CORE_BASE}/{cfg['sport']}/leagues/{cfg['league']}/seasons/{year - 1}/types/2/athletes/{player_id}/statistics",
        f"{SITE_BASE}/{cfg['sport']}/{cfg['league']}/athletes/{player_id}/stats",
        f"{SITE_BASE}/{cfg['sport']}/{cfg['league']}/athletes/{player_id}",
    ]



def _parse_stat_response(stat_data: dict) -> dict:
    """Handles the response shapes seen from the URLs _player_stat_urls
    tries. The primary one (the gamelog endpoint) is now CONFIRMED live
    against real ESPN data (Baker Mayfield, Sept 2026 -- see FEATURES.md):
    top-level `events` is metadata only (opponent/date/score/links, no
    stat values), and the actual numbers live in
    `seasonTypes[].categories[].events[].stats` (one game's stat line,
    matched by eventId) and `...categories[].totals` (season totals) --
    both flat lists aligned 1:1 with the top-level `names`/`displayNames`.
    Falls back to a core-API-style splits.categories[].stats[] shape,
    unconfirmed, for any sport/path that might return that instead.
    Returns a flat {label: value} dict; empty if nothing usable (e.g. a
    player with zero games logged yet this season)."""
    if not isinstance(stat_data, dict):
        return {}

    season_types = stat_data.get("seasonTypes")
    names = stat_data.get("names")
    events_meta = stat_data.get("events")
    if isinstance(season_types, list) and season_types and isinstance(names, list) and names:
        display_names = stat_data.get("displayNames") or names
        out: dict = {}
        season_type = season_types[0]
        if season_type.get("displayName"):
            out["Season"] = season_type["displayName"]

        most_recent_id = None
        if isinstance(events_meta, dict) and events_meta:
            most_recent_id = max(events_meta, key=lambda k: (events_meta.get(k) or {}).get("gameDate") or "")
            ev_meta = events_meta.get(most_recent_id) or {}
            opponent = (ev_meta.get("opponent") or {}).get("displayName") or (ev_meta.get("opponent") or {}).get("abbreviation")
            if opponent:
                out["Most recent game"] = f"{ev_meta.get('atVs', 'vs')} {opponent} ({str(ev_meta.get('gameDate', ''))[:10]})"
            result_bits = " ".join(str(x) for x in [ev_meta.get("gameResult"), ev_meta.get("score")] if x)
            if result_bits:
                out["Result"] = result_bits

        game_stats = None
        season_totals = None
        for cat in season_type.get("categories") or []:
            if season_totals is None and isinstance(cat.get("totals"), list):
                season_totals = cat["totals"]
            if most_recent_id and game_stats is None:
                match = next((e for e in cat.get("events") or []
                              if str(e.get("eventId")) == str(most_recent_id)), None)
                if match and isinstance(match.get("stats"), list):
                    game_stats = match["stats"]

        values, prefix = (game_stats, "") if game_stats else (season_totals, "Season ")
        if values and len(values) == len(display_names):
            for label, val in zip(display_names, values):
                if val not in (None, ""):
                    out[f"{prefix}{label}"] = val
        return out

    splits = stat_data.get("splits") or (stat_data.get("statistics") or {}).get("splits") or {}
    out = {}
    for cat in splits.get("categories", []) or []:
        cat_name = cat.get("displayName") or cat.get("name") or "general"
        for s in cat.get("stats", []) or []:
            label = s.get("displayName") or s.get("name")
            if label:
                out[f"{cat_name}: {label}"] = s.get("displayValue", s.get("value"))
    return out


def get_player_stats(sport: str, team_name: str, player_name: str) -> dict:
    """On-demand lookup: one player's season stats. Resolves the player by
    (fuzzy) name match against their team's roster first, since ESPN's
    public API has no simple cross-league player name search."""
    roster = get_team_roster(sport, team_name)
    if "error" in roster:
        return roster

    match = _match_player(roster["roster"], player_name)
    if not match:
        close = [p.get("name") for p in roster["roster"][:8] if p.get("name")]
        hint = f" Roster has {len(roster['roster'])} players, e.g.: {', '.join(close)}." if close else " Roster came back empty."
        return {"error": f"'{player_name}' not found on {team_name}'s current roster.{hint}"}

    cfg = _espn_cfg(sport)
    stats_out: dict = {}
    for url in _player_stat_urls(cfg, match["id"]):
        try:
            stat_data = _get(url)
        except Exception:
            continue
        try:
            parsed = _parse_stat_response(stat_data)
        except Exception:
            parsed = {}
        if parsed:
            stats_out = parsed
            break
        # Fetch succeeded but had nothing usable (e.g. a gamelog with zero
        # games played yet this season) -- keep trying the next candidate
        # rather than stopping on a technically-successful empty response.

    if not stats_out:
        return {"player": match["name"], "team": team_name, "position": match.get("position"),
                "error": "ESPN didn't return usable stats for this player through any known endpoint shape "
                         "(they may not have played yet this season)"}

    return {
        "player": match["name"],
        "team": team_name,
        "position": match.get("position"),
        "jersey": match.get("jersey"),
        "stats": stats_out,
        "stats_available": bool(stats_out),
    }
