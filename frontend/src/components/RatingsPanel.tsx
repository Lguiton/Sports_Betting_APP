"use client";

import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import { Trophy, X } from "lucide-react";

const backendUrl = () => process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

type Rating = { team: string; rating: number; rd: number; confidence: "High" | "Medium" | "Low"; games_played: number; last_updated: string };
type TeamStatus = { id: number; team: string; adjustment: number; note: string | null; expires_at: string | null; created_at: string; source?: string };

const EMPTY_FORM = { sport: "NFL", home_team: "", away_team: "", home_score: "", away_score: "" };
const EMPTY_STATUS_FORM = { team: "", adjustment: "", note: "", expires_at: "" };

const confidenceColor: Record<string, string> = {
  High: "text-[#00FF5B]",
  Medium: "text-yellow-400",
  Low: "text-slate-500",
};

export default function RatingsPanel() {
  const [sport, setSport] = useState("NFL");
  const [ratings, setRatings] = useState<Rating[]>([]);
  const [statuses, setStatuses] = useState<TeamStatus[]>([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [statusForm, setStatusForm] = useState(EMPTY_STATUS_FORM);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  const refresh = useCallback(async (s: string) => {
    try {
      const res = await fetch(`${backendUrl()}/ratings/${s}`);
      if (res.ok) setRatings((await res.json()).ratings);
    } catch (err) {
      console.error("Failed to load ratings:", err);
    }
  }, []);

  const refreshStatuses = useCallback(async (s: string) => {
    try {
      const res = await fetch(`${backendUrl()}/team-status/${s}`);
      if (res.ok) setStatuses((await res.json()).statuses);
    } catch (err) {
      console.error("Failed to load team status:", err);
    }
  }, []);

  const runEspnSyncNow = useCallback(async () => {
    setSyncing(true);
    setSyncError(null);
    setSyncResult(null);
    // This endpoint can make a lot of sequential ESPN requests under the
    // hood (auto-settlement across 4 sports x 2 dates, then one injury
    // check per team currently playing, then a standings pull per sport)
    // -- on a normal day it finishes in a few seconds, but a big slate of
    // games (or ESPN being slow to respond) can genuinely take a while.
    // Without a timeout here, a single slow/hanging request would leave
    // the button reading "Syncing..." forever with no feedback -- so this
    // gives up after 90s and reports that clearly instead of looking
    // frozen (the sync may still finish on the backend even after this
    // gives up client-side; re-running it, or just waiting for the next
    // scheduled poll, will reflect the result either way).
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 90_000);
    try {
      const res = await fetch(`${backendUrl()}/espn-sync/run-all`, { method: "POST", signal: controller.signal });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || "ESPN sync failed");
      }
      const data = await res.json();
      const gamesLogged = data.auto_settlement?.games_logged ?? 0;
      const betsGraded = data.auto_settlement?.bets_graded ?? 0;
      const injuryTeams = data.injury_sync?.teams_synced ?? 0;
      const statsTeams = data.stats_sync?.teams_synced ?? 0;
      setSyncResult(
        `Games logged: ${gamesLogged} -- Bets graded: ${betsGraded} -- Injury-synced: ${injuryTeams} teams -- Stats-synced: ${statsTeams} teams`
      );
      refresh(sport);
      refreshStatuses(sport);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setSyncError("Taking longer than 90s -- it may still be finishing in the background (a big slate of games can mean a lot of ESPN calls). Give it a bit, then refresh.");
      } else {
        setSyncError(err instanceof Error ? err.message : "ESPN sync failed");
      }
    } finally {
      clearTimeout(timeoutId);
      setSyncing(false);
    }
  }, [sport, refresh, refreshStatuses]);

  useEffect(() => {
    refresh(sport);
    refreshStatuses(sport);
  }, [sport, refresh, refreshStatuses]);

  async function submitResult(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    if (!form.home_team.trim() || !form.away_team.trim() || form.home_score === "" || form.away_score === "") return;
    try {
      const res = await fetch(`${backendUrl()}/games/result`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sport: form.sport,
          home_team: form.home_team,
          away_team: form.away_team,
          home_score: parseFloat(form.home_score),
          away_score: parseFloat(form.away_score),
        }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || "Failed to log result");
      }
      setMessage(`Ratings updated for ${form.home_team} & ${form.away_team}.`);
      setForm({ ...EMPTY_FORM, sport: form.sport });
      if (form.sport === sport) refresh(sport);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to log result");
    }
  }

  async function submitStatus(e: React.FormEvent) {
    e.preventDefault();
    setStatusError(null);
    if (!statusForm.team.trim() || statusForm.adjustment === "") return;
    try {
      const res = await fetch(`${backendUrl()}/team-status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sport,
          team: statusForm.team,
          adjustment: parseFloat(statusForm.adjustment),
          note: statusForm.note || undefined,
          expires_at: statusForm.expires_at || undefined,
        }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || "Failed to save situational note");
      }
      setStatusForm(EMPTY_STATUS_FORM);
      refreshStatuses(sport);
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : "Failed to save situational note");
    }
  }

  async function removeStatus(id: number) {
    try {
      await fetch(`${backendUrl()}/team-status/${id}`, { method: "DELETE" });
      refreshStatuses(sport);
    } catch (err) {
      console.error(err);
    }
  }

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="grid grid-cols-1 xl:grid-cols-3 gap-6">
      <div className="xl:col-span-1 flex flex-col gap-6">
        <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 h-fit">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Log a Completed Game</h3>
          <p className="text-[11px] text-slate-600 mb-4">
            Every result you log here nudges both teams&apos; power ratings (Glicko-2: rating + confidence), which
            is what predict_matchup_winner actually reads from now instead of guessing.
          </p>
          <form onSubmit={submitResult} className="flex flex-col gap-3">
            <select
              value={form.sport}
              onChange={(e) => setForm({ ...form, sport: e.target.value })}
              className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white"
            >
              <option value="NFL">NFL</option>
              <option value="NBA">NBA</option>
              <option value="MLB">MLB</option>
              <option value="NCAAF">NCAAF</option>
            </select>
            <div className="grid grid-cols-2 gap-2">
              <input
                value={form.home_team}
                onChange={(e) => setForm({ ...form, home_team: e.target.value })}
                placeholder="Home team"
                className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white"
              />
              <input
                value={form.home_score}
                onChange={(e) => setForm({ ...form, home_score: e.target.value })}
                placeholder="Home score"
                type="number"
                className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white"
              />
              <input
                value={form.away_team}
                onChange={(e) => setForm({ ...form, away_team: e.target.value })}
                placeholder="Away team"
                className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white"
              />
              <input
                value={form.away_score}
                onChange={(e) => setForm({ ...form, away_score: e.target.value })}
                placeholder="Away score"
                type="number"
                className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white"
              />
            </div>
            <button
              type="submit"
              className="bg-[#00FF5B] text-[#06080A] font-bold text-xs uppercase rounded-lg px-3 py-2 hover:opacity-90 transition-opacity"
            >
              Update Ratings
            </button>
            {message && <div className="text-[#00FF5B] text-[11px]">{message}</div>}
            {error && <div className="text-red-400 text-[11px]">{error}</div>}
          </form>
        </div>

        <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 h-fit">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-2">Situational Adjustment</h3>
          <p className="text-[11px] text-slate-600 mb-4">
            No injury-report feed is wired in, so this is how you tell the model something it can&apos;t see itself --
            e.g. &quot;starting QB out: -60&quot;. Applies to {sport} until it expires (or you remove it).
          </p>
          <form onSubmit={submitStatus} className="flex flex-col gap-2">
            <input
              value={statusForm.team}
              onChange={(e) => setStatusForm({ ...statusForm, team: e.target.value })}
              placeholder="Team"
              className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white"
            />
            <input
              value={statusForm.adjustment}
              onChange={(e) => setStatusForm({ ...statusForm, adjustment: e.target.value })}
              placeholder="Adjustment (e.g. -60)"
              type="number"
              className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white"
            />
            <input
              value={statusForm.note}
              onChange={(e) => setStatusForm({ ...statusForm, note: e.target.value })}
              placeholder="Note (e.g. Starting QB out)"
              className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white"
            />
            <input
              value={statusForm.expires_at}
              onChange={(e) => setStatusForm({ ...statusForm, expires_at: e.target.value })}
              placeholder="Expires (YYYY-MM-DD, optional)"
              className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white"
            />
            <button
              type="submit"
              className="bg-[#06080A] border border-[#00FF5B] text-[#00FF5B] font-bold text-xs uppercase rounded-lg px-3 py-2 hover:bg-[#00FF5B]/10 transition-colors"
            >
              Add Adjustment
            </button>
            {statusError && <div className="text-red-400 text-[11px]">{statusError}</div>}
          </form>

          {statuses.length > 0 && (
            <div className="flex flex-col gap-2 mt-4">
              {statuses.map((s) => (
                <div key={s.id} className="flex items-center justify-between text-[11px] border-t border-[#1C212B] pt-2">
                  <div className="text-slate-300">
                    <span className="text-white font-semibold">{s.team}</span>{" "}
                    <span className={s.adjustment < 0 ? "text-red-400" : "text-[#00FF5B]"}>
                      {s.adjustment > 0 ? "+" : ""}{s.adjustment}
                    </span>
                    {s.source === "espn_auto" && (
                      <span className="text-[9px] text-slate-500 border border-[#1C212B] rounded px-1 py-[1px] ml-1 uppercase">
                        Auto -- ESPN Injury
                      </span>
                    )}
                    {s.source === "espn_stats_auto" && (
                      <span className="text-[9px] text-slate-500 border border-[#1C212B] rounded px-1 py-[1px] ml-1 uppercase">
                        Auto -- ESPN Stats
                      </span>
                    )}
                    {s.note && <span className="text-slate-500"> -- {s.note}</span>}
                  </div>
                  <button onClick={() => removeStatus(s.id)} className="text-slate-600 hover:text-red-400">
                    <X size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="xl:col-span-2 bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 h-fit">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest flex items-center gap-2">
            <Trophy className="text-[#00FF5B]" size={14} /> Power Rankings
          </h3>
          <div className="flex items-center gap-2">
            <button
              onClick={runEspnSyncNow}
              disabled={syncing}
              title="Runs auto-settlement, injury sync, and stats sync right now instead of waiting for their scheduled polls"
              className="bg-[#06080A] border border-[#00FF5B] text-[#00FF5B] font-bold text-[10px] uppercase rounded-lg px-3 py-1.5 hover:bg-[#00FF5B]/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {syncing ? "Syncing..." : "Sync ESPN Data Now"}
            </button>
            <select
              value={sport}
              onChange={(e) => setSport(e.target.value)}
              className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-1 text-xs text-white"
            >
              <option value="NFL">NFL</option>
              <option value="NBA">NBA</option>
              <option value="MLB">MLB</option>
              <option value="NCAAF">NCAAF</option>
            </select>
          </div>
        </div>
        {(syncResult || syncError) && (
          <div className={`text-[11px] mb-3 ${syncError ? "text-red-400" : "text-[#00FF5B]"}`}>
            {syncError || syncResult}
          </div>
        )}
        {ratings.length === 0 ? (
          <p className="text-slate-600 text-xs italic">
            No {sport} results logged yet -- every team starts neutral at 1500 (wide uncertainty) until you log a game.
          </p>
        ) : (
          <table className="w-full text-xs text-left">
            <thead>
              <tr className="text-slate-500 uppercase text-[10px] tracking-wider border-b border-[#1C212B]">
                <th className="py-2 pr-3">#</th>
                <th className="py-2 pr-3">Team</th>
                <th className="py-2 pr-3">Rating</th>
                <th className="py-2 pr-3">Confidence</th>
                <th className="py-2 pr-3">Games</th>
              </tr>
            </thead>
            <tbody>
              {ratings.map((r, i) => (
                <tr key={r.team} className="border-b border-[#1C212B]/50 text-slate-300">
                  <td className="py-2 pr-3 text-slate-600">{i + 1}</td>
                  <td className="py-2 pr-3 text-white font-semibold">{r.team}</td>
                  <td className="py-2 pr-3 text-[#00FF5B] font-bold">{r.rating}</td>
                  <td className={`py-2 pr-3 font-semibold ${confidenceColor[r.confidence] || "text-slate-500"}`}>
                    {r.confidence}
                  </td>
                  <td className="py-2 pr-3">{r.games_played}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </motion.div>
  );
}
