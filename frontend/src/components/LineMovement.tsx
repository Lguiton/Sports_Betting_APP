"use client";

import { useState, useCallback, useEffect } from "react";
import { motion } from "framer-motion";
import { Activity, Loader2, Power } from "lucide-react";

const backendUrl = () => process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

type Snapshot = {
  best_home_price: number | null;
  best_home_book: string | null;
  best_away_price: number | null;
  best_away_book: string | null;
  commence_time: string | null;
  captured_at: string;
};
type Movement = { home_implied_prob_shift_pct: number | null; steam_move: boolean } | null;
type LineMovementResult = { matchup: string; snapshots: Snapshot[]; movement: Movement };
type TrackingStatus = { line_tracking_enabled: boolean; last_run: string | null; poll_interval_minutes: number };
type SteamAlert = {
  sport: string;
  matchup: string;
  home_team: string;
  away_team: string;
  home_implied_prob_shift_pct: number;
  direction: "toward home" | "toward away";
  snapshots: number;
  latest_snapshot: string;
};

export default function LineMovement() {
  const [sport, setSport] = useState("NFL");
  const [homeTeam, setHomeTeam] = useState("");
  const [awayTeam, setAwayTeam] = useState("");
  const [result, setResult] = useState<LineMovementResult | null>(null);
  const [status, setStatus] = useState<TrackingStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<SteamAlert[] | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const res = await fetch(`${backendUrl()}/line-tracking/status`);
      if (res.ok) setStatus(await res.json());
    } catch {
      // silent -- backend may not be running yet
    }
  }, []);

  const refreshAlerts = useCallback(async () => {
    try {
      const res = await fetch(`${backendUrl()}/line-movement/alerts`);
      if (res.ok) setAlerts((await res.json()).alerts);
    } catch {
      // silent -- backend may not be running yet
    }
  }, []);

  useEffect(() => {
    refreshStatus();
    refreshAlerts();
  }, [refreshStatus, refreshAlerts]);

  async function toggleTracking() {
    if (!status) return;
    try {
      const res = await fetch(`${backendUrl()}/line-tracking/enabled`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !status.line_tracking_enabled }),
      });
      if (res.ok) await refreshStatus();
    } catch (err) {
      console.error(err);
    }
  }

  async function lookup(e: React.FormEvent) {
    e.preventDefault();
    if (!homeTeam.trim() || !awayTeam.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ sport, home_team: homeTeam, away_team: awayTeam });
      const res = await fetch(`${backendUrl()}/line-movement?${params}`);
      if (!res.ok) throw new Error("Lookup failed");
      setResult(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lookup failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-6">
      <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-slate-300 uppercase tracking-widest flex items-center gap-2">
            <Activity className="text-[#00FF5B]" size={18} /> Line Tracker
          </h2>
          <p className="text-[11px] text-slate-500 mt-1 max-w-xl">
            When on, polls the odds board every {status?.poll_interval_minutes ?? 15} minutes for any matchup you
            have an open bet on -- snapshotting price history and auto-filling your closing line (CLV) once the
            game starts. Only tracks matchups tied to an open bet, so it never burns your Odds API quota scanning
            the whole board. Off by default.
          </p>
        </div>
        <button
          onClick={toggleTracking}
          disabled={!status}
          className={`flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-bold uppercase transition-opacity disabled:opacity-50 ${
            status?.line_tracking_enabled
              ? "bg-[#00FF5B] text-[#06080A]"
              : "bg-[#06080A] border border-[#1C212B] text-slate-400"
          }`}
        >
          <Power size={12} />
          {status?.line_tracking_enabled ? "Tracking ON" : "Tracking OFF"}
        </button>
      </div>

      <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6">
        <h3 className="text-xs font-bold text-[#00FF5B] uppercase tracking-widest mb-4">Steam Alerts</h3>
        <p className="text-[11px] text-slate-500 mb-4 max-w-xl">
          Every currently-tracked matchup (any matchup with an open bet) whose price has moved 5+ points of
          implied probability since the first snapshot -- no need to already know which game to look up below.
        </p>
        {!alerts || alerts.length === 0 ? (
          <p className="text-slate-600 text-xs italic">
            No steam moves detected yet -- needs Tracking ON and at least two snapshots for a matchup.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {alerts.map((a) => (
              <div
                key={`${a.sport}-${a.matchup}`}
                className="flex items-center justify-between text-[11px] border-t border-[#1C212B] pt-2"
              >
                <div className="text-slate-300">
                  <span className="text-slate-500 uppercase text-[9px] mr-2">{a.sport}</span>
                  <span className="text-white font-semibold">{a.matchup}</span>
                </div>
                <div className={a.home_implied_prob_shift_pct > 0 ? "text-[#00FF5B]" : "text-red-400"}>
                  {a.home_implied_prob_shift_pct > 0 ? "+" : ""}
                  {a.home_implied_prob_shift_pct}% ({a.direction})
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6">
        <h3 className="text-xs font-bold text-[#00FF5B] uppercase tracking-widest mb-4">Price History Lookup</h3>
        <form onSubmit={lookup} className="flex flex-wrap items-end gap-3 mb-6">
          <select
            value={sport}
            onChange={(e) => setSport(e.target.value)}
            className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white"
          >
            <option value="NFL">NFL</option>
            <option value="NBA">NBA</option>
            <option value="MLB">MLB</option>
            <option value="NCAAF">NCAAF</option>
          </select>
          <input
            value={homeTeam}
            onChange={(e) => setHomeTeam(e.target.value)}
            placeholder="Home team"
            className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white"
          />
          <input
            value={awayTeam}
            onChange={(e) => setAwayTeam(e.target.value)}
            placeholder="Away team"
            className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white"
          />
          <button
            type="submit"
            disabled={loading}
            className="bg-[#00FF5B] text-[#06080A] font-bold text-xs uppercase rounded-lg px-4 py-2 hover:opacity-90 transition-opacity disabled:opacity-50 flex items-center gap-2"
          >
            {loading && <Loader2 className="animate-spin" size={12} />}
            Look Up
          </button>
        </form>

        {error && <div className="text-red-400 text-xs mb-4">{error}</div>}

        {!result && !error && (
          <p className="text-slate-600 text-xs italic">
            No snapshots yet for a matchup until it has an open bet logged and tracking has run at least once.
          </p>
        )}

        {result && result.snapshots.length === 0 && (
          <p className="text-slate-500 text-xs italic">No snapshots recorded yet for {result.matchup}.</p>
        )}

        {result && result.snapshots.length > 0 && (
          <div className="flex flex-col gap-4">
            <div className="text-white font-semibold text-sm">{result.matchup}</div>
            {result.movement && (
              <div className={`text-xs ${result.movement.steam_move ? "text-yellow-400" : "text-slate-400"}`}>
                Home implied-probability shift: {result.movement.home_implied_prob_shift_pct ?? "--"}%
                {result.movement.steam_move ? " -- steam move detected" : ""}
              </div>
            )}
            <table className="w-full text-xs text-left">
              <thead>
                <tr className="text-slate-500 uppercase text-[10px] tracking-wider border-b border-[#1C212B]">
                  <th className="py-2 pr-3">Captured</th>
                  <th className="py-2 pr-3">Home Price</th>
                  <th className="py-2 pr-3">Away Price</th>
                </tr>
              </thead>
              <tbody>
                {result.snapshots.map((s, i) => (
                  <tr key={i} className="border-b border-[#1C212B]/50 text-slate-300">
                    <td className="py-2 pr-3">{s.captured_at}</td>
                    <td className="py-2 pr-3">
                      {s.best_home_price != null ? (s.best_home_price > 0 ? `+${s.best_home_price}` : s.best_home_price) : "--"}{" "}
                      {s.best_home_book && <span className="text-slate-600">({s.best_home_book})</span>}
                    </td>
                    <td className="py-2 pr-3">
                      {s.best_away_price != null ? (s.best_away_price > 0 ? `+${s.best_away_price}` : s.best_away_price) : "--"}{" "}
                      {s.best_away_book && <span className="text-slate-600">({s.best_away_book})</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </motion.div>
  );
}
