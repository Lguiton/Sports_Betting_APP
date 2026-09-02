"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Layers, Loader2 } from "lucide-react";

const backendUrl = () => process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

type Opportunity = {
  matchup: string;
  commence_time: string;
  home_leg: { book: string; price: number };
  away_leg: { book: string; price: number };
  guaranteed_edge_pct: number;
};

export default function ArbitrageScanner() {
  const [sport, setSport] = useState("NFL");
  const [minEdge, setMinEdge] = useState("0.5");
  const [opportunities, setOpportunities] = useState<Opportunity[] | null>(null);
  const [scannedGames, setScannedGames] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function scan() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${backendUrl()}/arbitrage/scan?sport=${sport}&min_edge_pct=${encodeURIComponent(minEdge)}`
      );
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
          <Layers className="text-[#00FF5B]" size={18} /> Cross-Book Arbitrage
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
            step="0.1"
            title="Minimum guaranteed edge %"
            className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white w-24"
          />
          <button
            onClick={scan}
            disabled={loading}
            className="bg-[#00FF5B] text-[#06080A] font-bold text-xs uppercase rounded-lg px-4 py-2 hover:opacity-90 transition-opacity disabled:opacity-50 flex items-center gap-2"
          >
            {loading && <Loader2 className="animate-spin" size={12} />}
            Scan
          </button>
        </div>
      </div>

      {error && <div className="text-red-400 text-xs">{error}</div>}

      {opportunities === null && !loading && !error && (
        <p className="text-slate-600 text-sm italic text-center py-10">
          Scans every live {sport} game across bookmakers for a price gap that guarantees profit no matter who wins.
          Requires ODDS_API_KEY to be set.
        </p>
      )}

      {scannedGames !== null && (
        <p className="text-[11px] text-slate-600">Scanned {scannedGames} live {sport} games.</p>
      )}

      {opportunities && opportunities.length === 0 && (
        <p className="text-slate-500 text-sm italic text-center py-10">No arbitrage above {minEdge}% found right now.</p>
      )}

      {opportunities && opportunities.length > 0 && (
        <div className="flex flex-col gap-3">
          {opportunities.map((op, i) => (
            <div key={i} className="border border-[#00FF5B]/30 bg-[#00FF5B]/5 rounded-xl p-4 flex flex-wrap justify-between gap-3">
              <div>
                <div className="text-white font-semibold text-sm">{op.matchup}</div>
                <div className="text-[11px] text-slate-400 mt-1">
                  {op.home_leg.book}: {op.home_leg.price > 0 ? `+${op.home_leg.price}` : op.home_leg.price} (home) &middot;{" "}
                  {op.away_leg.book}: {op.away_leg.price > 0 ? `+${op.away_leg.price}` : op.away_leg.price} (away)
                </div>
              </div>
              <div className="text-[#00FF5B] font-black text-lg self-center">+{op.guaranteed_edge_pct}%</div>
            </div>
          ))}
        </div>
      )}
    </motion.div>
  );
}
