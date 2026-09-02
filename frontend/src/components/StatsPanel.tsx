"use client";

import { useState, useCallback, useEffect } from "react";
import { motion } from "framer-motion";
import { BarChart3, Loader2, Search } from "lucide-react";

// Defensive: the backend's stat values should always be scalars, but a
// future ESPN response shape change (or a parsing edge case) could in
// theory hand us an object/array. Rendering that directly as a React child
// throws and takes down the whole page (this happened once already) -- so
// always coerce to a safe, displayable string instead of trusting the type.
function renderStatValue(v: unknown): string {
  if (v === null || v === undefined) return "--";
  if (typeof v === "object") {
    try {
      return JSON.stringify(v);
    } catch {
      return String(v);
    }
  }
  return String(v);
}

const backendUrl = () => process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

type StandingsRow = {
  team: string;
  group?: string;
  wins: number | string | null;
  losses: number | string | null;
  win_pct: number | string | null;
  points_per_game?: number | null;
  points_for?: number | string | null;
  points_against?: number | string | null;
  points_allowed_per_game?: number | null;
  point_differential?: number | string | null;
  rating?: number;
  confidence?: string;
  streak?: string | null;
};

export default function StatsPanel() {
  const [sport, setSport] = useState("NFL");
  const [source, setSource] = useState<"espn" | "mine">("espn");
  const [standings, setStandings] = useState<StandingsRow[] | null>(null);
  const [standingsError, setStandingsError] = useState<string | null>(null);
  const [loadingStandings, setLoadingStandings] = useState(false);

  const [teamQuery, setTeamQuery] = useState("");
  const [teamStats, setTeamStats] = useState<Record<string, string> | null>(null);
  const [teamError, setTeamError] = useState<string | null>(null);
  const [loadingTeam, setLoadingTeam] = useState(false);

  const [playerTeam, setPlayerTeam] = useState("");
  const [playerName, setPlayerName] = useState("");
  const [playerResult, setPlayerResult] = useState<{ player?: string; position?: string; stats?: Record<string, string>; error?: string } | null>(null);
  const [loadingPlayer, setLoadingPlayer] = useState(false);

  const loadStandings = useCallback(async () => {
    setLoadingStandings(true);
    setStandingsError(null);
    try {
      const endpoint = source === "espn" ? `/espn/standings?sport=${sport}` : `/my-record/${sport}`;
      const res = await fetch(`${backendUrl()}${endpoint}`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setStandings(data.standings || []);
    } catch (err) {
      setStandingsError(err instanceof Error ? err.message : "Failed to load standings");
      setStandings(null);
    } finally {
      setLoadingStandings(false);
    }
  }, [sport, source]);

  useEffect(() => {
    loadStandings();
  }, [loadStandings]);

  async function lookupTeam(e: React.FormEvent) {
    e.preventDefault();
    if (!teamQuery.trim()) return;
    setLoadingTeam(true);
    setTeamError(null);
    setTeamStats(null);
    try {
      const res = await fetch(`${backendUrl()}/espn/team-stats?sport=${sport}&team=${encodeURIComponent(teamQuery)}`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setTeamStats(data.stats || {});
    } catch (err) {
      setTeamError(err instanceof Error ? err.message : "Lookup failed");
    } finally {
      setLoadingTeam(false);
    }
  }

  async function lookupPlayer(e: React.FormEvent) {
    e.preventDefault();
    if (!playerTeam.trim() || !playerName.trim()) return;
    setLoadingPlayer(true);
    setPlayerResult(null);
    try {
      const res = await fetch(
        `${backendUrl()}/espn/player-stats?sport=${sport}&team=${encodeURIComponent(playerTeam)}&player=${encodeURIComponent(playerName)}`
      );
      setPlayerResult(await res.json());
    } catch (err) {
      setPlayerResult({ error: err instanceof Error ? err.message : "Lookup failed" });
    } finally {
      setLoadingPlayer(false);
    }
  }

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-6">
      <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
          <h2 className="text-lg font-bold text-slate-300 uppercase tracking-widest flex items-center gap-2">
            <BarChart3 className="text-[#00FF5B]" size={18} /> Standings
          </h2>
          <div className="flex items-center gap-2">
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
            <div className="flex bg-[#06080A] border border-[#1C212B] rounded-lg overflow-hidden">
              <button
                onClick={() => setSource("espn")}
                className={`px-3 py-2 text-xs font-bold uppercase ${source === "espn" ? "bg-[#00FF5B] text-[#06080A]" : "text-slate-400"}`}
              >
                Official
              </button>
              <button
                onClick={() => setSource("mine")}
                className={`px-3 py-2 text-xs font-bold uppercase ${source === "mine" ? "bg-[#00FF5B] text-[#06080A]" : "text-slate-400"}`}
              >
                My Record
              </button>
            </div>
          </div>
        </div>
        <p className="text-[11px] text-slate-500 mb-4">
          {source === "espn"
            ? "Official league standings, pulled live from ESPN's public API (unofficial -- not a documented/guaranteed source)."
            : "Your own record, computed only from games you've logged via the Ratings tab -- not the full official schedule."}
        </p>

        {loadingStandings && (
          <div className="flex items-center gap-2 text-slate-500 text-xs py-6 justify-center">
            <Loader2 className="animate-spin" size={14} /> Loading...
          </div>
        )}
        {standingsError && <div className="text-red-400 text-xs">{standingsError}</div>}
        {!loadingStandings && standings && standings.length === 0 && (
          <p className="text-slate-600 text-xs italic">No standings data yet.</p>
        )}
        {!loadingStandings && standings && standings.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left min-w-[560px]">
              <thead>
                <tr className="text-slate-500 uppercase text-[10px] tracking-wider border-b border-[#1C212B]">
                  <th className="py-2 pr-3">Team</th>
                  <th className="py-2 pr-3">W</th>
                  <th className="py-2 pr-3">L</th>
                  <th className="py-2 pr-3">Win%</th>
                  <th className="py-2 pr-3">PF</th>
                  <th className="py-2 pr-3">PA</th>
                  <th className="py-2 pr-3">Diff</th>
                </tr>
              </thead>
              <tbody>
                {standings.map((s, i) => (
                  <tr key={i} className="border-b border-[#1C212B]/50 text-slate-300">
                    <td className="py-2 pr-3 text-white font-semibold">{s.team}</td>
                    <td className="py-2 pr-3">{s.wins ?? "--"}</td>
                    <td className="py-2 pr-3">{s.losses ?? "--"}</td>
                    <td className="py-2 pr-3">{s.win_pct ?? "--"}</td>
                    <td className="py-2 pr-3">{s.points_per_game ?? s.points_for ?? "--"}</td>
                    <td className="py-2 pr-3">{s.points_allowed_per_game ?? s.points_against ?? "--"}</td>
                    <td className={`py-2 pr-3 font-semibold ${(Number(s.point_differential) || 0) >= 0 ? "text-[#00FF5B]" : "text-red-400"}`}>
                      {s.point_differential ?? "--"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6">
          <h3 className="text-xs font-bold text-[#00FF5B] uppercase tracking-widest mb-4">Team Stats Lookup</h3>
          <form onSubmit={lookupTeam} className="flex items-end gap-2 mb-4">
            <input
              value={teamQuery}
              onChange={(e) => setTeamQuery(e.target.value)}
              placeholder="Team name"
              className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white flex-1"
            />
            <button
              type="submit"
              disabled={loadingTeam}
              className="bg-[#00FF5B] text-[#06080A] font-bold text-xs uppercase rounded-lg px-3 py-2 hover:opacity-90 transition-opacity disabled:opacity-50 flex items-center gap-1"
            >
              {loadingTeam ? <Loader2 className="animate-spin" size={12} /> : <Search size={12} />}
            </button>
          </form>
          {teamError && <div className="text-red-400 text-xs mb-2">{teamError}</div>}
          {teamStats && Object.keys(teamStats).length === 0 && (
            <p className="text-slate-600 text-xs italic">Team found, but ESPN didn&apos;t return any stat categories for it.</p>
          )}
          {teamStats && Object.keys(teamStats).length > 0 && (
            <div className="flex flex-col gap-1 max-h-64 overflow-y-auto pr-3 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:bg-[#1C212B] [&::-webkit-scrollbar-thumb]:rounded-full">
              {Object.entries(teamStats).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3 text-[11px] border-b border-[#1C212B]/50 py-1">
                  <span className="text-slate-400">{k}</span>
                  <span className="text-white font-semibold shrink-0">{renderStatValue(v)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6">
          <h3 className="text-xs font-bold text-[#00FF5B] uppercase tracking-widest mb-4">Player Stats Lookup</h3>
          <form onSubmit={lookupPlayer} className="flex flex-col gap-2 mb-4">
            <input
              value={playerTeam}
              onChange={(e) => setPlayerTeam(e.target.value)}
              placeholder="Team"
              className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white"
            />
            <div className="flex items-end gap-2">
              <input
                value={playerName}
                onChange={(e) => setPlayerName(e.target.value)}
                placeholder="Player name"
                className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white flex-1"
              />
              <button
                type="submit"
                disabled={loadingPlayer}
                className="bg-[#00FF5B] text-[#06080A] font-bold text-xs uppercase rounded-lg px-3 py-2 hover:opacity-90 transition-opacity disabled:opacity-50 flex items-center gap-1"
              >
                {loadingPlayer ? <Loader2 className="animate-spin" size={12} /> : <Search size={12} />}
              </button>
            </div>
          </form>
          {playerResult?.error && <div className="text-red-400 text-xs mb-2">{playerResult.error}</div>}
          {playerResult && !playerResult.error && (
            <div>
              <div className="text-white font-semibold text-sm mb-1">
                {playerResult.player} {playerResult.position && <span className="text-slate-500 text-xs">({playerResult.position})</span>}
              </div>
              {playerResult.stats && Object.keys(playerResult.stats).length > 0 ? (
                <div className="flex flex-col gap-1 max-h-64 overflow-y-auto pr-3 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:bg-[#1C212B] [&::-webkit-scrollbar-thumb]:rounded-full">
                  {Object.entries(playerResult.stats).map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-3 text-[11px] border-b border-[#1C212B]/50 py-1">
                      <span className="text-slate-400">{k}</span>
                      <span className="text-white font-semibold shrink-0">{renderStatValue(v)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-slate-600 text-xs italic">Found on the roster, but no stats came back from ESPN for this player.</p>
              )}
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}
