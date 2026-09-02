"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Search, Loader2 } from "lucide-react";

const backendUrl = () => process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

type BookPrice = { book: string; home_price: number | null; away_price: number | null; last_update: string };
type CompareResult = {
  matchup: string;
  commence_time: string;
  books: BookPrice[];
  best_home_price: { book: string; price: number } | null;
  best_away_price: { book: string; price: number } | null;
};

export default function OddsCompare() {
  const [sport, setSport] = useState("NFL");
  const [homeTeam, setHomeTeam] = useState("");
  const [awayTeam, setAwayTeam] = useState("");
  const [result, setResult] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function compare(e: React.FormEvent) {
    e.preventDefault();
    if (!homeTeam.trim() || !awayTeam.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const params = new URLSearchParams({ sport, home_team: homeTeam, away_team: awayTeam });
      const res = await fetch(`${backendUrl()}/odds/compare?${params}`);
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || "No odds found for that matchup");
      }
      setResult(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lookup failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6">
      <h3 className="text-xs font-bold text-[#00FF5B] uppercase tracking-widest mb-4">Multi-Book Odds Comparison</h3>

      <form onSubmit={compare} className="flex flex-wrap items-end gap-3 mb-6">
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
          {loading ? <Loader2 className="animate-spin" size={12} /> : <Search size={12} />}
          Compare
        </button>
      </form>

      {error && <div className="text-red-400 text-xs mb-4">{error}</div>}

      {!result && !error && (
        <p className="text-slate-600 text-xs italic">
          Look up a matchup to see every bookmaker&apos;s current price side by side. Requires ODDS_API_KEY.
        </p>
      )}

      {result && (
        <div className="flex flex-col gap-4">
          <div className="text-white font-semibold text-sm">{result.matchup}</div>
          {(result.best_home_price || result.best_away_price) && (
            <div className="flex gap-4 text-[11px] text-slate-400">
              {result.best_home_price && (
                <span>
                  Best home price: <span className="text-[#00FF5B] font-bold">{result.best_home_price.price}</span> ({result.best_home_price.book})
                </span>
              )}
              {result.best_away_price && (
                <span>
                  Best away price: <span className="text-[#00FF5B] font-bold">{result.best_away_price.price}</span> ({result.best_away_price.book})
                </span>
              )}
            </div>
          )}
          <table className="w-full text-xs text-left">
            <thead>
              <tr className="text-slate-500 uppercase text-[10px] tracking-wider border-b border-[#1C212B]">
                <th className="py-2 pr-3">Book</th>
                <th className="py-2 pr-3">Home</th>
                <th className="py-2 pr-3">Away</th>
              </tr>
            </thead>
            <tbody>
              {result.books.map((b) => (
                <tr key={b.book} className="border-b border-[#1C212B]/50 text-slate-300">
                  <td className="py-2 pr-3 text-white">{b.book}</td>
                  <td className="py-2 pr-3">{b.home_price != null ? (b.home_price > 0 ? `+${b.home_price}` : b.home_price) : "--"}</td>
                  <td className="py-2 pr-3">{b.away_price != null ? (b.away_price > 0 ? `+${b.away_price}` : b.away_price) : "--"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </motion.div>
  );
}
