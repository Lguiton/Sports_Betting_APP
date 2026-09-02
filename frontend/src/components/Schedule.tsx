"use client";

import { useState, useCallback, useEffect } from "react";
import { motion } from "framer-motion";
import { CalendarDays, Loader2, Check, AlertTriangle } from "lucide-react";

const backendUrl = () => process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

type Side = { team: string; price: number; book: string } | null;
type Game = {
  matchup: string;
  home_team: string;
  away_team: string;
  commence_time: string | null;
  market_favorite: Side;
  market_underdog: Side;
  model_favorite: string;
  model_win_probability_pct: number;
  model_confidence: "High" | "Medium" | "Low";
  model_agrees_with_market: boolean;
};
type ScheduleResult = { sport: string; date: string | null; scanned_games: number; games: Game[] };
type ProbablePitchers = Record<string, { home?: string; away?: string }>; // keyed by "home@away"

const confidenceColor: Record<string, string> = {
  High: "text-[#00FF5B]",
  Medium: "text-yellow-400",
  Low: "text-slate-500",
};

function formatPrice(p: number | undefined | null) {
  if (p == null) return "--";
  return p > 0 ? `+${p}` : `${p}`;
}

export default function Schedule() {
  const [sport, setSport] = useState("NFL");
  const [date, setDate] = useState("");
  const [result, setResult] = useState<ScheduleResult | null>(null);
  const [pitchers, setPitchers] = useState<ProbablePitchers>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ sport });
      if (date) params.set("date", date);
      const res = await fetch(`${backendUrl()}/schedule?${params}`);
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || "Failed to load schedule");
      }
      const data: ScheduleResult = await res.json();
      setResult(data);

      if (sport === "MLB") {
        try {
          const espnRes = await fetch(`${backendUrl()}/espn/schedule?sport=MLB${date ? `&date=${date}` : ""}`);
          if (espnRes.ok) {
            const espnData = await espnRes.json();
            const map: ProbablePitchers = {};
            for (const g of espnData.games || []) {
              if (g.probable_pitchers) {
                map[`${g.home_team}@${g.away_team}`] = g.probable_pitchers;
              }
            }
            setPitchers(map);
          }
        } catch {
          // probable pitchers are a bonus, not core -- fail silently
        }
      } else {
        setPitchers({});
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load schedule");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [sport, date]);

  useEffect(() => {
    load();
  }, [load]);

  function findPitchers(g: Game) {
    return pitchers[`${g.home_team}@${g.away_team}`];
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 min-h-[400px] flex flex-col gap-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-bold text-slate-300 uppercase tracking-widest flex items-center gap-2">
          <CalendarDays className="text-[#00FF5B]" size={18} /> Schedule
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
          <input
            value={date}
            onChange={(e) => setDate(e.target.value)}
            type="date"
            title="Filter to one day (leave blank for the full current board)"
            className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white"
          />
          {date && (
            <button onClick={() => setDate("")} className="text-[10px] text-slate-500 hover:text-white">
              clear
            </button>
          )}
        </div>
      </div>

      <p className="text-[11px] text-slate-500">
        The Odds API board isn&apos;t strictly &quot;today only&quot; -- it&apos;s every game currently listed. Pick a date to narrow it down.
        {sport === "MLB" && " Probable pitchers (when ESPN has them listed) show under each game."}
      </p>

      {loading && (
        <div className="flex items-center gap-2 text-slate-500 text-xs py-10 justify-center">
          <Loader2 className="animate-spin" size={14} /> Loading...
        </div>
      )}
      {error && <div className="text-red-400 text-xs">{error}</div>}

      {!loading && result && result.games.length === 0 && (
        <p className="text-slate-500 text-sm italic text-center py-10">No games found{date ? ` for ${date}` : ""}.</p>
      )}

      {!loading && result && result.games.length > 0 && (
        <div className="flex flex-col gap-3">
          {result.games.map((g, i) => {
            const gp = findPitchers(g);
            return (
              <div key={i} className="border border-[#1C212B] rounded-xl p-4 flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-white font-semibold text-sm">{g.matchup}</div>
                  <div className="text-[10px] text-slate-500">{g.commence_time}</div>
                </div>

                <div className="flex flex-wrap items-center gap-4 text-[11px]">
                  <div>
                    <span className="text-slate-500">Market: </span>
                    {g.market_favorite ? (
                      <>
                        <span className="text-white font-medium">{g.market_favorite.team}</span>{" "}
                        <span className="text-[#00FF5B]">{formatPrice(g.market_favorite.price)}</span>{" "}
                        <span className="text-slate-600">({g.market_favorite.book})</span>
                        <span className="text-slate-500"> favored over </span>
                        <span className="text-slate-300">{g.market_underdog?.team}</span>{" "}
                        <span className="text-slate-400">{formatPrice(g.market_underdog?.price)}</span>
                      </>
                    ) : (
                      <span className="text-slate-600">no market price available</span>
                    )}
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2 text-[11px]">
                  <span className="text-slate-500">Model: </span>
                  <span className="text-white font-medium">{g.model_favorite}</span>
                  <span>{g.model_win_probability_pct}%</span>
                  <span className={confidenceColor[g.model_confidence] || "text-slate-500"}>
                    ({g.model_confidence} confidence)
                  </span>
                  {g.market_favorite && (
                    g.model_agrees_with_market ? (
                      <span className="flex items-center gap-1 text-[#00FF5B]"><Check size={12} /> agrees with market</span>
                    ) : (
                      <span className="flex items-center gap-1 text-yellow-400"><AlertTriangle size={12} /> disagrees with market</span>
                    )
                  )}
                </div>

                {gp && (
                  <div className="text-[11px] text-slate-400 border-t border-[#1C212B] pt-2 mt-1">
                    Probable pitchers: {gp.away && <span>{g.away_team}: <span className="text-white">{gp.away}</span></span>}
                    {gp.away && gp.home && " · "}
                    {gp.home && <span>{g.home_team}: <span className="text-white">{gp.home}</span></span>}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </motion.div>
  );
}
