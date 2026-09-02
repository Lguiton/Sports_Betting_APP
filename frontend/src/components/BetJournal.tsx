"use client";

import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import { Check, X, Minus, Ban } from "lucide-react";

const backendUrl = () => process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

type Bet = {
  id: number;
  sport: string;
  matchup: string;
  bet_type: string;
  selection: string;
  odds: number;
  stake: number;
  to_win: number;
  status: "pending" | "won" | "lost" | "push" | "void";
  result_profit: number | null;
  closing_odds: number | null;
  clv_pct: number | null;
  placed_at: string;
  graded_at: string | null;
  notes: string | null;
  home_team: string | null;
  away_team: string | null;
  graded_by: string | null;
};

type Performance = {
  graded_bets: number;
  wins: number;
  losses: number;
  win_rate_pct: number | null;
  total_staked: number;
  total_profit: number;
  roi_pct: number | null;
  avg_clv_pct: number | null;
  bankroll_curve: { date: string; cumulative_profit: number }[];
};

const EMPTY_FORM = { sport: "NFL", bet_type: "moneyline", home_team: "", away_team: "", selection: "", odds: "", stake: "", notes: "" };

export default function BetJournal() {
  const [bets, setBets] = useState<Bet[]>([]);
  const [performance, setPerformance] = useState<Performance | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [gradingId, setGradingId] = useState<number | null>(null);
  const [closingOddsInput, setClosingOddsInput] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [betsRes, perfRes] = await Promise.all([
        fetch(`${backendUrl()}/bets`),
        fetch(`${backendUrl()}/performance`),
      ]);
      if (betsRes.ok) setBets(await betsRes.json());
      if (perfRes.ok) setPerformance(await perfRes.json());
    } catch (err) {
      console.error("Failed to load bet journal:", err);
      setError("Couldn't reach the backend. Is it running?");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function submitBet(e: React.FormEvent) {
    e.preventDefault();
    if (!form.home_team.trim() || !form.away_team.trim() || !form.selection.trim() || !form.odds || !form.stake) return;
    setError(null);
    try {
      const res = await fetch(`${backendUrl()}/bets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sport: form.sport,
          bet_type: form.bet_type,
          home_team: form.home_team,
          away_team: form.away_team,
          selection: form.selection,
          odds: parseFloat(form.odds),
          stake: parseFloat(form.stake),
          notes: form.notes || undefined,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setForm({ ...EMPTY_FORM, sport: form.sport, bet_type: form.bet_type });
      refresh();
    } catch (err) {
      console.error(err);
      setError("Failed to log bet.");
    }
  }

  async function grade(id: number, status: "won" | "lost" | "push" | "void") {
    try {
      const res = await fetch(`${backendUrl()}/bets/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status,
          closing_odds: closingOddsInput ? parseFloat(closingOddsInput) : undefined,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setGradingId(null);
      setClosingOddsInput("");
      refresh();
    } catch (err) {
      console.error(err);
      setError("Failed to grade bet.");
    }
  }

  const pending = bets.filter((b) => b.status === "pending");
  const graded = bets.filter((b) => b.status !== "pending");

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-6">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <StatCard label="Win Rate" value={performance?.win_rate_pct != null ? `${performance.win_rate_pct}%` : "--"} />
        <StatCard label="Record" value={performance ? `${performance.wins}-${performance.losses}` : "--"} />
        <StatCard
          label="ROI"
          value={performance?.roi_pct != null ? `${performance.roi_pct}%` : "--"}
          tone={performance?.roi_pct != null ? (performance.roi_pct >= 0 ? "pos" : "neg") : "neutral"}
        />
        <StatCard
          label="Total P/L"
          value={performance ? `${performance.total_profit >= 0 ? "+" : ""}$${performance.total_profit}` : "--"}
          tone={performance ? (performance.total_profit >= 0 ? "pos" : "neg") : "neutral"}
        />
        <StatCard label="Avg CLV" value={performance?.avg_clv_pct != null ? `${performance.avg_clv_pct}%` : "--"} />
      </div>

      <form
        onSubmit={submitBet}
        className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 grid grid-cols-2 md:grid-cols-8 gap-3 items-end"
      >
        <Field label="Sport">
          <select
            value={form.sport}
            onChange={(e) => setForm({ ...form, sport: e.target.value })}
            className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white w-full"
          >
            <option value="NFL">NFL</option>
            <option value="NBA">NBA</option>
            <option value="MLB">MLB</option>
            <option value="NCAAF">NCAAF</option>
          </select>
        </Field>
        <Field label="Type">
          <select
            value={form.bet_type}
            onChange={(e) => setForm({ ...form, bet_type: e.target.value })}
            className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white w-full"
          >
            <option value="moneyline">Moneyline</option>
            <option value="spread">Spread</option>
            <option value="total">Total</option>
            <option value="other">Other</option>
          </select>
        </Field>
        <Field label="Home Team">
          <input
            value={form.home_team}
            onChange={(e) => setForm({ ...form, home_team: e.target.value })}
            placeholder="Ravens"
            className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white w-full"
          />
        </Field>
        <Field label="Away Team">
          <input
            value={form.away_team}
            onChange={(e) => setForm({ ...form, away_team: e.target.value })}
            placeholder="Chiefs"
            className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white w-full"
          />
        </Field>
        <Field label="Selection" className="col-span-2">
          <input
            value={form.selection}
            onChange={(e) => setForm({ ...form, selection: e.target.value })}
            placeholder="Chiefs ML"
            className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white w-full"
          />
        </Field>
        <Field label="Odds">
          <input
            value={form.odds}
            onChange={(e) => setForm({ ...form, odds: e.target.value })}
            placeholder="-150"
            type="number"
            className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white w-full"
          />
        </Field>
        <Field label="Stake ($)">
          <input
            value={form.stake}
            onChange={(e) => setForm({ ...form, stake: e.target.value })}
            placeholder="100"
            type="number"
            className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white w-full"
          />
        </Field>
        <button
          type="submit"
          className="col-span-2 md:col-span-1 bg-[#00FF5B] text-[#06080A] font-bold text-xs uppercase rounded-lg px-3 py-2 hover:opacity-90 transition-opacity"
        >
          Log Bet
        </button>
      </form>

      {error && <div className="text-red-400 text-xs">{error}</div>}

      {pending.length > 0 && (
        <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Pending ({pending.length})</h3>
          <div className="flex flex-col gap-2">
            {pending.map((bet) => (
              <div key={bet.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-[#1C212B] pb-2">
                <div className="text-xs text-slate-300">
                  <span className="text-white font-semibold">{bet.matchup}</span> &middot; {bet.selection} &middot;{" "}
                  <span className="text-[#00FF5B]">{bet.odds > 0 ? `+${bet.odds}` : bet.odds}</span> &middot; ${bet.stake} to win ${bet.to_win}
                </div>
                {gradingId === bet.id ? (
                  <div className="flex items-center gap-2">
                    <input
                      value={closingOddsInput}
                      onChange={(e) => setClosingOddsInput(e.target.value)}
                      placeholder="Closing odds (optional)"
                      type="number"
                      className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-1 text-[11px] text-white w-36"
                    />
                    <button onClick={() => grade(bet.id, "won")} className="text-[#00FF5B]" title="Won"><Check size={16} /></button>
                    <button onClick={() => grade(bet.id, "lost")} className="text-red-400" title="Lost"><X size={16} /></button>
                    <button onClick={() => grade(bet.id, "push")} className="text-slate-400" title="Push"><Minus size={16} /></button>
                    <button onClick={() => grade(bet.id, "void")} className="text-slate-500" title="Void"><Ban size={16} /></button>
                    <button onClick={() => setGradingId(null)} className="text-slate-600 text-[11px]">cancel</button>
                  </div>
                ) : (
                  <button
                    onClick={() => setGradingId(bet.id)}
                    className="text-[10px] uppercase font-bold text-slate-400 hover:text-[#00FF5B] border border-[#1C212B] rounded-lg px-3 py-1"
                  >
                    Grade
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 overflow-x-auto">
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">History ({graded.length})</h3>
        {graded.length === 0 ? (
          <p className="text-slate-600 text-xs italic">No graded bets yet.</p>
        ) : (
          <table className="w-full text-xs text-left min-w-[640px]">
            <thead>
              <tr className="text-slate-500 uppercase text-[10px] tracking-wider border-b border-[#1C212B]">
                <th className="py-2 pr-3">Matchup</th>
                <th className="py-2 pr-3">Selection</th>
                <th className="py-2 pr-3">Odds</th>
                <th className="py-2 pr-3">Stake</th>
                <th className="py-2 pr-3">Result</th>
                <th className="py-2 pr-3">P/L</th>
                <th className="py-2 pr-3">CLV</th>
                <th className="py-2 pr-3">Graded</th>
              </tr>
            </thead>
            <tbody>
              {graded.map((bet) => (
                <tr key={bet.id} className="border-b border-[#1C212B]/50 text-slate-300">
                  <td className="py-2 pr-3">{bet.matchup}</td>
                  <td className="py-2 pr-3">{bet.selection}</td>
                  <td className="py-2 pr-3">{bet.odds > 0 ? `+${bet.odds}` : bet.odds}</td>
                  <td className="py-2 pr-3">${bet.stake}</td>
                  <td className="py-2 pr-3 uppercase">{bet.status}</td>
                  <td className={`py-2 pr-3 font-bold ${(bet.result_profit ?? 0) >= 0 ? "text-[#00FF5B]" : "text-red-400"}`}>
                    {bet.result_profit != null ? `${bet.result_profit >= 0 ? "+" : ""}$${bet.result_profit}` : "--"}
                  </td>
                  <td className="py-2 pr-3">{bet.clv_pct != null ? `${bet.clv_pct}%` : "--"}</td>
                  <td className="py-2 pr-3 text-[10px] text-slate-500 uppercase">
                    {bet.graded_by === "auto" ? "Auto (ESPN)" : bet.graded_by === "manual" ? "Manual" : "--"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </motion.div>
  );
}

function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <label className="text-[9px] text-slate-500 uppercase tracking-wider block mb-1">{label}</label>
      {children}
    </div>
  );
}

function StatCard({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" | "neutral" }) {
  const color = tone === "pos" ? "text-[#00FF5B]" : tone === "neg" ? "text-red-400" : "text-white";
  return (
    <div className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-4">
      <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-lg font-bold ${color}`}>{value}</div>
    </div>
  );
}
