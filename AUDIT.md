# Sports Betting App — Bug & Architecture Audit
_Generated 2026-08-25_

## TL;DR

The biggest problem isn't any single bug — it's that the project has **three parallel frontends** (`frontend/` Next.js app, `ui.py`/`app_ui.py` Streamlit apps, `index.html`/`app.js`/`styles.css` static site) and **three parallel backends** (`app.py`, `sports_agent/app.py`, `backend/main.py`) that all listen on `localhost:8000` and implement `/chat/sports` differently. Only one backend can run at a time, and which one you happen to start determines whether the app works at all, streams correctly, or silently ignores your question. Consolidating down to one frontend + one backend will fix most of the "why doesn't this work" confusion before you even touch individual bugs.

---

## Critical

**1. Three different `/chat/sports` backends, mutually incompatible with the frontend contract**
- `app.py` (root): LangGraph agent, streams one SSE event `data: {...}\n\ndata: [DONE]\n\n`. Request shape `{message, thread_id, bankroll, risk_profile}`. This is the one whose request/response shape actually matches what `frontend/src/page.tsx` sends and parses.
- `sports_agent/app.py`: same LangGraph agent, but returns a **plain JSON body** (`response_model=ChatResponse`), not SSE, and only accepts `{message, thread_id}` (`schemas.ChatRequest` has no `bankroll`/`risk_profile` fields — they're silently dropped by pydantic). If you run *this* file as the backend, the frontend's `response.body.getReader()` SSE parser gets no `data:` lines, `accumulatedContent` stays empty, and every request shows "The agent returned no result."
- `backend/main.py`: SSE-shaped like `app.py` (compatible framing), but `req.message`/`req.thread_id` are **never read** — `get_sports_prediction` always evaluates a hardcoded mock Bucs @ Chiefs game (`mock_game` literal in the function body). Every query, regardless of teams or intent, returns the identical response.
- Fix: pick one backend (root `app.py` looks like the intended one — it's the only one whose contract matches the live frontend), delete or clearly archive the other two, and update ports/imports accordingly.

**2. `backend/main.py` has no run entrypoint**
- No `if __name__ == "__main__":` / `uvicorn.run(...)` block, unlike `app.py` and `sports_agent/app.py`. `python backend/main.py` does nothing; it has to be run with an explicit `uvicorn backend.main:app` command that isn't documented anywhere.

**3. Stale `.git/index.lock`**
- `.git/index.lock` exists in the repo root. Any `git add`/`git commit` will currently fail with `fatal: Unable to create '.git/index.lock': File exists.` unless a git process is genuinely mid-operation. Delete it (`rm .git/index.lock`) if no git command is actively running.

---

## High

**4. Dependencies are attached to the wrong backend**
- `backend/requirements.txt` lists `langchain-core`, `langchain-openai`, `langgraph` — none of which `backend/main.py` imports (it only needs `fastapi`, `uvicorn`, `pydantic`, `pandas`, `numpy`, `scipy`, `statsmodels`).
- Meanwhile `app.py` + `sports_agent/` (which *do* need langchain/langgraph/python-dotenv) have **no requirements.txt of their own** anywhere in the repo root. Reproducing the environment for the backend that's actually meant to run is currently undocumented.

**5. Injected system-context text corrupts intent classification**
- `app.py` prepends `"[System Context - Active Bankroll: ${bankroll}, Risk Profile: {risk_profile}]\nUser Prompt: {message}"` to every message before it reaches the agent.
- `classify_sports_intent_node` (`sports_agent/nodes.py`) does plain substring keyword matching, and `"bankroll"` is literally inside `"Active Bankroll"`. So **any query that doesn't happen to also contain an `odds_ev`/`data_science`/`data_analyst` keyword gets misrouted to the bankroll node** instead of falling through to the LLM classifier fallback that was clearly meant to catch exactly those ambiguous cases. E.g. "How does home field advantage affect scoring?" would get routed to `bankroll_node`.
- Fix: don't fold the bankroll/risk-profile context into the same string the keyword classifier reads, or match on word boundaries / classify on the raw user message before contextualizing.

**6. Duplicate, drifted `QuantWidgets.tsx`**
- `frontend/components/QuantWidgets.tsx` (top-level, outside `src/`) is an older, shorter copy (only `PoissonWidget`/`MonteCarloWidget`) with no `NBAWidget`/`MLBWidget`.
- `frontend/src/components/QuantWidgets.tsx` is the real one imported everywhere via the `@/components/*` alias (`tsconfig.json` maps `@/*` → `./src/*`).
- The top-level copy is dead code, but it's tracked and shows as "modified" in `git status`, so it's an easy trap to edit the wrong file and wonder why nothing changes. Delete `frontend/components/`.

**7. Kelly stake sizing uses a hardcoded market price**
- `all_models_node` (`sports_agent/nodes.py`) always calls `kelly_criterion(win_probability, -110, fraction=0.5)` — the `-110` American odds is a hardcoded stub, disconnected from whatever odds `fetch_mock_live_odds`/`predict_matchup_winner` actually returned in the same call. The recommended stake size will be wrong whenever real odds diverge from -110.

---

## Medium

**8. `extractQuantitativeJson`'s primary regex can't handle nested JSON**
- In `frontend/src/page.tsx`, the fenced-code-block regex `` /`{2,3}\s*(?:json)?\s*(\{[\s\S]*?\})\s*`{2,3}/i `` is non-greedy, so it captures up to the *first* `}` it finds — which truncates any nested object (and every payload from `all_models_node`, `backend/main.py`, etc. is nested: `{"prediction": {...}, "poisson": {...}}`). `JSON.parse` on that slice throws, and the code silently falls through to the brace-depth-counting fallback parser below it, which does work correctly. It functions today only because of the fallback — worth simplifying/removing the first regex attempt since it never actually succeeds on real payloads, rather than leaving a dead code path that looks load-bearing.

**9. `american_to_decimal` divides by zero on `american_odds == 0`**
- `sports_agent/nodes.py`: `100 / abs(american_odds)` when `american_odds` is `0` raises `ZeroDivisionError`. Odds of `0` are invalid anyway, but there's no validation catching it before it reaches this function (or in the pydantic models).

**10. Unexpected second line in `.env`**
- `.env` has `OPENAI_API_KEY=...` plus a second entry `Sports_Betting_App=...`. That doesn't match any `os.getenv(...)` call in the codebase — worth double-checking this wasn't an accidental paste, and not something you meant to reference from `config.py`.

**11. `sports_agent/app.py`'s fallback `intent` value is dead**
- `intent = result.get("intent", "concept_explanation")` — but the classifier can only ever set `intent` to one of `all_models/data_science/data_analyst/odds_ev/bankroll/quant_code/tutor`. `"concept_explanation"` never actually occurs and isn't handled anywhere downstream; harmless today but misleading if you're debugging routing.

---

## Low / cleanup

**12. Legacy prototype UIs left in the repo root**
- `ui.py`, `app_ui.py` (Streamlit) and `index.html`/`app.js`/`styles.css` (static JS) are all earlier UI attempts that also point at `http://localhost:8000/chat/sports`, now superseded by `frontend/`. They still work as standalone artifacts but add to the "which one is real" confusion. Consider moving them to an `/archive` folder or deleting once you're sure you don't need them for reference.

**13. `ui.py.save`**
- Backup file with a real bug frozen in it (`unsafe_allow_stdio=True` instead of the valid Streamlit kwarg `unsafe_allow_html=True`, which would raise a `TypeError` if ever run). Not currently used by anything — safe to delete.

**14. Two Python virtualenvs (`venv/` and `.venv/`)**
- Not a correctness bug (`.venv/` self-ignores via its own nested `.gitignore`), but having both invites installing packages into the wrong one and being confused about why imports fail. Worth standardizing on one.

**15. `frontend/src/page.tsx` lives outside `src/app/`**
- Not a bug — `frontend/src/app/page.tsx` intentionally re-exports it (`export { default } from "../page"`) to route around the top-level/`src` duplicate-folder issue, and that pattern works fine with Next's App Router. Flagging only so it's clear this is deliberate and not an accident, since it looks unusual at first glance.

---

## Suggested order of attack

1. Delete `.git/index.lock`, decide which backend is canonical (root `app.py` is the natural choice) and delete/archive the other two `/chat/sports` implementations.
2. Move the langchain/langgraph dependencies into a requirements file next to the backend that actually needs them; strip them out of `backend/requirements.txt` if you drop that file.
3. Fix the bankroll-keyword misrouting (finding #5) — it's a quiet correctness bug that will keep misfiring in production.
4. Delete `frontend/components/QuantWidgets.tsx` (the dead duplicate) and `ui.py.save`.
5. Everything else (Kelly hardcoding, zero-odds guard, `.env` stray line) is worth a pass but won't block basic functionality.
