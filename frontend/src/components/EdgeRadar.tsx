"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Radar, Loader2 } from "lucide-react";
import { useDashboardStore } from "@/store/useDashboardStore";

const backendUrl = () => process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

type Opportunity = {
  matchup: string;
  commence_time: string;
  favored_team: string;
  favored_win_probability_pct: number;
  favored_confidence: "High" | "Medium" | "Low";
  best_price: number;
  best_book: string;
  edge_pct: number;
  expected_value: number;
  recommended_wager: number;
  kelly_pct: number;
};

const confidenceColor: Record<string, string> = {
  High: "text-[#00FF5B]",
  Medium: "text-yellow-400",
  Low: "text-slate-500",
};

export default function EdgeRadar() {
  const riskProfile = useDashboardStore((s) => s.riskProfile);
  const [sport, setSport] = useState("NFL");
  const [minEdge, setMinEdge] = useState("1");
  const [bankroll, setBankroll] = useState("1000");
  const [opportunities, setOpportunities] = useState<Opportunity[] | null>(null);
  const [scannedGames, setScannedGames] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function scan() {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        sport, min_edge_pct: minEdge, bankroll, risk_profile: riskProfile,
      });
      const res = await fetch(`${backendUrl()}/edge-radar?${params}`);
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || "Scan failed");
      }
      const data = await res.json();
      setOpportunities(data.opportunities);
      setScannedGames(data.scanned_games);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed");
      setOpportunities(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 min-h-[400px] flex flex-col gap-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-bold text-slate-300 uppercase tracking-widest flex items-center gap-2">
          <Radar className="text-[#00FF5B]" size={18} /> Edge Radar
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
            value={minEdge}
            onChange={(e) => setMinEdge(e.target.value)}
            type="number"
            step="0.5"
            title="Minimum edge %"
            className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white w-20"
          />
          <input
            value={bankroll}
            onChange={(e) => setBankroll(e.target.value)}
            type="number"
            title="Bankroll ($)"
            className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white w-24"
          />
          <button
            onClick={scan}
            disabled={loading}
            className="bg-[#00FF5B] text-[#06080A] font-bold text-xs uppercase rounded-lg px-4 py-2 hover:opacity-90 transition-opacity disabled:opacity-50 flex items-center gap-2"
          >
            {loading && <Loader2 className="animate-spin" size={12} />}
            Scan Slate
          </button>
        </div>
      </div>

      {error && <div className="text-red-400 text-xs">{error}</div>}

      {opportunities === null && !loading && !error && (
        <p className="text-slate-600 text-sm italic text-center py-10">
          Runs the power-rating model against every live {sport} game at once and ranks them by predicted edge --
          instead of checking one matchup at a time. Requires ODDS_API_KEY.
        </p>
      )}

      {scannedGames !== null && (
        <p className="text-[11px] text-slate-600">
          Scanned {scannedGames} live {sport} games &middot; {opportunities?.length ?? 0} above {minEdge}% edge, sized for a {riskProfile.toLowerCase()} bankroll.
        </p>
      )}

      {opportunities && opportunities.length === 0 && (
        <p className="text-slate-500 text-sm italic text-center py-10">
          No game clears {minEdge}% edge right now -- the model and the market mostly agree.
        </p>
      )}

      {opportunities && opportunities.length > 0 && (
        <div className="flex flex-col gap-3">
          {opportunities.map((op, i) => (
            <div key={i} className="border border-[#00FF5B]/30 bg-[#00FF5B]/5 rounded-xl p-4 flex flex-wrap justify-between gap-3">
              <div>
                <div className="text-white font-semibold text-sm">{op.matchup}</div>
                <div className="text-[11px] text-slate-400 mt-1">
                  Model favors <span className="text-white font-medium">{op.favored_team}</span> at{" "}
                  {op.favored_win_probability_pct}% (
                  <span className={confidenceColor[op.favored_confidence] || "text-slate-500"}>
                    {op.favored_confidence} confidence
                  </span>
                  ) &middot; best price {op.best_price > 0 ? `+${op.best_price}` : op.best_price} ({op.best_book})
                </div>
                <div className="text-[11px] text-slate-500 mt-1">
                  Kelly ({riskProfile}): ${op.recommended_wager} ({op.kelly_pct}% of bankroll)
                </div>
              </div>
              <div className="text-right self-center">
                <div className="text-[#00FF5B] font-black text-lg">+{op.edge_pct}%</div>
                <div className="text-[10px] text-slate-500">EV ${op.expected_value}/100</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </motion.div>
  );
}
