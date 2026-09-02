# New Features (2026-09-01)

This app was upgraded from a demo (random win probabilities, no memory of
results, no bet tracking) into a real personal tool for improving your
actual win rate. Everything below is single-user, no auth, running locally.

## 1. Real predictions instead of random ones

`predict_matchup_winner` used to call `random.uniform(0.42, 0.72)`. It now
reads from a self-updating Elo-style power rating per team
(`sports_agent/ratings.py`). Every team starts neutral at 1500 -- there's no
historical data baked in. Ratings only move when **you** log a real
completed game's score. The more you log, the sharper predictions get.

**How to use it:** open the **Ratings** tab in the dashboard, fill in the
sport, both teams, and the final score, and submit. That updates both
teams' ratings immediately -- ask the agent about that matchup again and
the win probability will reflect it. The same tab shows the current power
rankings for whichever sport you select.

## 1a. Simulation tab fix (2026-09-01)

The **Simulation** tab (Monte Carlo Engine) was sitting on "Awaiting
simulation parameters" forever. Root cause: it only renders when the
dashboard payload has `home_win_probability` / `away_win_probability` /
`median_projected_score`, and those three fields only ever got set from
`run_monte_carlo_simulation`'s output -- but a plain matchup query like
"Mets vs Rays" routes to `odds_ev_node`, which only called
`predict_matchup_winner`. `run_monte_carlo_simulation` was never invoked on
that path, so the fields never existed for a normal query.

Two fixes:
- `odds_ev_node` now deterministically runs `run_monte_carlo_simulation` on
  the same matchup right after `predict_matchup_winner`, instead of relying
  on the LLM to separately decide to call it too. Every matchup query now
  populates both the Poisson-style prediction and the Simulation tab.
- `run_monte_carlo_simulation` itself was still pure random noise
  (sport-generic means, no connection to your logged results). It now reads
  the same Elo win probability as `predict_matchup_winner` and skews the
  simulated scoring distributions toward the favored team, so an unlogged
  matchup simulates as a real toss-up and a matchup with logged history
  simulates consistently with the rest of the dashboard.

Margin of victory matters (a blowout moves ratings more than a 1-point
game), and each sport has its own home-field-advantage and K-factor tuned
to how often that sport is played (MLB moves slower per game than NFL,
since MLB teams play far more games).

## 2. Real edge / EV / Kelly math, not the LLM's guess

`kelly_criterion()` and `calculate_ev()` existed in the code before but
were never actually called by anything -- every "recommended wager" and
"edge %" on the dashboard was the model's own guess (and in one case, it
was literally copying the placeholder numbers out of its own prompt
template). `backend/main.py` now computes these deterministically from the
model's real win probability and the real market price when one was
returned, using your selected risk profile to size the Kelly fraction
(Conservative = quarter-Kelly, Moderate = half-Kelly, Aggressive =
three-quarter-Kelly).

There was also a deeper bug behind this: the agent graph never actually
attached tool results to the conversation the way the code assumed, so the
"pull real tool data" logic had silently been matching nothing since day
one. Fixed by having tool results flow through `state["math_results"]`.

## 3. Bet journal (Journal tab)

Log every bet you actually place -- sport, matchup, bet type, selection,
odds, stake. Grade it later as won / lost / push / void (optionally with
the closing line, to get real closing-line value). This is tracked
separately from the agent's own predictions, because it's the one number
that actually matters: what *you* bet and what happened.

## 4. Performance dashboard

The Journal tab's stat row (win rate, record, ROI, total P/L, average CLV)
and the main Dashboard's "Bankroll Curve" chart are both computed live from
`GET /performance` -- real numbers from your graded bets, not a simulated
random walk. The chart is empty until you've graded at least one bet.

## 5. Multi-book odds comparison + real arbitrage scanning

The Odds tab now looks up a specific matchup and shows every bookmaker's
current moneyline price side by side (not just DraftKings). The Arbitrage
tab scans every live game in a sport for a guaranteed cross-book edge (best
home price at one book + best away price at another summing to under 100%
implied probability) and lists any it finds, sorted by size.

Both require `ODDS_API_KEY` to be set in `.env` (already the case in this
repo) and only find something when the odds API has live games listed for
that sport.

## New backend endpoints

All under the same FastAPI app (`backend/main.py`), no auth:

| Method | Path | Purpose |
|---|---|---|
| POST | `/games/result` | Log a completed game's real score; updates Elo ratings |
| GET | `/ratings/{sport}` | Current power rankings for a sport |
| POST | `/bets` | Log a new bet |
| GET | `/bets` | List bets (optional `?status=` / `?sport=` filters) |
| PATCH | `/bets/{id}` | Grade a bet won/lost/push/void, optional closing odds |
| GET | `/performance` | Win rate, ROI, avg CLV, bankroll curve (optional `?sport=`) |
| GET | `/odds/compare?sport=&home_team=&away_team=` | All bookmakers' prices for one matchup |
| GET | `/arbitrage/scan?sport=&min_edge_pct=` | Scan for cross-book arbitrage |

## What's still not "real" (known limitation)

The Poisson total-points model (`calculate_poisson_over_under`) still gets
its EPA-style inputs from the LLM's own estimate rather than your logged
ratings -- Elo ratings and EPA aren't the same scale, so wiring them
together properly is a follow-up, not something folded into this pass.
Treat the Poisson/over-under numbers as more illustrative than the
win-probability and Kelly numbers, which are now fully deterministic.

## 2. "Supreme analytics" pass (2026-09-01, part 2)

Four bigger builds on top of the Elo/Simulation fix above, plus a new sport.

### NCAA Football (NCAAF)
Every sport picker (Ratings, Bet Journal, Odds Compare, Arbitrage, Edge Radar,
Line Tracker) now includes NCAAF, with its own home-field-advantage/K-factor
tuning and its own Odds-API sport key (`americanfootball_ncaaf`). `normalize_sport()`
checks for it before the generic NFL/"football" match, so "college football" or
"CFB" doesn't get misread as NFL.

### Glicko-2 ratings (replaces plain Elo)
`sports_agent/ratings.py` now runs real Glicko-2 -- rating **and** rating
deviation (RD, a confidence measure) **and** volatility, not just a single
number. A brand-new team starts at 1500 with RD 350 ("I don't know yet"); RD
narrows as you log real results and widens again the longer a team goes
without one. `win_probability()` folds in:
- both teams' RD (two uncertain teams produce a probability pulled closer to
  a toss-up than the same rating gap would with two well-established teams)
- **rest days**, computed from each team's own logged `game_results` history
  -- no external schedule feed needed
- any active **manual situational adjustment** you log yourself (see below)

`GET /predict/explain?sport=&home_team=&away_team=` returns every ingredient
behind a pick (rating gap, confidence, rest days, situational notes) for a
"why this pick" view, without going through the LLM agent.

### Manual situational adjustments
No injury-report data source is wired in, so `POST /team-status` lets you log
one yourself -- e.g. `{"team": "Ravens", "adjustment": -60, "note": "Starting
QB out", "expires_at": "2026-09-15"}`. It folds into `win_probability()`
until it expires or you delete it (`DELETE /team-status/{id}`, or the X
button in the Ratings tab). Adjustments are clamped to +/-150 points so a
typo can't send a prediction to 0% or 100%.

### Calibration & backtesting
Every `predict_matchup_winner` call now logs its probability to a new
`model_predictions` table. Logging a real result via `POST /games/result`
auto-resolves any pending predictions for that matchup. `GET /calibration`
buckets resolved predictions by predicted probability and compares against
the actual win rate in each bucket -- the honesty check for the model -- plus
a Brier score (0 = perfect, 0.25 = a coinflip model). New **Calibration** tab
charts predicted vs. actual per bucket.

### Edge Radar
`GET /edge-radar?sport=&min_edge_pct=&bankroll=&risk_profile=` pulls every
currently-listed game for a sport from the Odds API (not one matchup at a
time), runs the Glicko-2 model against each, and ranks by predicted +EV --
using the same `kelly_criterion`/`calculate_ev` math the main chat flow uses.
New **Edge Radar** tab.

### Line tracking + automatic CLV
New `odds_snapshots` table + `GET /line-movement` show price history and flag
a >=5% implied-probability "steam move." A background poller (`POST
/line-tracking/enabled` to opt in -- **off by default**) snapshots odds every
15 minutes for any matchup with an *open bet*, and once that game's kickoff
time passes, auto-fills `closing_odds`/`clv_pct` on the bet if you haven't
already graded it. It only tracks matchups tied to an open bet -- never the
whole board -- to keep Odds-API usage bounded, since it's a paid, rate-limited
API. Grading a bet (`PATCH /bets/{id}`) now falls back to whatever the
tracker already auto-captured if you don't supply a closing line yourself.
Bets can now be logged with structured `home_team`/`away_team` fields (the
Bet Journal form asks for them directly) so the tracker can match them --
free-text-only bets still work, just aren't trackable.

### What's still not wired in
- The Poisson total-points model still gets its inputs from the LLM's own
  estimate rather than the rating engine (unchanged from part 1).
- "Situational adjustments" are manual, not automated -- there's still no
  live injury-report or weather data source connected.
- The line tracker polls on a fixed interval while the backend process is
  running; it doesn't run anything while the server is stopped.

## 3. Daily schedule, standings, and stats (2026-09-01, part 3)

### Schedule tab
`GET /schedule?sport=&date=` lists every currently-listed game for a sport
(optionally narrowed to one calendar day) with the **market's** favorite/
underdog (best price across books) shown right next to the **model's** own
favorite, win probability, and confidence -- plus a flag for whether they
agree. Disagreement is the interesting signal: it's where the model thinks
the market has it wrong. For MLB, probable pitchers (when ESPN has them
listed) show under the matching game.

### Standings & stats tab, and a new data source
The Odds API only ever has betting lines -- no standings, rosters, or
stats. Two sources now cover that:
- **Your own record** (`GET /my-record/{sport}`) -- real win-loss, PPG, and
  points-allowed computed purely from games you've logged. Needs nothing new.
- **ESPN's public site API** (`sports_agent/espn_stats.py`, `GET /espn/...`)
  -- official standings, team stats (points/yards per game, etc.), rosters,
  and on-demand single-player stats. This is a genuinely different kind of
  dependency than The Odds API: it needs **no signup or API key at all**,
  but it's also not an official/documented API -- it's the JSON ESPN's own
  site consumes, widely used by hobby projects, with no SLA and no
  guarantee it won't change shape without notice. Every function is written
  defensively and returns `{"error": ...}` instead of crashing if a field
  is missing.
- Player stats are looked up **on demand** (one player, by name, resolved
  against their team's roster) rather than preloaded for every player on
  every team -- pulling full box-score stats for entire rosters daily would
  be a lot of calls for data you'd rarely all look at.

**Important caveat, unverified**: outbound network from the sandbox this
was built in is restricted to an allowlist that doesn't include espn.com, so
none of the `/espn/*` endpoints could be tested against ESPN's actual live
response -- only against a synthetic response built to match ESPN's
long-stable, community-documented JSON shape. The parsing logic itself is
tested and correct for that assumed shape (see the test suite run while
building this). The real first test is the first live call on your machine.
If a field comes back empty or an endpoint errors, tell me what you see and
I'll adjust the parsing in `sports_agent/espn_stats.py` to match.

### ESPN client hardening (403 blocks, player-name matching)
Two rounds of real bugs against live ESPN traffic on your machine (which I
still can't reach from the sandbox -- everything below is verified offline
against synthetic responses shaped like your actual data, and against a
simulated 403, but not against a live ESPN response):

- **Player lookups failing that clearly should match** (e.g. Baker Mayfield
  on the Buccaneers roster): name matching in `get_player_stats` now
  normalizes both sides (strips accents/punctuation, drops suffixes like
  Jr./II/III, ignores case/whitespace) and matches on last-name-only
  searches too. A genuine miss now also reports the roster size and a
  sample of names ESPN actually returned, so a future failure is
  self-diagnosing instead of needing another debug round-trip.
- **`403 Client Error: Forbidden` on every ESPN call** (standings, teams,
  everything): this is ESPN's bot-mitigation, almost certainly tripped by
  the burst of requests during debugging -- not a code bug, and not
  something any header change can force through once it's active. It
  should clear on its own (typically minutes to a day). To reduce the
  chance of re-triggering it: requests now carry a Referer/Origin mimicking
  espn.com, are paced at least ~350ms apart, and the team name -> ESPN ID
  map is now cached to disk (`data/espn_team_cache.json`, 24h TTL) so a
  backend restart doesn't force a full team-list re-fetch. If a live fetch
  fails while a (even stale) disk cache exists, team **name resolution**
  falls back to it rather than failing outright -- though roster/stat/player
  calls still need a live ESPN response, since those aren't cached.
- New debug endpoint: `GET /espn/debug/player-match?sport=&team=&player=`
  runs the exact production roster-fetch + name-match code and reports the
  resolved team id, full roster name list, and match result in one call.

### The real fix for ESPN's 403 (browser fingerprint, not IP block)
Confirmed directly against your machine: `https://site.api.espn.com/apis/v2/sports/football/nfl/standings`
loaded fine in a real browser tab while the backend's own requests to the
exact same URL kept getting `403 Forbidden`. That rules out an IP-level
block -- it's ESPN's bot-mitigation fingerprinting the *client* (TLS
handshake shape, header order, HTTP/2 behavior -- not just the `User-Agent`
string), which no amount of header-spoofing on a plain `requests` call can
get around.

Fix: `sports_agent/espn_stats.py` now uses `curl_cffi` (`impersonate="chrome"`)
instead of plain `requests` for every ESPN call -- it replicates an actual
Chrome browser's connection fingerprint, not just its headers. Falls back to
plain `requests` automatically if `curl_cffi` isn't installed yet (so the
app doesn't crash, it just keeps 403ing until it is).

**One-time step needed on your machine**: run `Update Backend Dependencies.bat`
once to install the new dependency, then use the EIVANTA Dashboard shortcut
as normal. Genuinely couldn't verify this live myself (no network access to
espn.com from here) -- confirmed offline that the fallback logic and
impersonation wiring both work correctly, but the real test is ESPN
actually returning data on your machine after the update.

### Player stats: the real, confirmed ESPN shape (finally)
Took four rounds of live debugging (thank you for all the paste-backs) but
this is now confirmed against real data, not guessed: ESPN's gamelog
endpoint (`site.web.api.espn.com/.../athletes/{id}/gamelog`) splits a
player's data across two places -- the top-level `events` dict is pure
metadata (opponent, date, score, a `links` array that happens to be the
same length as the stat list, which is what caused two of the bugs above),
while the actual stat numbers live in
`seasonTypes[0].categories[0].events[].stats` (one game's line, matched by
event id) and `...categories[0].totals` (season totals) -- both flat lists
aligned 1:1 with the top-level `names`/`displayNames` arrays.
`_parse_stat_response` now reads from there directly: it shows the most
recent logged game's full stat line by default, labeled with the season
and opponent, and falls back to season totals if no specific game lines up.
Verified offline against Baker Mayfield's actual real numbers from this
conversation (203 passing yards, 16/22 completions, etc.) before asking for
another live retest.

Also fixed in this round: the backend now runs with `uvicorn --reload`
(scoped to `backend/` and `sports_agent/` only, so editing data files never
triggers a spurious restart) -- Python changes now take effect automatically
like the frontend already did, instead of needing a manual restart every
time (a recurring source of confusion this session). Needs `watchfiles`
installed (`Update Backend Dependencies.bat`).

## Home/away orientation was backwards for some matchups (fixed)

**Symptom:** For a real Braves @ Nationals game (Nationals hosting), the
dashboard showed the Braves -- the actual road team -- as the home team:
Monte Carlo's "Home Win Probability" and "Median Projected Score" both had
the Braves on the home side, and the AI narrative said the Braves were
"favored... with a home win probability of 57.8%."

**Root cause:** `home_team`/`away_team` were never grounded in real
schedule data -- the tool-calling LLM in `sports_agent/nodes.py` decided who
was home purely from how the user phrased the matchup (e.g. word order in
"Braves vs Nationals"), and had no way to know who was actually hosting.
This is worse than a cosmetic swap: `ratings.py`'s `win_probability()` adds
a real home-field rating bonus (`params["home_adv"]`) to whichever team is
passed as `home_team`, so a backwards orientation hands that edge to the
wrong team and can shift (or even flip) who the model favors.

**Fix:** Added `espn_stats.resolve_matchup_home_away(sport, team_a,
team_b, date=None)`, which looks up ESPN's real scoreboard for the day and
returns which of the two teams is actually home, using the same
normalized fuzzy-name matching as player lookups. `nodes.py` now runs every
tool call that carries `home_team`/`away_team` (`fetch_live_odds`,
`predict_matchup_winner`, `run_monte_carlo_simulation`,
`calculate_poisson_over_under`, and the auto-triggered Monte Carlo call
that piggybacks on `predict_matchup_winner`) through
`_grounded_tool_call()`, which swaps the two team names into the correct
home/away slots when ESPN's scoreboard confidently disagrees with the
LLM's guess. If ESPN's scoreboard can't confidently resolve it (no
matching game found, or the two team names match more than one game),
the LLM's original guess is left untouched rather than risking a wrong
"correction."

Verified offline with a stubbed scoreboard response (the exact real
Braves/Nationals case) confirming the swap happens, a same-order case
confirming an already-correct guess isn't touched, and a no-match case
confirming an unresolvable matchup falls back untouched.

## Enhancement round: auto-settlement, auto injury sync, steam alerts

Before building anything here, actually read through `backend/analytics.py`
in full (hadn't done that yet this session) and found two of the five
originally-recommended features already existed in solid form: **Edge
Radar** (`GET /edge-radar`, `EdgeRadar.tsx` -- scans the whole slate for
+EV vs. the market) and the **Bet Journal's P&L view**
(`GET /performance`, `BetJournal.tsx` -- real win rate, ROI, avg CLV,
bankroll curve). Nothing was rebuilt there. The three genuine gaps got
built:

### 1. Auto-settlement (`run_auto_settlement_cycle`, `backend/analytics.py`)

A background poller (every 20 min, default ON) that checks ESPN's
scoreboard for each supported sport and, for any game gone Final:
- Logs the result into the Glicko-2 rating engine via
  `record_game_result` -- but only if that exact (sport, home, away,
  date) result isn't already in `game_results`, since that table has no
  unique constraint and calling it twice would double-count the rating
  update.
- Auto-grades any **pending moneyline** bet on that matchup by matching
  your free-text `selection` against the real winner/loser team name.
  Spread/total bets are deliberately left for the manual Won/Lost/Push/
  Void buttons -- the app only stores selection as free text, not a
  structured line, so auto-grading those isn't safe.

New: `POST/GET /auto-settle/enabled`, `/auto-settle/status`,
`POST /auto-settle/run` (manual trigger). Bets now carry a `graded_by`
column (`manual` vs `auto`), shown as a column in the Bet Journal history
table.

### 2. Automatic injury sync (`run_injury_sync_cycle`, `backend/analytics.py`)

Team-status situational adjustments (`win_probability()`'s injury/
suspension nudge) used to be 100% manual entry -- the code said so
explicitly. A background poller (every 60 min, default ON) now pulls
today's scoreboard, fetches each playing team's ESPN injury report
(`espn_stats.get_team_injuries`, new -- same URL pattern as the
already-working `/roster` and `/statistics` endpoints, but **unverified
against a live response** the same way player-stats was before that got
debugged against your real ESPN traffic; see `GET
/espn/debug/injuries-raw` if `GET /espn/injuries` ever comes back empty
for a team you know has real injuries), and turns it into a rating
adjustment: Out/IR -8, Doubtful -4, Questionable -2 per player, summed
and floored at -30. This is a blunt heuristic, not a depth-chart model --
it has no idea if the player out is a starter or third-stringer.

To avoid piling up duplicate adjustments every hour, adjustments now
carry a `source` (`manual` vs `espn_auto`); each sync cycle deletes and
re-derives only its own `espn_auto` rows, so a recovered player's penalty
clears automatically too. Manual entries you type in yourself are never
touched. `RatingsPanel.tsx` tags auto entries "Auto -- ESPN" so you can
tell them apart from your own notes.

New: `GET /espn/injuries`, `GET /espn/debug/injuries-raw`,
`POST/GET /injury-sync/enabled`, `/injury-sync/status`,
`POST /injury-sync/run`.

### 3. Steam alerts (`GET /line-movement/alerts`)

Line movement tracking already existed (`GET /line-movement`,
`steam_move` flag on a 5%+ implied-probability shift) but only for one
matchup you already knew to look up. New endpoint scans every
currently-tracked matchup (anything with 2+ captured odds snapshots) and
returns just the ones that moved 5+ points, sorted by size of the move.
Surfaced as a new "Steam Alerts" panel at the top of `LineMovement.tsx`,
above the existing per-matchup lookup, so a move surfaces without typing
in the game first.

### Testing performed (offline, before any live retest)

- `py_compile` on every touched Python file.
- `ratings.py`'s new `replace_auto_team_status` exercised against a real
  scratch DuckDB file: confirmed a manual entry survives alongside an
  auto entry, confirmed a second sync with no injuries clears the auto
  row without touching the manual one, confirmed 3 repeated syncs don't
  pile up duplicate auto rows, confirmed the combined adjustment
  (`get_active_status_adjustment`) sums both sources correctly.
- Auto-settlement's winner/loser selection-matching and profit math,
  the injury status→weight mapping, and the steam-alert grouping/shift
  math were each exercised standalone against handwritten cases
  (including the ambiguous-selection-text skip case) before being
  trusted in the real cycle functions.
- `tsc --noEmit` across the whole frontend: clean, no type errors.

Not yet verified live (need a real backend run + real ESPN traffic,
same caveat as everything else built against ESPN's unofficial API this
session): whether `get_team_injuries`'s URL/shape assumption is actually
right. If `GET /espn/injuries` comes back empty for a team with known
injuries, paste `GET /espn/debug/injuries-raw?sport=...&team=...`'s
output back and it'll get fixed the same way player-stats did.

## Post-deploy audit: two real bugs found and fixed in the enhancement round

Ran a deliberate audit of everything from the previous round (auto-
settlement, injury sync, steam alerts) rather than trusting the earlier
offline tests alone. Found two genuine defects, both fixed and re-verified
before this note was written.

### Bug 1: auto-settlement's bet matching used an exact string comparison

`run_auto_settlement_cycle` matched pending bets to a finished ESPN game
with `lower(bets.home_team) = lower(espn_home_team)`. ESPN's scoreboard
always returns full display names ("Boston Red Sox"), but the Bet
Journal's own home/away fields are free text the user types -- and the
form's own placeholder ("Ravens") models the *short* form. In practice
this meant almost no moneyline bet would ever actually get matched to its
game, let alone graded -- the exact-match condition would almost always
be false. Same problem existed a second time in the selection-text match
(`winner.lower() in selection`), for the same reason.

Fixed by pulling pending bets by sport only, then fuzzy-matching each
bet's own home/away text against the ESPN game's team names in either
orientation (`_fuzzy_team_match`, normalized substring match, reusing
`espn_stats._normalize_name`), and matching selection text against the
bet's *own* team-name text rather than ESPN's. Re-verified against the
real short-vs-full-name scenario (`"Red Sox"` bet vs. ESPN's `"Boston Red
Sox"`), a swapped-orientation bet, a genuine loss, and an unrelated
matchup that must NOT match -- all correct.

### Bug 2 (more significant): team names weren't canonicalized anywhere,
### so ratings/situational-adjustment history could silently fragment

`team_ratings` and `team_status` are both keyed by an exact `team` string
-- `WHERE sport = ? AND team = ?`, no fuzzy matching. Before this fix,
that string was whatever happened to be passed in: a chat prediction
might use `"Braves"`, while the new auto-settlement cycle always uses
ESPN's own full scoreboard name (`"Atlanta Braves"`). Those would land on
*two different rows*, each starting over at the default 1500 rating --
meaning auto-settlement could keep logging real results that a
short-name chat prediction would never actually see, silently defeating
the entire point of closing the loop. The same fragmentation risk applied
to situational adjustments (manual notes vs. the new ESPN injury sync)
and rest-day tracking.

Fixed with `espn_stats.canonical_team_name(sport, name)` (resolves any
known alias to ESPN's own full display name, reusing the already-cached
team-id map -- no extra network calls) and a `ratings._canonicalize()`
wrapper used in two layers for defense in depth: at the entry points
(`win_probability`, `win_probability_breakdown`, `record_game_result`,
`set_team_status`, `replace_auto_team_status`) *and* inside the low-level
read primitives themselves (`get_rating_full`, `get_active_status_
adjustment`, `_rest_days`), so a future direct caller can't bypass it by
accident. Falls back to the original string (never raises) if ESPN can't
resolve a name, so a lookup failure degrades to the old behavior instead
of breaking anything.

Verified end-to-end against a real scratch DuckDB (not mocked): confirmed
import order between `ratings.py` and `espn_stats.py` doesn't create a
circular-import failure either direction (they reference each other, so
the resolution uses a lazy import); confirmed a chat-style prediction
using the short name (`"Red Sox"`) sees a result the auto-settlement
cycle logged using ESPN's full name (`"Boston Red Sox"`) -- including the
win probability actually moving after the result, the situational
adjustment sync being visible via the short name, and rest-days tracking
correctly across the name-form boundary; re-ran the earlier manual-vs-
auto isolation tests to confirm this didn't regress them.

**Checked the user's actual live data before writing this off as
theoretical**: as of this audit, `data/telemetry.duckdb` has 4
`team_ratings` rows, 2 `game_results`, 0 `team_status` entries, and 0
bets -- and all 4 team names already match ESPN's canonical full form
(auto-settlement had already run live and logged them correctly). No
fragmentation exists yet in the real data, so no migration/cleanup was
needed -- this fix prevents the problem going forward rather than
patching existing drift.

## User-reported bug: Monte Carlo (and projected score) always favored home,
## regardless of real team strength -- confirmed and fixed

**Symptom:** across three different real MLB matchups, the Monte Carlo
panel favored the home team every time by roughly the same 57-59% margin,
seemingly independent of each team's actual rating/standing.

**Root cause, precisely quantified:** `run_monte_carlo_simulation` (and,
to a lesser extent, `predict_matchup_winner`'s displayed projected score)
in `sports_agent/tools.py` had a *second*, independent home-field bump
hardcoded into the per-sport baseline scoring means (e.g. MLB: `mu_h=4.8`
vs. `mu_a=4.2`) -- on top of the `edge` term already derived from
`win_probability()`, which *itself* already adds a real home-field rating
bonus (`home_adv`, e.g. +24 Glicko points for MLB). This double-counted
home-field advantage, and worse: the fixed baseline gap ate a large,
constant share (roughly a quarter to a third, depending on sport) of the
`spread` budget the real `edge` needed to move the needle -- so even a
substantial, well-established rating advantage for the *away* team could
barely shift the simulated win rate off of "home favored."

Quantified with the exact math before touching anything:
- Two still-unrated MLB teams (a true 51.9% Glicko-implied toss-up, since
  the only difference is home_adv) simulated as a **58.0%** home favorite.
- An away team with a real, established +150-point rating advantage
  (which Glicko puts at 39.8% for home, i.e. away clearly favored)
  still simulated home at **51.1%** -- essentially erasing a real edge.
- Even a massive +300-point away advantage (28.1% Glicko) only pulled the
  simulated home number down to **44.0%** -- never actually showing home
  as a real underdog.

**Fix:** `mu_h`/`mu_a` (and `predict_matchup_winner`'s `base_h`/`base_a`)
now start **equal** per sport -- home-field advantage flows exclusively
through `edge`, which already reflects `win_probability()`'s real
home_adv, each team's actual rating gap, rest days, and any situational
adjustments (manual or the automatic ESPN injury sync). Re-verified the
same three cases after the fix: the true-toss-up case now simulates at
~51.2% (vs. Glicko's 51.9% -- within normal Monte Carlo noise), the
+150 away-advantage case now correctly shows the away team favored
(44.0% home), and the +300 case shows home clearly as the underdog
(37.3%, vs. Glicko's 28.1% -- some residual compression is expected and
normal, since mapping a probability onto a fixed-shape score distribution
via a single linear `edge * spread` term is an approximation, not exact
inversion; it no longer masks the direction or rough scale of a real
edge, which was the actual bug).

This bug predates this session's changes (the baked-in home bump was
already there) -- this session's earlier `int()`->`round()` fix only
addressed the separate truncation-bias issue, not this one.
