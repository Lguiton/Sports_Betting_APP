"use client";

import { useState, useCallback, useEffect } from "react";
import { motion } from "framer-motion";
import { Target, Loader2 } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";

const backendUrl = () => process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

type Bucket = { range: string; n: number; predicted_avg_pct: number; actual_win_rate_pct: number };
type Calibration = {
  total_resolved: number;
  buckets: Bucket[];
  brier_score: number | null;
  overall_accuracy_pct: number | null;
};

export default function Calibration() {
  const [sport, setSport] = useState("");
  const [data, setData] = useState<Calibration | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = sport ? `?sport=${sport}` : "";
      const res = await fetch(`${backendUrl()}/calibration${params}`);
      if (!res.ok) throw new Error("Failed to load calibration data");
      setData(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load calibration data");
    } finally {
      setLoading(false);
    }
  }, [sport]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-[#0A0D14] border border-[#1C212B] rounded-2xl p-6 min-h-[400px] flex flex-col gap-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-bold text-slate-300 uppercase tracking-widest flex items-center gap-2">
          <Target className="text-[#00FF5B]" size={18} /> Model Calibration
        </h2>
        <select
          value={sport}
          onChange={(e) => setSport(e.target.value)}
          className="bg-[#06080A] border border-[#1C212B] rounded-lg px-2 py-2 text-xs text-white"
        >
          <option value="">All Sports</option>
          <option value="NFL">NFL</option>
          <option value="NBA">NBA</option>
          <option value="MLB">MLB</option>
          <option value="NCAAF">NCAAF</option>
        </select>
      </div>

      <p className="text-[11px] text-slate-500">
        Every prediction the model makes gets logged, then auto-graded once you log that game&apos;s real result.
        This is the honesty check: when the model says &quot;70% favorite,&quot; does that side actually win about 70% of
        the time? A well-calibrated model has its bars land close together in every bucket.
      </p>

      {loading && (
        <div className="flex items-center gap-2 text-slate-500 text-xs py-10 justify-center">
          <Loader2 className="animate-spin" size={14} /> Loading...
        </div>
      )}
      {error && <div className="text-red-400 text-xs">{error}</div>}

      {!loading && data && data.total_resolved === 0 && (
        <p className="text-slate-600 text-sm italic text-center py-10">
          No resolved predictions yet. Ask the agent about a matchup, then log that game&apos;s real result in the
          Ratings tab -- predictions auto-resolve against logged results.
        </p>
      )}

      {!loading && data && data.total_resolved > 0 && (
        <>
          <div className="grid grid-cols-3 gap-4">
            <StatCard label="Resolved Predictions" value={String(data.total_resolved)} />
            <StatCard
              label="Overall Accuracy"
              value={data.overall_accuracy_pct != null ? `${data.overall_accuracy_pct}%` : "--"}
            />
            <StatCard
              label="Brier Score"
              value={data.brier_score != null ? data.brier_score.toFixed(3) : "--"}
              hint="Lower is better -- 0 is perfect, 0.25 is a coinflip"
            />
          </div>

          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.buckets} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1C212B" vertical={false} />
                <XAxis dataKey="range" tick={{ fill: "#64748B", fontSize: 11 }} axisLine={{ stroke: "#1C212B" }} tickLine={false} />
                <YAxis
                  domain={[0, 100]}
                  tick={{ fill: "#64748B", fontSize: 11 }}
                  axisLine={{ stroke: "#1C212B" }}
                  tickLine={false}
                  width={36}
                />
                <Tooltip
                  contentStyle={{ background: "#06080A", border: "1px solid #1C212B", borderRadius: 8, fontSize: 11 }}
                  labelStyle={{ color: "#94A3B8" }}
                  formatter={(value, name) => [`${value}%`, name]}
                />
                <Legend wrapperStyle={{ fontSize: 11, color: "#94A3B8" }} />
                <Bar dataKey="predicted_avg_pct" name="Predicted" fill="#475569" radius={[4, 4, 0, 0]} />
                <Bar dataKey="actual_win_rate_pct" name="Actual" fill="#00FF5B" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <table className="w-full text-xs text-left">
            <thead>
              <tr className="text-slate-500 uppercase text-[10px] tracking-wider border-b border-[#1C212B]">
                <th className="py-2 pr-3">Predicted Range</th>
                <th className="py-2 pr-3">Sample Size</th>
                <th className="py-2 pr-3">Predicted Avg</th>
                <th className="py-2 pr-3">Actual Win Rate</th>
              </tr>
            </thead>
            <tbody>
              {data.buckets.map((b) => (
                <tr key={b.range} className="border-b border-[#1C212B]/50 text-slate-300">
                  <td className="py-2 pr-3 text-white">{b.range}</td>
                  <td className="py-2 pr-3">{b.n}</td>
                  <td className="py-2 pr-3">{b.predicted_avg_pct}%</td>
                  <td className="py-2 pr-3 text-[#00FF5B] font-semibold">{b.actual_win_rate_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </motion.div>
  );
}

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="bg-[#06080A] border border-[#1C212B] rounded-xl p-4">
      <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">{label}</div>
      <div className="text-lg font-bold text-white">{value}</div>
      {hint && <div className="text-[9px] text-slate-600 mt-1">{hint}</div>}
    </div>
  );
}
